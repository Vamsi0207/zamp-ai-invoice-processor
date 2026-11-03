"""Diagnostic control-flow tests with explicit mocks; not live Google evidence."""
import json

import httpx
import pytest

from app.extraction import AIAdapter
from scripts import diagnose_gemini as diagnostic
from test_extraction import pages, response_body, sample_result


def envelope(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": value}]}}]}


def success_response(index):
    if index == 0:
        return envelope("OK")
    if index == 1:
        return envelope(json.dumps({"record_id": "DIAG-001", "amount": "12.00"}))
    if index == 2:
        return envelope(json.dumps({"invoice": {"invoice_number": "DIAG-002", "total": "12.00",
            "lines": [{"description": "Test item", "quantity": 2}]}}))
    return response_body("gemini")


def test_four_baselines_sequential_once_no_sampling_overrides():
    requests = []

    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "test-secret"
        assert "test-secret" not in str(request.url)
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=success_response(len(requests) - 1))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results, summary = diagnostic.diagnose(client, "test-secret", "gemini-3.5-flash-lite", pages())
    assert len(requests) == 4
    assert "generationConfig" not in requests[0]
    assert set(requests[1]["generationConfig"]["responseJsonSchema"]["properties"]) == {"record_id", "amount"}
    assert "invoice" in requests[2]["generationConfig"]["responseJsonSchema"]["properties"]
    assert all("temperature" not in r.get("generationConfig", {}) for r in requests)
    assert [r["category"] for r in results] == ["OK"] * 4
    assert results[0]["schema_conforms"] is None
    assert all(r["schema_conforms"] for r in results[1:])
    assert results[3]["evidence_validated"] is True
    assert summary["all_baselines_passed"] is True
    assert summary["root_cause_verified"] is False


def test_full_probe_matches_production_request_without_changing_adapter(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    expected = diagnostic.baseline_probes(pages())[3].body

    def handler(request):
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=response_body("gemini"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        AIAdapter("gemini", client).extract(pages())


@pytest.mark.parametrize("status,category", [(400, "INVALID_REQUEST"), (404, "MODEL_UNAVAILABLE"),
    (429, "RATE_LIMITED"), (503, "SERVICE_UNAVAILABLE")])
def test_first_failure_status_and_no_automatic_retry(status, category):
    calls = []

    def handler(request):
        index = len(calls)
        calls.append(json.loads(request.content))
        return httpx.Response(status, json={"error": {"message": "PRIVATE"}}) if index == 1 else httpx.Response(200, json=success_response(index))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results, summary = diagnostic.diagnose(client, "test", "gemini-3.5-flash-lite", pages())
    assert len(calls) == 4
    assert results[1]["http_status"] == status
    assert results[1]["category"] == category
    assert results[1]["schema_conforms"] is None
    assert summary["first_failed_level"] == "02_two_fields"
    assert summary["first_http_failure"] == "02_two_fields"
    assert summary["requests_sent"] == 4


def test_invalid_schema_and_evidence_never_count_as_success():
    payload = sample_result()
    payload["evidence"] = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        result = diagnostic.run_probe(client, "https://generativelanguage.googleapis.com/test", "test",
                                      diagnostic.baseline_probes(pages())[3], pages())
    assert result["category"] == "INVALID_RESPONSE"
    assert result["schema_conforms"] is True
    assert result["evidence_validated"] is False
    assert result["expectation_passed"] is None


def test_schema_conformance_separate_from_synthetic_expectation():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope(json.dumps({"record_id": "wrong", "amount": "12.00"}))))) as client:
        result = diagnostic.run_probe(client, "https://generativelanguage.googleapis.com/test", "test",
                                      diagnostic.baseline_probes(pages())[1], pages())
    assert result["http_status"] == 200
    assert result["schema_conforms"] is True
    assert result["expectation_passed"] is False
    assert result["category"] == "FIXTURE_EXPECTATION_FAILED"


