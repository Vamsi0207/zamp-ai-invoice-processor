"""Provider contract tests use explicit HTTP mocks, never claimed as live API results."""
import json
import os

import httpx
import pytest

from app.extraction import AIAdapter, ExtractionResult, ProviderError, ProviderNotConfigured, validate_evidence
from test_documents import upload


def sample_result():
    invoice = {"vendor_name": "SYNTHETIC OFFICE SUPPLY", "vendor_reference": "DEMO-VENDOR",
        "invoice_number": "SYN-001", "po_number": "DEMO-PO", "currency": "USD", "total": "400.00",
        "tax": "0.00", "shipping": "0.00", "discount": "0.00", "lines": [
            {"line_reference": "L1", "description": "Office chairs", "quantity": 4, "unit_price": "100.00"}]}
    quotes = {"vendor_name": "SYNTHETIC OFFICE SUPPLY", "vendor_reference": "Vendor reference: DEMO-VENDOR",
        "invoice_number": "Invoice number: SYN-001", "po_number": "Purchase order: DEMO-PO", "currency": "Currency: USD",
        "total": "TOTAL DUE: USD 400.00", "tax": "Tax: USD 0.00", "shipping": "Shipping: USD 0.00",
        "discount": "Discount: USD 0.00"}
    for field in ("line_reference", "description", "quantity", "unit_price"):
        quotes[f"lines.0.{field}"] = "L1     Office chairs     4          100.00       400.00"
    return {"invoice": invoice, "evidence": [{"field": f, "page": 1, "quote": q} for f, q in quotes.items()]}


def pages():
    from app.documents import parse_pdf
    from test_documents import FIXTURES
    return parse_pdf((FIXTURES / "native_invoice.pdf").read_bytes())


def response_body(provider, result=None):
    content = json.dumps(result or sample_result())
    if provider == "gemini":
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]}
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_real_adapter_request_contract(provider, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY", "test-only-key")
    def handler(request):
        body = json.loads(request.content)
        assert request.url.scheme == "https"
        assert "test-only-key" not in str(request.url)
        if provider == "gemini":
            assert request.url.host == "generativelanguage.googleapis.com"
            assert request.headers["x-goog-api-key"] == "test-only-key"
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            schema = body["generationConfig"]["responseJsonSchema"]
        else:
            assert request.url.host == "api.openai.com"
            assert request.headers["Authorization"] == "Bearer test-only-key"
            assert body["response_format"]["json_schema"]["strict"] is True
            schema = body["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        return httpx.Response(200, json=response_body(provider))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = AIAdapter(provider, client).extract(pages())
    assert result.invoice.total == "400.00"
    assert len(result.evidence) == 13


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_missing_keys_fail_explicitly(provider, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfigured):
        AIAdapter(provider).extract(pages())


@pytest.mark.parametrize("change", ["invented_quote", "wrong_page", "missing_evidence", "unsupported_value", "unknown_field"])
def test_evidence_fail_closed(change):
    result = sample_result()
    if change == "invented_quote":
        result["evidence"][0]["quote"] = "Invented company name"
    elif change == "wrong_page":
        result["evidence"][0]["page"] = 2
    elif change == "missing_evidence":
        result["evidence"].pop()
    elif change == "unknown_field":
        result["evidence"][0]["field"] = "unknown"
    else:
        result["invoice"]["total"] = "999.00"
    with pytest.raises(ProviderError):
        validate_evidence(ExtractionResult.model_validate(result), pages())


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_not_fabricated_or_leaked(status, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-must-not-leak")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text="sensitive body"))) as client:
        with pytest.raises(ProviderError) as err:
            AIAdapter("gemini", client).extract(pages())
        assert "sensitive body" not in str(err.value)
        assert "test-key" not in str(err.value)


def test_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    def handler(request):
        raise httpx.ReadTimeout("timeout")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError):
            AIAdapter("openai", client).extract(pages())


@pytest.mark.parametrize("payload", [
    {}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"refusal": "refused", "content": None}}]},
])
def test_malformed_truncated_or_refused_output(payload, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ProviderError):
            AIAdapter("openai", client).extract(pages())


def test_extraction_api_records_draft_without_financial_allocation(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    document_id = upload(client).json()["id"]
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini")))) as http:
        client.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        response = client.post(f"/documents/{document_id}/extract", json={"provider": "gemini"})
    assert response.status_code == 200, response.text
    run = response.json()["extraction_runs"][0]
    assert run["status"] == "succeeded"
    assert run["result"]["invoice"]["invoice_number"] == "SYN-001"
    assert response.json()["requires_human_review"] is True
    with client.app.state.service.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0


def test_failed_extraction_audited(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    document_id = upload(client).json()["id"]
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        client.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        assert client.post(f"/documents/{document_id}/extract", json={"provider": "openai"}).status_code == 502
    run = client.get(f"/documents/{document_id}").json()["extraction_runs"][0]
    assert run["status"] == "failed"
    assert run["result"] is None


def test_api_configuration_and_provider_validation(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    document_id = upload(client).json()["id"]
    assert client.post(f"/documents/{document_id}/extract", json={"provider": "gemini"}).status_code == 503
    assert client.post(f"/documents/{document_id}/extract", json={"provider": "fake"}).status_code == 422
    assert client.post("/documents/missing/extract", json={"provider": "gemini"}).status_code == 404


def test_null_values_need_no_fabricated_evidence():
    data = {field: None for field in sample_result()["invoice"] if field != "lines"}
    data["lines"] = []
    result = ExtractionResult.model_validate({"invoice": data, "evidence": []})
    assert validate_evidence(result, pages()).invoice.total is None


def test_reviewed_document_invoice_uses_financial_engine(seeded):
    from conftest import invoice
    document_id = upload(seeded).json()["id"]
    response = seeded.post(f"/documents/{document_id}/invoices", json=invoice(total="1"))
    assert response.status_code == 201
    invoice_id = response.json()["id"]
    stored = seeded.get(f"/invoices/{invoice_id}").json()
    assert stored["source_document_id"] == document_id
    result = seeded.post(f"/invoices/{invoice_id}/process", json={"idempotency_key": "reviewed"}).json()
    assert result["decision"] == "Rejected"
    assert "INVALID_TOTAL" in result["reasons"]
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 0


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1.001", "not money"])
def test_bad_extracted_money_rejected(amount):
    from pydantic import ValidationError
    result = sample_result()
    result["invoice"]["total"] = amount
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(result)


def test_model_path_injection_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "../../other-model")
    with pytest.raises(ProviderNotConfigured):
        AIAdapter("gemini")


@pytest.mark.parametrize("provider,key", [("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_live_provider_opt_in(provider, key):
    if os.getenv("ZAMP_RUN_LIVE_AI") != "1" or not os.getenv(key):
        pytest.skip("Live API test requires explicit opt-in and configured credentials")
    result = AIAdapter(provider).extract(pages())
    assert result.invoice.invoice_number == "SYN-001"
    assert result.invoice.total == "400.00"
