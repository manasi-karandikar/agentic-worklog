"""Pure business-rule validators. Each returns a list of actionable error strings (empty = ok)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .schema import Invoice

TOLERANCE = 0.02  # currency units; absorbs rounding
ISO_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY", "AUD", "CAD", "CHF"}
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GST_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97"}
MIN_DATE = date(2000, 1, 1)
MAX_FUTURE_DAYS = 366      # invoice dated more than a year ahead is suspect
MAX_TERMS_DAYS = 366       # due date more than a year after invoice date is suspect


def _close(a: float, b: float, tol: float = TOLERANCE) -> bool:
    return abs(a - b) <= tol


def parse_iso_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def check_dates(inv: Invoice) -> list[str]:
    errors = []
    for name in ("invoice_date", "due_date"):
        val = getattr(inv, name)
        if val is not None and parse_iso_date(val) is None:
            errors.append(f"{name} '{val}' is not a valid ISO date YYYY-MM-DD; reformat it or return null if ambiguous")
    d1, d2 = parse_iso_date(inv.invoice_date or ""), parse_iso_date(inv.due_date or "")
    if d1 and d2 and d2 < d1:
        errors.append(f"due_date {inv.due_date} is before invoice_date {inv.invoice_date}; re-read both dates")
    if d1 and not (MIN_DATE <= d1 <= date.today() + timedelta(days=MAX_FUTURE_DAYS)):
        errors.append(f"invoice_date {inv.invoice_date} is outside the plausible range ({MIN_DATE} to one year from today); re-read the year")
    if d1 and d2 and d2 > d1 + timedelta(days=MAX_TERMS_DAYS):
        errors.append(f"due_date {inv.due_date} is more than {MAX_TERMS_DAYS} days after invoice_date {inv.invoice_date}; re-read both dates")
    return errors


def check_currency(inv: Invoice) -> list[str]:
    if inv.currency is not None and inv.currency not in ISO_CURRENCIES:
        return [f"currency '{inv.currency}' is not a recognised ISO 4217 code; use e.g. INR, USD, EUR (symbols like ₹ → INR)"]
    return []


def check_line_items(inv: Invoice) -> list[str]:
    errors = []
    for i, li in enumerate(inv.line_items):
        if None not in (li.quantity, li.unit_price, li.amount):
            expected = round(li.quantity * li.unit_price, 2)
            if not _close(expected, li.amount):
                errors.append(
                    f"line_items[{i}].amount {li.amount} != quantity {li.quantity} x unit_price {li.unit_price} = {expected}; re-read that row"
                )
    return errors


def check_totals(inv: Invoice) -> list[str]:
    errors = []
    amounts = [li.amount for li in inv.line_items]
    line_sum = round(sum(a for a in amounts if a is not None), 2) if amounts and None not in amounts else None
    if inv.subtotal is not None and line_sum is not None and not _close(line_sum, inv.subtotal):
        errors.append(f"subtotal {inv.subtotal} != sum of line_items amounts {line_sum}; re-check lines and subtotal")
    base = inv.subtotal if inv.subtotal is not None else line_sum
    if base is not None and inv.total_amount is not None:
        expected = round(base + (inv.tax_amount or 0.0), 2)
        if not _close(expected, inv.total_amount):
            errors.append(
                f"total_amount {inv.total_amount} != subtotal/lines {base} + tax_amount {inv.tax_amount or 0.0} = {expected}; "
                "re-read the totals block (if the printed total really differs, keep it as printed and lower confidence.total_amount)"
            )
    return errors


def gstin_check_digit(first14: str) -> str:
    """GSTN mod-36 check character for the first 14 characters."""
    total = 0
    for i, ch in enumerate(first14):
        p = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def check_gstin(gstin: str | None, label: str = "GSTIN") -> list[str]:
    """Format, state code and check digit. None = not printed (handled by review policy, not here)."""
    if gstin is None:
        return []
    if not GSTIN_RE.match(gstin):
        return [f"{label} '{gstin}' has invalid format (15 chars, e.g. 27AAPFU0939F1ZV); re-read it, or keep as printed and lower confidence"]
    errors = []
    if gstin[:2] not in GST_STATE_CODES:
        errors.append(f"{label} '{gstin}' has unknown state code {gstin[:2]} (valid 01-38, 97)")
    if gstin_check_digit(gstin[:14]) != gstin[14]:
        errors.append(f"{label} '{gstin}' fails the check digit (expected last character {gstin_check_digit(gstin[:14])})")
    return errors


def check_tax_ids(gstin: str | None = None, pan: str | None = None,
                  buyer_gstin: str | None = None) -> list[str]:
    errors = check_gstin(gstin, "vendor GSTIN") + check_gstin(buyer_gstin, "buyer GSTIN")
    if pan is not None and not PAN_RE.match(pan):
        errors.append(f"PAN '{pan}' has invalid format (e.g. ABCDE1234F)")
    if gstin and pan and GSTIN_RE.match(gstin) and PAN_RE.match(pan) and gstin[2:12] != pan:
        errors.append(f"vendor GSTIN '{gstin}' embeds PAN {gstin[2:12]} which differs from printed PAN '{pan}'")
    return errors


def check_gst_taxes(inv: Invoice) -> list[str]:
    """Tax must follow the printed rates; CGST=SGST; intra-state (CGST+SGST) and IGST never mix."""
    errors = []
    cgst, sgst, igst = inv.cgst or 0.0, inv.sgst or 0.0, inv.igst or 0.0
    if cgst and sgst and not _close(cgst, sgst):
        errors.append(f"cgst {cgst} != sgst {sgst}; they must be equal, re-read the tax block")
    if igst and (cgst or sgst):
        errors.append(f"igst {igst} printed together with cgst/sgst; a sale is either intra-state or inter-state, re-read the tax block")
    components = round(cgst + sgst + igst, 2)
    if components and inv.tax_amount is not None and not _close(components, inv.tax_amount):
        errors.append(f"cgst+sgst+igst = {components} != tax_amount {inv.tax_amount}; re-read the tax block")
    lines = inv.line_items
    if lines and all(li.amount is not None and li.gst_rate is not None for li in lines):
        expected = round(sum(li.amount * li.gst_rate / 100 for li in lines), 2)
        tol = TOLERANCE + 0.01 * len(lines)   # per-line rounding
        actual = components or inv.tax_amount
        if actual is not None and abs(expected - actual) > tol:
            errors.append(f"tax {actual} does not match line amounts x GST rates = {expected}; re-read rates and tax amounts "
                          "(if the printed tax really differs, keep it as printed and lower confidence)")
    return errors


def validate_invoice(inv: Invoice) -> list[str]:
    return (check_dates(inv) + check_currency(inv) + check_line_items(inv) + check_totals(inv)
            + check_tax_ids(inv.vendor_gstin, inv.vendor_pan, inv.buyer_gstin) + check_gst_taxes(inv))
