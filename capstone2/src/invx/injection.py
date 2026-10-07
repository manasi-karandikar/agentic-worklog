"""Prompt-injection defence, in code (the prompt rule in SKILL.md is only the first layer).

Layer 2 - PDF scan *before* trusting the model: look at the text layer for instruction-like phrases and for
text a human cannot see (tiny font, white-on-white). Layer 3 - scan the model's extracted strings for
instruction-like text. Any hit becomes a needs_review reason; values are never silently "fixed".
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|extraction)? ?(instructions|rules)",
    r"system (override|prompt|message)",
    r"(you are|act as) (now )?(an? )?(ai|assistant|model|llm)",
    r"\b(ai|llm) (assistant|model)\b",
    r"note to the (ai|model|assistant)",
    r"reveal (your|the) (system )?prompt",
    r"do not (flag|mark|set)[^.]{0,40}(review|needs_review)",
    r"(mark|set|treat)[^.]{0,30}(approved|pre-approved|paid)",
    r"(set|change|output|report)\s+\w*[\s_]*(total_amount|invoice_number|vendor_name|buyer_name|confidence)",
    r"set every confidence",
    r"</?instructions?>",
    r"skip (the )?validation",
]
_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)
MIN_VISIBLE_PT = 4.0
WHITE = 0xFFFFFF


def find_instruction_text(text: str) -> list[str]:
    """Return the instruction-like snippets found in `text` (empty = clean)."""
    return [m.group(0) for m in _RE.finditer(text or "")]


def scan_pdf(pdf_path: Path) -> list[str]:
    """Review reasons from the PDF text layer. Scanned (image-only) PDFs have no text layer: no hits, no hidden text."""
    try:
        return _scan_pdf(pdf_path)
    except Exception:  # unreadable/corrupt PDF: the extraction call itself surfaces that failure
        return []


def _scan_pdf(pdf_path: Path) -> list[str]:
    reasons: list[str] = []
    hidden: list[str] = []
    with pymupdf.open(pdf_path) as pdf:
        full = []
        for page in pdf:
            # white text is only legitimate on a coloured fill (header bands, table headers)
            fills = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()
                     if d.get("fill") and tuple(round(c, 2) for c in d["fill"][:3]) != (1.0, 1.0, 1.0)]
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        t = span["text"].strip()
                        if not t:
                            continue
                        full.append(t)
                        on_fill = any(r.intersects(pymupdf.Rect(span["bbox"])) for r in fills)
                        if span["size"] < MIN_VISIBLE_PT or (span["color"] == WHITE and not on_fill):
                            hidden.append(t)
    if hidden:
        reasons.append(f"hidden text in PDF (tiny or white): '{' '.join(hidden)[:80]}'")
    hits = find_instruction_text(" ".join(full))
    if hits:
        reasons.append(f"possible prompt injection in document text: '{hits[0]}'")
    return reasons


def scan_extracted(strings: list[str | None]) -> list[str]:
    hits = [h for s in strings if s for h in find_instruction_text(s)]
    return [f"instruction-like text in extracted fields: '{hits[0]}'"] if hits else []
