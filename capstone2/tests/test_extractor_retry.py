import json
from types import SimpleNamespace

from invx.extractor import extract_invoice
from invx.evaluate import score_doc, summarize
from invx.review import review_reasons
from invx.schema import Invoice

GOOD = {
    "invoice_number": "INV-1", "invoice_date": "2025-01-02", "vendor_name": "Acme", "currency": "USD",
    "line_items": [{"description": "x", "quantity": 2, "unit_price": 50, "amount": 100}],
    "subtotal": 100, "tax_amount": 10, "total_amount": 110,
    "confidence": {"invoice_number": 1, "invoice_date": 1, "vendor_name": 1, "currency": 1, "total_amount": 1},
}
BAD = {**GOOD, "total_amount": 999}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        usage = SimpleNamespace(prompt_token_count=1000, cached_content_token_count=0,
                                candidates_token_count=100, thoughts_token_count=0)
        return SimpleNamespace(text=json.dumps(self.replies.pop(0)), usage_metadata=usage)


def run(tmp_path, monkeypatch, replies):
    monkeypatch.setenv("INVX_MIN_INTERVAL", "0")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    client = FakeClient(replies)
    return extract_invoice(client, pdf, model="m"), client


def test_clean_first_try(tmp_path, monkeypatch):
    res, client = run(tmp_path, monkeypatch, [GOOD])
    assert res.status == "ok" and res.attempts == 1 and len(client.calls) == 1


def test_retry_passes_validation_error_back(tmp_path, monkeypatch):
    res, client = run(tmp_path, monkeypatch, [BAD, GOOD])
    assert res.status == "ok" and res.attempts == 2
    last_msg = client.calls[1][-1].parts[0].text
    assert "total_amount 999" in last_msg


def test_persistent_failure_is_needs_review(tmp_path, monkeypatch):
    res, _ = run(tmp_path, monkeypatch, [BAD, BAD, BAD])
    assert res.status == "needs_review" and res.attempts == 3
    assert any("validation failed" in r for r in res.review_reasons)


def test_null_required_field_needs_review():
    inv = Invoice(**{**GOOD, "invoice_number": None})
    assert "missing required field: invoice_number" in review_reasons(inv)


def test_low_confidence_needs_review():
    inv = Invoice(**{**GOOD, "confidence": {**GOOD["confidence"], "invoice_date": 0.4}})
    assert any("invoice_date" in r for r in review_reasons(inv))


def test_confident_complete_doc_has_no_reasons():
    assert review_reasons(Invoice(**GOOD)) == []


def test_scoring_and_summary():
    label = {**GOOD, "due_date": None}
    scores = score_doc(Invoice(**GOOD), label)
    assert all(scores.values())
    rows = [{"scores": scores, "attempts": 2, "latency_s": 3.0, "notional_cost_usd": 0.001,
             "status": "needs_review", "expected_needs_review": True}]
    s = summarize(rows)
    assert s["retry_rate"] == 1 and s["review_precision"] == 1 and s["median_latency_s"] == 3.0
