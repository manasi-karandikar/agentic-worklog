"""The extraction tool, designed per "Writing effective tools for agents".

`invoice_extract` is the agent-facing tool: one clear purpose, a description that says when (not)
to use it, concise output by default, and errors that tell the caller what to do next.
`extract_one` is the same operation returning objects, used by the CLI/eval.
"""
from __future__ import annotations

import os
from pathlib import Path

from google import genai

from .extractor import extract_invoice
from .metrics import DocMetrics
from .schema import ExtractionResult

TOOL_SPEC = {
    "name": "invoice_extract",
    "description": (
        "Extract structured fields (invoice number, dates, vendor, buyer, currency, line items, totals) "
        "from ONE invoice PDF. Use for invoices only; not for bank statements, salary slips or scans of "
        "non-financial documents. Returns status 'ok' or 'needs_review' (missing/low-confidence fields "
        "are listed in review_reasons - route those to a human, do not guess). "
        "Default output is concise; pass response_format='detailed' for line items and confidences."
    ),
    "parameters": {
        "path": "Path to a single .pdf invoice file.",
        "response_format": "'concise' (default) or 'detailed'.",
    },
}


def make_client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set. Create a free key in Google AI Studio and put it in .env.")
    return genai.Client(api_key=key)


def extract_one(path: Path, client=None) -> tuple[ExtractionResult, DocMetrics]:
    client = client or make_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    m = DocMetrics(file=path.name, model=model)
    return extract_invoice(client, path, model=model, metrics=m), m


def invoice_extract(path: str, response_format: str = "concise", client=None) -> str:
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return f"Error: '{path}' is not a .pdf file. Pass the path to a single PDF invoice."
    if not p.is_file():
        return f"Error: file '{path}' not found. Check the path (use an absolute path or one relative to the working directory)."
    if response_format not in ("concise", "detailed"):
        return "Error: response_format must be 'concise' or 'detailed'."
    res, m = extract_one(p, client)
    if res.status == "failed":
        return f"Error: extraction failed after {res.attempts} attempt(s): {res.error}. Retry later or check the file is a readable invoice."
    inv = res.invoice
    lines = [
        f"status: {res.status}",
        f"invoice_number: {inv.invoice_number}", f"invoice_date: {inv.invoice_date}",
        f"vendor: {inv.vendor_name}", f"total: {inv.total_amount} {inv.currency}",
    ]
    if res.review_reasons:
        lines.append("review_reasons: " + "; ".join(res.review_reasons))
    if response_format == "detailed":
        lines.append(inv.model_dump_json(indent=2))
        lines.append(f"attempts: {res.attempts}, latency_s: {m.latency_s:.1f}, notional_cost_usd: {m.notional_cost_usd:.5f}")
    return "\n".join(lines)
