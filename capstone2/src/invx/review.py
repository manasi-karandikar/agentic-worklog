"""needs_review policy: flag instead of guessing."""
from __future__ import annotations

from .schema import CONFIDENCE_FIELDS, REQUIRED_FIELDS, Invoice

DEFAULT_THRESHOLD = 0.8


def review_reasons(inv: Invoice, residual_errors: list[str] | None = None,
                   threshold: float = DEFAULT_THRESHOLD) -> list[str]:
    reasons = []
    for f in REQUIRED_FIELDS:
        if getattr(inv, f) is None:
            reasons.append(f"missing required field: {f}")
    for f in CONFIDENCE_FIELDS:
        c = getattr(inv.confidence, f)
        if getattr(inv, f) is not None and c < threshold:
            reasons.append(f"low confidence on {f} ({c:.2f} < {threshold})")
    has_gst = any(v for v in (inv.cgst, inv.sgst, inv.igst)) or any(li.gst_rate for li in inv.line_items)
    if has_gst and inv.vendor_gstin is None:
        reasons.append("GST charged but vendor GSTIN is missing")
    for e in residual_errors or []:
        reasons.append(f"validation failed: {e}")
    return reasons
