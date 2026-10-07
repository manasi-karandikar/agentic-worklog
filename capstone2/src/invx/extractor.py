"""Gemini call + validate/retry loop."""
from __future__ import annotations

import os
import time
from pathlib import Path

from google.genai import errors, types
from pydantic import ValidationError

from .metrics import DocMetrics
from .injection import scan_extracted, scan_pdf
from .review import review_reasons
from .schema import ExtractionResult, Invoice
from .validators import validate_invoice

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 2          # validation retries (so up to 3 attempts)
MAX_429_RETRIES = 4
SKILL_PATH = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "invoice-extraction" / "SKILL.md"
_last_call = 0.0


def load_system_prompt() -> str:
    """SKILL.md body (frontmatter stripped). Stable text => eligible for implicit caching."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def _throttle() -> None:
    """Free tier is ~10 RPM; keep a minimum gap between calls."""
    global _last_call
    gap = float(os.getenv("INVX_MIN_INTERVAL", "6.5"))
    wait = _last_call + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _generate(client, model: str, contents, config, m: DocMetrics):
    for attempt in range(MAX_429_RETRIES + 1):
        _throttle()
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            m.add_usage(getattr(resp, "usage_metadata", None))
            return resp
        except errors.APIError as e:
            if getattr(e, "code", None) in (429, 503) and attempt < MAX_429_RETRIES:
                time.sleep(15 * 2 ** attempt)
                continue
            raise


def _strings(inv: Invoice) -> list[str | None]:
    return [inv.invoice_number, inv.vendor_name, inv.buyer_name, inv.vendor_gstin, inv.buyer_gstin,
            *(li.description for li in inv.line_items)]


def extract_invoice(client, pdf_path: Path, model: str | None = None,
                    metrics: DocMetrics | None = None) -> ExtractionResult:
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    m = metrics or DocMetrics(file=pdf_path.name, model=model)
    config = types.GenerateContentConfig(
        system_instruction=load_system_prompt(),
        response_mime_type="application/json",
        response_schema=Invoice,
        temperature=0.0,
    )
    pdf = types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf")
    contents = [types.Content(role="user", parts=[pdf, types.Part.from_text(text="Extract this invoice.")])]
    start = time.perf_counter()
    inv, errs, raw = None, [], ""
    try:
        for attempt in range(1, MAX_RETRIES + 2):
            m.attempts = attempt
            resp = _generate(client, model, contents, config, m)
            raw = resp.text or ""
            try:
                inv = Invoice.model_validate_json(raw)
                errs = validate_invoice(inv)
            except ValidationError as e:
                inv, errs = None, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
            if not errs:
                break
            contents += [
                types.Content(role="model", parts=[types.Part.from_text(text=raw)]),
                types.Content(role="user", parts=[types.Part.from_text(text=(
                    "Your JSON failed validation:\n- " + "\n- ".join(errs) +
                    "\nRe-read the document and return the full corrected JSON."))]),
            ]
    except Exception as e:  # network/quota/etc.: record, don't crash a batch
        m.latency_s = time.perf_counter() - start
        m.status = "failed"
        return ExtractionResult(file=pdf_path.name, status="failed", attempts=m.attempts,
                                error=f"{type(e).__name__}: {e}")
    m.latency_s = time.perf_counter() - start
    if inv is None:
        m.status = "failed"
        return ExtractionResult(file=pdf_path.name, status="failed", attempts=m.attempts,
                                error="Output never matched schema: " + "; ".join(errs))
    reasons = review_reasons(inv, residual_errors=errs)
    reasons += scan_pdf(pdf_path) + scan_extracted(_strings(inv))
    m.status = "needs_review" if reasons else "ok"
    return ExtractionResult(file=pdf_path.name, status=m.status, invoice=inv,
                            review_reasons=reasons, attempts=m.attempts)
