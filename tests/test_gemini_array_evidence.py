"""Windows HTTP observations motivate the change; these tests use explicit mocks."""
import copy
import json
import traceback

import httpx
import pytest
from pydantic import ValidationError

from app.extraction import AIAdapter, EvidenceValidationError, ExtractionResult, ProviderError, gemini_response_schema, validate_evidence
from scripts import diagnose_gemini as diagnostic
from test_extraction import pages, response_body, sample_result


def test_only_max_items_omitted_from_provider_hints():
    schema = gemini_response_schema()

    def assert_no_max(node):
        if isinstance(node, dict):
            assert "maxItems" not in node
            for value in node.values():
                assert_no_max(value)
        elif isinstance(node, list):
            for value in node:
                assert_no_max(value)

    assert_no_max(schema)
    invoice = schema["properties"]["invoice"]
    assert invoice["properties"]["lines"]["type"] == "array"
    assert schema["properties"]["evidence"]["type"] == "array"
    assert invoice["additionalProperties"] is False
    assert invoice["title"] == "ExtractedInvoice"
    assert schema["properties"]["evidence"]["items"]["properties"]["page"]["maximum"] == 20
    original = ExtractionResult.model_json_schema()
    assert original["$defs"]["ExtractedInvoice"]["properties"]["lines"]["maxItems"] == 200
    assert original["properties"]["evidence"]["maxItems"] == 1000


@pytest.mark.parametrize("field,limit", [("lines", 200), ("evidence", 1000)])
def test_local_array_limits_still_enforced(field, limit, monkeypatch):
    payload = sample_result()
    target = payload["invoice"][field] if field == "lines" else payload[field]
    target[:] = [copy.deepcopy(target[0]) for _ in range(limit)]
    ExtractionResult.model_validate(payload)  # Exact bound is schema-valid, not an approval.
    target.append(copy.deepcopy(target[0]))
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        with pytest.raises(ProviderError) as caught:
            AIAdapter("gemini", client).extract(pages())
    assert caught.value.code == "INVALID_RESPONSE"
    assert caught.value.details()["validation_stage"] == "pydantic"
    assert caught.value.http_status == 200


@pytest.mark.parametrize("mutation,category,reason", [
    ("invented-quote", "UNSUPPORTED_SOURCE_QUOTE", "QUOTE_NOT_IN_SOURCE"),
    ("missing-evidence", "MISSING_FIELD_EVIDENCE", "NON_NULL_FIELD_WITHOUT_EVIDENCE"),
    ("numeric", "INCORRECT_NUMERIC_EVIDENCE", "NUMERIC_VALUE_NOT_SUPPORTED"),
    ("path", "INVALID_FIELD_OR_PAGE_REFERENCE", "INVALID_FIELD_PATH"),
    ("prefix", "INVALID_FIELD_OR_PAGE_REFERENCE", "UNEXPECTED_INVOICE_PREFIX"),
    ("page", "INVALID_FIELD_OR_PAGE_REFERENCE", "INVALID_PAGE_REFERENCE"),
    ("value", "OTHER_SCHEMA_EVIDENCE_MISMATCH", "FIELD_VALUE_NOT_SUPPORTED"),
    ("null-value", "OTHER_SCHEMA_EVIDENCE_MISMATCH", "EVIDENCE_WITHOUT_EXTRACTED_VALUE"),
])
def test_evidence_categories_preserve_rejection_and_redact_values(mutation, category, reason):
    payload = sample_result()
    if mutation == "invented-quote":
        payload["evidence"][0]["quote"] = "PRIVATE-SOURCE-CONTENT"
    elif mutation == "missing-evidence":
        payload["evidence"].pop()
    elif mutation == "numeric":
        payload["invoice"]["total"] = "401.00"
    elif mutation == "path":
        payload["evidence"][0]["field"] = "PRIVATE-FIELD-PATH"
    elif mutation == "prefix":
        payload["evidence"][0]["field"] = "invoice.vendor_name"
    elif mutation == "page":
        payload["evidence"][0]["page"] = 2
    elif mutation == "value":
        payload["invoice"]["vendor_name"] = "PRIVATE-SOURCE-CONTENT"
    else:
        payload["invoice"]["vendor_name"] = None
    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(ExtractionResult.model_validate(payload), pages())
    details = caught.value.details()
    assert details["code"] == "INVALID_RESPONSE"
    assert details["validation_stage"] == "evidence"
    assert details["evidence_category"] == category
    assert details["evidence_reason"] == reason
    assert "PRIVATE" not in json.dumps(details) + str(caught.value) + "".join(traceback.format_exception(caught.value))


