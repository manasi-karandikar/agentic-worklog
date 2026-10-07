"""Generate 20 synthetic invoice PDFs + ground-truth labels (no real data).

Usage: python scripts/gen_synthetic.py
Outputs: data/pdfs/inv_001.pdf ... and data/labels/inv_001.json ...
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SEED = 42
ROOT = Path(__file__).resolve().parent.parent
PDF_DIR, LABEL_DIR = ROOT / "data" / "pdfs", ROOT / "data" / "labels"

CURRENCIES = {"INR": "Rs.", "USD": "$", "EUR": "EUR "}
DATE_FMTS = ["%d %b %Y", "%B %d, %Y", "%Y-%m-%d", "%d-%b-%Y"]
ITEMS = ["Consulting services", "Cloud hosting (monthly)", "Software licence", "Office supplies",
         "Annual maintenance", "Training workshop", "Hardware repair", "Data migration", "Courier charges"]
# 15 clean, then 5 defects (index -> defect)
DEFECTS = {15: "missing_invoice_number", 16: "wrong_total", 17: "ambiguous_date",
           18: "missing_invoice_date", 19: "rotated_page"}


def build_truth(fake: Faker, rng: random.Random, idx: int) -> dict:
    cur = rng.choice(list(CURRENCIES))
    items = []
    for _ in range(rng.randint(1, 5)):
        qty = rng.randint(1, 10)
        price = round(rng.uniform(10, 900), 2)
        items.append({"description": rng.choice(ITEMS), "quantity": float(qty),
                      "unit_price": price, "amount": round(qty * price, 2)})
    subtotal = round(sum(i["amount"] for i in items), 2)
    rate = rng.choice([0, 5, 12, 18])
    tax = round(subtotal * rate / 100, 2)
    inv_date = date(2025, 1, 1) + timedelta(days=rng.randint(0, 330))
    return {
        "invoice_number": f"INV-{rng.randint(2025, 2026)}-{rng.randint(1000, 9999)}",
        "invoice_date": inv_date.isoformat(),
        "due_date": (inv_date + timedelta(days=rng.choice([15, 30, 45]))).isoformat(),
        "vendor_name": fake.company(), "buyer_name": fake.company(),
        "currency": cur, "line_items": items, "subtotal": subtotal,
        "tax_amount": tax, "total_amount": round(subtotal + tax, 2), "_tax_rate": rate,
    }


def apply_defect(truth: dict, defect: str | None) -> tuple[dict, dict]:
    """Return (label_truth, printed_doc). Label = what a careful human would record from the PDF."""
    label, printed = dict(truth), dict(truth)
    if defect == "missing_invoice_number":
        label["invoice_number"] = printed["invoice_number"] = None
    elif defect == "wrong_total":
        printed["total_amount"] = label["total_amount"] = round(truth["total_amount"] + 100, 2)
    elif defect == "ambiguous_date":
        d = date.fromisoformat(truth["invoice_date"]).replace(day=3, month=4)  # 03/04/2025 style
        printed["_date_text"] = d.strftime("%d/%m/%Y")
        label["invoice_date"] = None  # ambiguous -> must be null/needs_review
    elif defect == "missing_invoice_date":
        label["invoice_date"] = printed["invoice_date"] = None
    return label, printed


def money(cur: str, v: float) -> str:
    return f"{CURRENCIES[cur]}{v:,.2f}"


def render(path: Path, doc: dict, layout: int, rng: random.Random, rotate: bool, date_fmt: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    if rotate:
        c.rotate(90); c.translate(0, -w); w, h = h, w
    cur = doc["currency"]
    date_text = doc.get("_date_text") or (
        date.fromisoformat(doc["invoice_date"]).strftime(date_fmt) if doc["invoice_date"] else None)
    due_text = date.fromisoformat(doc["due_date"]).strftime(date_fmt) if doc["due_date"] else None
    left, right = 20 * mm, w - 20 * mm

    # header by layout
    c.setFont("Helvetica-Bold", 18)
    if layout == 0:
        c.drawString(left, h - 25 * mm, doc["vendor_name"])
        c.setFont("Helvetica-Bold", 22); c.drawRightString(right, h - 25 * mm, "INVOICE")
    elif layout == 1:
        c.drawCentredString(w / 2, h - 25 * mm, "TAX INVOICE")
        c.setFont("Helvetica", 12); c.drawCentredString(w / 2, h - 32 * mm, doc["vendor_name"])
    elif layout == 2:
        c.setFillColor(colors.HexColor("#223355")); c.rect(0, h - 35 * mm, w, 35 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white); c.drawString(left, h - 22 * mm, doc["vendor_name"])
        c.setFont("Helvetica", 12); c.drawRightString(right, h - 22 * mm, "Invoice"); c.setFillColor(colors.black)
    else:
        c.drawString(left, h - 25 * mm, "Invoice"); c.setFont("Helvetica", 10)
        c.drawString(left, h - 31 * mm, f"From: {doc['vendor_name']}")

    c.setFont("Helvetica", 10)
    y = h - 48 * mm
    if doc["invoice_number"]:
        c.drawString(left, y, f"Invoice No: {doc['invoice_number']}"); y -= 6 * mm
    if date_text:
        c.drawString(left, y, f"Date: {date_text}"); y -= 6 * mm
    if due_text:
        c.drawString(left, y, f"Due: {due_text}"); y -= 6 * mm
    c.drawString(left, y, f"Bill To: {doc['buyer_name']}"); y -= 6 * mm
    c.drawString(left, y, f"Currency: {cur}"); y -= 12 * mm

    # table
    c.setFont("Helvetica-Bold", 10)
    cols = [left, left + 85 * mm, left + 105 * mm, left + 135 * mm]
    for x, t in zip(cols, ["Description", "Qty", "Unit price", "Amount"]):
        c.drawString(x, y, t)
    c.line(left, y - 2 * mm, right, y - 2 * mm); y -= 8 * mm
    c.setFont("Helvetica", 10)
    for li in doc["line_items"]:
        c.drawString(cols[0], y, li["description"]); c.drawString(cols[1], y, f"{li['quantity']:g}")
        c.drawString(cols[2], y, money(cur, li["unit_price"])); c.drawString(cols[3], y, money(cur, li["amount"]))
        y -= 7 * mm
    y -= 5 * mm

    # totals (layout 3 right-aligned box, others plain)
    rows = [("Subtotal", doc["subtotal"])]
    if doc["_tax_rate"]:
        label = f"Tax ({doc['_tax_rate']}%)" if layout != 1 else f"CGST+SGST ({doc['_tax_rate']}%)"
        rows.append((label, doc["tax_amount"]))
    rows.append(("Total", doc["total_amount"]))
    if layout == 3:
        c.rect(right - 70 * mm, y - 7 * mm * len(rows) + 3 * mm, 70 * mm, 7 * mm * len(rows), stroke=1, fill=0)
    for name, val in rows:
        c.setFont("Helvetica-Bold" if name == "Total" else "Helvetica", 10)
        c.drawString(right - 65 * mm, y, name); c.drawRightString(right - 2 * mm, y, money(cur, val)); y -= 7 * mm
    c.showPage(); c.save()


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True); LABEL_DIR.mkdir(parents=True, exist_ok=True)
    Faker.seed(SEED)
    fake, rng = Faker(), random.Random(SEED)
    for i in range(20):
        defect = DEFECTS.get(i)
        truth = build_truth(fake, rng, i)
        label, printed = apply_defect(truth, defect)
        name = f"inv_{i + 1:03d}"
        render(PDF_DIR / f"{name}.pdf", printed, layout=i % 4, rng=rng,
               rotate=defect == "rotated_page", date_fmt=rng.choice(DATE_FMTS))
        out = {k: v for k, v in label.items() if not k.startswith("_")}
        out["defect"] = defect
        # rotated page is a robustness test: a good model should still extract everything
        out["expected_needs_review"] = defect in {"missing_invoice_number", "wrong_total",
                                                  "ambiguous_date", "missing_invoice_date"}
        (LABEL_DIR / f"{name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote 20 PDFs to {PDF_DIR} and labels to {LABEL_DIR}")


if __name__ == "__main__":
    main()