@pytest.mark.parametrize("failure", ["bad-json", "blocked", "wrong-type", "timeout", "connection", "oversized"])
def test_safe_invalid_response_and_transport_diagnostics(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE-KEY PRIVATE-CONTENT")
        if failure == "connection":
            raise httpx.ConnectError("PRIVATE-KEY PRIVATE-CONTENT")
        if failure == "oversized":
            return httpx.Response(200, text="x" * 2_000_001)
        if failure == "bad-json":
            return httpx.Response(200, text="PRIVATE-CONTENT")
        if failure == "blocked":
            return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        return httpx.Response(200, json=envelope(json.dumps({"record_id": 7, "amount": 12})))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = diagnostic.run_probe(client, "https://generativelanguage.googleapis.com/test", "PRIVATE-KEY",
                                      diagnostic.baseline_probes(pages())[1], pages())
    assert result["category"] in {"INVALID_RESPONSE", "TIMEOUT", "CONNECTION_ERROR", "RESPONSE_TOO_LARGE"}
    assert "PRIVATE" not in json.dumps(result)


def test_only_allowlisted_provider_status_and_field_roots_are_printed():
    response = httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "PRIVATE-INVOICE",
        "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [
            {"field": "generation_config.response_json_schema.properties.PRIVATE", "description": "PRIVATE-KEY"},
            {"field": "PRIVATE-INVOICE"}]}]}})
    status, fields = diagnostic.safe_hints(response)
    assert status == "INVALID_ARGUMENT"
    assert fields == ["generationConfig.responseJsonSchema"]
    assert "PRIVATE" not in json.dumps((status, fields))
    assert diagnostic.safe_hints(httpx.Response(400, json={"error": {"status": "PRIVATE"}})) == (None, [])


def test_optional_isolation_changes_one_group_never_resends_same_payload():
    baselines = diagnostic.baseline_probes(pages())
    fingerprints = []

    def handler(request):
        body = json.loads(request.content)
        fingerprint = json.dumps(body, sort_keys=True)
        assert fingerprint not in fingerprints
        fingerprints.append(fingerprint)
        index = len(fingerprints) - 1
        if index < 3:
            return httpx.Response(200, json=success_response(index))
        if body == baselines[3].body:
            return httpx.Response(400)
        # The only passing full-schema variation removes titles.
        if body == diagnostic.isolation_probes(baselines)[2].body:
            return httpx.Response(200, json=response_body("gemini"))
        return httpx.Response(400)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, summary = diagnostic.diagnose(client, "test", "gemini-3.5-flash-lite", pages(), isolate=True)
    assert summary["requests_sent"] == 12
    assert summary["successful_controlled_differences"] == ["remove_titles"]
    assert summary["root_cause_verified"] is False
    assert baselines == diagnostic.baseline_probes(pages())
    for probe in diagnostic.isolation_probes(baselines)[2:]:
        assert probe.validation == "full"  # All still run original Pydantic/evidence checks.


def test_isolation_not_run_for_plain_request_failure_or_only_service_failure():
    for status in (400, 503):
        count = []
        with httpx.Client(transport=httpx.MockTransport(lambda r: count.append(1) or httpx.Response(status))) as client:
            _, summary = diagnostic.diagnose(client, "test", "gemini-3.5-flash-lite", pages(), isolate=True)
        assert len(count) == 4
        assert summary["isolation_ran"] is False


def test_cli_missing_key_sends_nothing_and_never_prints_configuration_values(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(diagnostic.httpx, "Client", lambda **kwargs: pytest.fail("No request without a key"))
    assert diagnostic.main([]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["requests_sent"] == 0
    assert output["category"] == "PROVIDER_NOT_CONFIGURED"


def test_cli_outputs_only_reports_and_summary_not_response_values(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-KEY")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=success_response(len(calls) - 1))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(diagnostic.httpx, "Client", lambda **kwargs: client)
    assert diagnostic.main([]) == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 5
    assert all(json.loads(line)["type"] in ("probe", "summary") for line in output.splitlines())
    for value in ("PRIVATE-KEY", "SYN-001", "400.00", "DIAG-001", "Test item"):
        assert value not in output