def test_quote_on_wrong_page_remains_rejected():
    source = pages()
    original = source[0]["text"]
    payload = sample_result()
    quote = payload["evidence"][0]["quote"]
    source[0]["text"] = original.replace(quote, "")
    source.append({"page": 2, "text": quote, "method": "native"})
    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(ExtractionResult.model_validate(payload), source)
    assert caught.value.details()["evidence_reason"] == "QUOTE_ON_DIFFERENT_PAGE"


def test_canonical_synthetic_evidence_still_passes():
    result = ExtractionResult.model_validate(sample_result())
    assert validate_evidence(result, pages()) is result


def test_live_check_reports_accepted_response_with_failed_evidence(monkeypatch, capsys):
    from scripts import check_gemini
    payload = sample_result()
    payload["evidence"][0]["quote"] = "PRIVATE-SOURCE-CONTENT"
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-KEY")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        monkeypatch.setattr(check_gemini, "AIAdapter", lambda provider: AIAdapter(provider, client))
        assert check_gemini.main() == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "failed"
    assert report["http_status"] == 200
    assert report["pydantic_validated"] is True
    assert report["evidence_validated"] is False
    assert report["evidence_category"] == "UNSUPPORTED_SOURCE_QUOTE"
    assert "PRIVATE" not in output and "SYN-001" not in output


def test_four_individual_array_bound_probes_only_change_limits():
    probes = diagnostic.array_bound_probes(pages())
    original = diagnostic.baseline_probes(pages())[3].body
    assert [p.name for p in probes] == ["no_array_bounds", "lines_max_only", "evidence_max_only", "both_max_bounds"]
    for probe, expected in zip(probes, [(None, None), (200, None), (None, 1000), (200, 1000)]):
        body = copy.deepcopy(probe.body)
        schema = body["generationConfig"]["responseJsonSchema"]
        line = schema["properties"]["invoice"]["properties"]["lines"]
        evidence = schema["properties"]["evidence"]
        assert (line.pop("maxItems", None), evidence.pop("maxItems", None)) == expected
        assert "minItems" not in line and "minItems" not in evidence
        assert body == original
        assert probe.validation == "full"


def test_matrix_reports_http_acceptance_even_when_evidence_fails():
    calls = []
    invalid = sample_result()
    invalid["evidence"] = []

    def handler(request):
        body = json.loads(request.content)
        assert body not in calls
        calls.append(body)
        schema = body["generationConfig"]["responseJsonSchema"]
        if "maxItems" in schema["properties"]["evidence"]:
            return httpx.Response(400)
        return httpx.Response(200, json=response_body("gemini", invalid))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results, summary = diagnostic.diagnose_array_bounds(client, "test", "gemini-3.5-flash-lite", pages())
    assert len(calls) == 4
    assert summary["http_accepted_variants"] == ["no_array_bounds", "lines_max_only"]
    assert summary["http_400_variants"] == ["evidence_max_only", "both_max_bounds"]
    assert summary["fully_validated_variants"] == []
    assert results[0]["evidence_category"] == "MISSING_FIELD_EVIDENCE"
    assert summary["historical_minItems_count"] == 0
    assert summary["historical_maxItems_count"] == 2
    assert summary["root_cause_verified"] is False  # Mock evidence is not a live conclusion.


def test_array_bound_cli_makes_four_calls_and_prints_no_model_data(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-KEY")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=response_body("gemini"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(diagnostic.httpx, "Client", lambda **kwargs: client)
    assert diagnostic.main(["--array-bounds"]) == 0
    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]
    assert len(calls) == 4
    assert records[-1]["type"] == "array_bound_summary"
    assert records[-1]["requests_sent"] == 4
    for value in ("PRIVATE-KEY", "SYN-001", "400.00", "Office chairs"):
        assert value not in output


def test_original_isolation_summary_keeps_http_acceptance_separate():
    from test_gemini_diagnostics import success_response
    baselines = diagnostic.baseline_probes(pages())
    accepted = diagnostic.isolation_probes(baselines)[2].body  # Controlled removal of titles.
    calls = []
    invalid = sample_result()
    invalid["evidence"] = []

    def handler(request):
        body = json.loads(request.content)
        index = len(calls)
        calls.append(body)
        if index < 3:
            return httpx.Response(200, json=success_response(index))
        if body == accepted:
            return httpx.Response(200, json=response_body("gemini", invalid))
        return httpx.Response(400)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, summary = diagnostic.diagnose(client, "test", "gemini-3.5-flash-lite", pages(), isolate=True)
    assert summary["http_accepted_controlled_differences"] == ["remove_titles"]
    assert summary["successful_controlled_differences"] == []
