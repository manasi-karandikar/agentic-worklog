"""Field-level scoring against hand-checked labels, plus run-level summary stats."""
from __future__ import annotations

import statistics

from .schema import Invoice

STRING_FIELDS = ["invoice_number", "invoice_date", "due_date", "vendor_name", "buyer_name", "currency"]
NUMBER_FIELDS = ["subtotal", "tax_amount", "total_amount"]
FIELDS = STRING_FIELDS + NUMBER_FIELDS + ["line_item_count"]
# GST fields: scored only on docs whose label has the key (legacy labels pre-date them)
EXTRA_STRING_FIELDS = ["vendor_gstin", "buyer_gstin", "vendor_pan"]
EXTRA_NUMBER_FIELDS = ["cgst", "sgst", "igst"]
EXTRA_FIELDS = EXTRA_STRING_FIELDS + EXTRA_NUMBER_FIELDS


def _norm(v):
    return v.strip().casefold() if isinstance(v, str) else v


def field_correct(field: str, pred: dict | None, label: dict) -> bool:
    if pred is None:
        return False
    if field == "line_item_count":
        return len(pred.get("line_items", [])) == len(label.get("line_items", []))
    p, l = pred.get(field), label.get(field)
    if field in EXTRA_NUMBER_FIELDS:  # an absent tax line and 0.00 mean the same thing
        p, l = p or 0.0, l or 0.0
    if p is None or l is None:
        return p is None and l is None
    if field in NUMBER_FIELDS or field in EXTRA_NUMBER_FIELDS:
        return abs(float(p) - float(l)) <= 0.01
    return _norm(p) == _norm(l)


def score_doc(pred_inv: Invoice | None, label: dict) -> dict[str, bool]:
    pred = pred_inv.model_dump() if pred_inv else None
    fields = FIELDS + [f for f in EXTRA_FIELDS if f in label]
    return {f: field_correct(f, pred, label) for f in fields}


def summarize(rows: list[dict]) -> dict:
    """rows: dicts with scores, attempts, latency_s, notional_cost_usd, status, expected_needs_review."""
    n = len(rows)
    acc = {f: sum(r["scores"][f] for r in rows) / n for f in FIELDS}
    flagged = [r["status"] == "needs_review" for r in rows]
    expected = [r["expected_needs_review"] for r in rows]
    tp = sum(f and e for f, e in zip(flagged, expected))
    lat = sorted(r["latency_s"] for r in rows)
    extra = {f: [r["scores"][f] for r in rows if f in r["scores"]] for f in EXTRA_FIELDS}
    by_defect: dict = {}
    for r in rows:
        by_defect.setdefault(r.get("defect") or "clean", []).append(r)
    return {
        "docs": n,
        "extra_field_accuracy": {f: sum(v) / len(v) for f, v in extra.items() if v},
        "by_defect": {
            d: {"docs": len(g), "expected_review": sum(x["expected_needs_review"] for x in g),
                "flagged": sum(x["status"] == "needs_review" for x in g),
                "flagged_correctly": sum(x["status"] == "needs_review" and x["expected_needs_review"] for x in g),
                "field_accuracy": sum(sum(v for k, v in x["scores"].items() if k in FIELDS) for x in g) / (len(g) * len(FIELDS))}
            for d, g in by_defect.items()},
        "field_accuracy": acc,
        "overall_field_accuracy": sum(acc.values()) / len(acc),
        "retry_rate": sum(r["attempts"] > 1 for r in rows) / n,
        "failed": sum(r["status"] == "failed" for r in rows),
        "review_precision": tp / sum(flagged) if any(flagged) else None,
        "review_recall": tp / sum(expected) if any(expected) else None,
        "cost_per_doc_usd": sum(r["notional_cost_usd"] for r in rows) / n,
        "median_latency_s": statistics.median(lat),
        "p95_latency_s": lat[min(n - 1, int(round(0.95 * (n - 1))))],
    }
