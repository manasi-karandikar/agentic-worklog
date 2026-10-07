# invx — invoice PDF extraction CLI

Extracts structured data from invoice PDFs with Gemini (native PDF input), validates with Pydantic,
retries with the validation error, and flags uncertain docs as `needs_review`.

## Commands
- Install: `../.venv/Scripts/python.exe -m pip install -e ".[dev]"` (venv lives one level up)
- Tests: `python -m pytest`
- Generate synthetic data: `python scripts/gen_synthetic.py`
- Extract: `invx extract data/pdfs/inv_001.pdf` (or a directory)
- Eval (20 docs): `invx eval`

## Rules
- **Data safety:** synthetic or public sample documents only. Never commit or process real customer data. `.env` is git-ignored.
- **Null over guess:** a missing/unclear field is `null` with low confidence, never invented. Docs with null required fields or confidence < 0.8 are `needs_review`.
- **Single source of truth for instructions:** `.claude/skills/invoice-extraction/SKILL.md` is loaded as the system prompt. Edit it there.
- **Validators are pure functions** in `src/invx/validators.py`, covered by pytest. Add a test with every new rule.
- Money is `Decimal`, never float. Dates are ISO `YYYY-MM-DD`.

## Tool design (Anthropic, "Writing effective tools for agents")
- One purpose per tool, clear namespaced name (`invoice_extract`), description says when to use it and when not to.
- Unambiguous parameter names; concise output by default, `response_format="detailed"` on request.
- Errors must be actionable: say what went wrong and what to do next.
- Return high-signal fields (names, not opaque IDs); keep token cost low.

## Notes
- Gemini free tier: real cost is $0; cost logged is *notional* (tokens × paid rates in `metrics.py`).
- Free tier is rate limited; the extractor throttles and backs off on 429.
