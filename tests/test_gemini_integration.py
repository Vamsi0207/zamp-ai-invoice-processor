"""Explicit HTTP mocks; no live provider success is implied by these tests."""
import copy
import json
import traceback

import httpx
import pytest

from app.extraction import AIAdapter, DEFAULT_GEMINI_MODEL, ExtractionResult, ProviderError, gemini_response_schema
from test_documents import upload
from test_extraction import pages, response_body, sample_result
from test_workflows import upload_run


def test_gemini_schema_uses_supported_keywords_preserving_fields_and_nullability():
    original = copy.deepcopy(ExtractionResult.model_json_schema())
    schema = gemini_response_schema()
    supported = {"type", "format", "title", "description", "enum", "minItems", "maxItems", "minimum", "maximum",
                 "required", "additionalProperties", "properties", "items", "anyOf"}

    def check(node):
        assert set(node) <= supported
        for child in node.get("properties", {}).values():
            check(child)
        if "items" in node:
            check(node["items"])
        for child in node.get("anyOf", []):
            check(child)

    check(schema)
    invoice = schema["properties"]["invoice"]
    assert set(invoice["properties"]) == set(sample_result()["invoice"])
    assert set(invoice["required"]) == set(invoice["properties"])
    assert invoice["additionalProperties"] is False
    assert invoice["properties"]["currency"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    line = invoice["properties"]["lines"]["items"]
    assert set(line["properties"]) == {"line_reference", "description", "quantity", "unit_price"}
    assert line["properties"]["quantity"]["anyOf"][0]["minimum"] == 1
    assert "maxItems" not in invoice["properties"]["lines"]
    evidence = schema["properties"]["evidence"]
    assert "maxItems" not in evidence
    assert set(evidence["items"]["required"]) == {"field", "page", "quote"}
    assert evidence["items"]["properties"]["page"]["maximum"] == 20
    assert ExtractionResult.model_json_schema() == original
    assert original["$defs"]["ExtractedInvoice"]["properties"]["lines"]["maxItems"] == 200
    assert original["properties"]["evidence"]["maxItems"] == 1000
    assert original["$defs"]["Evidence"]["properties"]["quote"]["minLength"] == 1
    assert original["$defs"]["ExtractedInvoice"]["properties"]["currency"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"


@pytest.mark.parametrize("model", ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash"])
def test_gemini_request_omits_sampling_overrides(model, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", model)
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")

    def handler(request):
        body = json.loads(request.content)
        assert str(request.url).endswith(f"/models/{model}:generateContent")
        assert set(body["generationConfig"]) == {"responseMimeType", "responseJsonSchema"}
        assert body["generationConfig"]["responseJsonSchema"] == gemini_response_schema()
        return httpx.Response(200, json=response_body("gemini"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert AIAdapter("gemini", client).extract(pages()).evidence


@pytest.mark.parametrize("status,code,retryable", [
    (400, "INVALID_REQUEST", False), (401, "AUTHENTICATION_FAILED", False),
    (403, "ACCESS_DENIED", False), (404, "MODEL_UNAVAILABLE", False),
    (429, "RATE_LIMITED", True), (503, "SERVICE_UNAVAILABLE", True),
    (500, "UPSTREAM_ERROR", True),
])
def test_safe_http_classification_no_bodies_headers_or_key(status, code, retryable, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-API-KEY")
    transport = httpx.MockTransport(lambda r: httpx.Response(status,
        json={"error": {"message": "PRIVATE-INVOICE-CONTENT"}}, headers={"Authorization": "PRIVATE-AUTH-HEADER"}))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ProviderError) as caught:
            AIAdapter("gemini", client).extract(pages())
    error = caught.value
    assert error.details() == {"code": code, "http_status": status, "retryable": retryable}
    serialized = str(error) + repr(error.__dict__) + "".join(traceback.format_exception(error))
    for secret in ("PRIVATE-API-KEY", "PRIVATE-INVOICE-CONTENT", "PRIVATE-AUTH-HEADER"):
        assert secret not in serialized


@pytest.mark.parametrize("mutation", ["empty-quote", "long-quote", "currency-pattern", "missing-evidence", "invented-evidence", "extra-field", "missing-field", "invalid-money"])
def test_gemini_projection_does_not_weaken_response_validation(mutation, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    result = sample_result()
    if mutation == "empty-quote":
        result["evidence"][0]["quote"] = ""
    elif mutation == "long-quote":
        result["evidence"][0]["quote"] = "X" * 2001
    elif mutation == "currency-pattern":
        result["invoice"]["currency"] = "usd"
    elif mutation == "missing-evidence":
        result["evidence"].pop()
    elif mutation == "invented-evidence":
        result["evidence"][0]["quote"] = "PRIVATE-INVOICE-CONTENT"
    elif mutation == "extra-field":
        result["invoice"]["approve"] = True
    elif mutation == "missing-field":
        del result["invoice"]["total"]
    else:
        result["invoice"]["total"] = "PRIVATE-INVOICE-CONTENT"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", result)))) as client:
        with pytest.raises(ProviderError) as caught:
            AIAdapter("gemini", client).extract(pages())
    assert caught.value.code == "INVALID_RESPONSE"
    assert "PRIVATE-INVOICE-CONTENT" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("payload", [
    {"promptFeedback": {"blockReason": "SAFETY"}}, {"candidates": []},
    {"candidates": [None]}, {"candidates": [{"finishReason": "MAX_TOKENS"}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [None]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}}]},
], ids=["blocked", "empty", "malformed", "truncated", "bad-parts", "bad-json"])
def test_gemini_invalid_responses_fail_closed(payload, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ProviderError) as error:
            AIAdapter("gemini", client).extract(pages())
    assert error.value.code == "INVALID_RESPONSE"


def test_gemini_ignores_thought_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    payload = response_body("gemini")
    payload["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "not response JSON"})
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        assert AIAdapter("gemini", client).extract(pages()).invoice.total == "400.00"


@pytest.mark.parametrize("status,code", [(400, "INVALID_REQUEST"), (404, "MODEL_UNAVAILABLE"), (429, "RATE_LIMITED"), (503, "SERVICE_UNAVAILABLE")])
def test_error_classification_survives_api_and_workflow(client, monkeypatch, status, code):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"message": "PRIVATE-INVOICE-CONTENT"}}))
    with httpx.Client(transport=transport) as http:
        client.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        document_id = upload(client).json()["id"]
        response = client.post(f"/documents/{document_id}/extract", json={"provider": "gemini"})
        assert response.status_code == 502
        assert response.headers["X-Provider-Error-Code"] == code
        assert "PRIVATE-INVOICE-CONTENT" not in response.text
        run = upload_run(client, provider="gemini")
        assert run["status"] == "failed"
        assert run["error"]["code"] == code
        assert run["error"]["http_status"] == status
        assert run["error"]["retryable"] == (status in (429, 503))
        assert "PRIVATE-INVOICE-CONTENT" not in json.dumps(run)


def test_default_model_and_whitespace_consistent_with_configuration(client, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert AIAdapter("gemini").model == DEFAULT_GEMINI_MODEL
    assert client.get("/configuration").json()["providers"]["gemini"]["model"] == DEFAULT_GEMINI_MODEL
    monkeypatch.setenv("GEMINI_MODEL", " gemini-3.5-flash-lite\n")
    assert AIAdapter("gemini").model == "gemini-3.5-flash-lite"
    assert client.get("/configuration").json()["providers"]["gemini"]["model"] == "gemini-3.5-flash-lite"


def test_check_script_reports_validation_without_invoice_contents(monkeypatch, capsys):
    from scripts import check_gemini

    class MockAdapter:
        def extract(self, document_pages):
            assert document_pages[0]["method"] == "native"
            return ExtractionResult.model_validate(sample_result())

    monkeypatch.setattr(check_gemini, "AIAdapter", lambda provider: MockAdapter())
    assert check_gemini.main() == 0
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["status"] == "passed"
    assert summary["evidence_validated"] is True
    assert summary["evidence_count"] == 13
    assert "SYN-001" not in output and "400.00" not in output


def test_check_script_reports_safe_classification(monkeypatch, capsys):
    from scripts import check_gemini

    class MockAdapter:
        def extract(self, document_pages):
            raise ProviderError("Provider rejected the request", code="INVALID_REQUEST", http_status=400)

    monkeypatch.setattr(check_gemini, "AIAdapter", lambda provider: MockAdapter())
    assert check_gemini.main() == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["code"] == "INVALID_REQUEST"
    assert summary["http_status"] == 400


def test_check_script_does_not_accept_incorrect_fixture_fields(monkeypatch, capsys):
    from scripts import check_gemini

    class MockAdapter:
        def extract(self, document_pages):
            result = ExtractionResult.model_validate(sample_result())
            result.invoice.total = "0.00"
            return result

    monkeypatch.setattr(check_gemini, "AIAdapter", lambda provider: MockAdapter())
    assert check_gemini.main() == 1
    assert json.loads(capsys.readouterr().out)["code"] == "INVALID_RESPONSE"
