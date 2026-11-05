"""Synthetic regression tests with HTTP mocks, not live Gemini verification."""
import copy
import json
import traceback

import httpx
import pytest

from app.extraction import (AIAdapter, CANONICAL_EVIDENCE_PATH_DESCRIPTION, EvidenceValidationError,
    ExtractionResult, SYSTEM_PROMPT, canonicalize_gemini_evidence, gemini_response_schema, validate_evidence)
from scripts import diagnose_gemini as diagnostic
from test_extraction import pages, response_body, sample_result


def prefixed_result():
    result = sample_result()
    for item in result["evidence"]:
        item["field"] = "invoice." + item["field"]
    return result


def test_prompt_and_provider_schema_document_canonical_paths():
    description = gemini_response_schema()["properties"]["evidence"]["items"]["properties"]["field"]["description"]
    assert description == CANONICAL_EVIDENCE_PATH_DESCRIPTION
    for path in ("vendor_name", "vendor_reference", "invoice_number", "po_number", "currency", "total", "tax", "shipping", "discount", "lines.0.quantity"):
        assert path in description
        assert path in SYSTEM_PROMPT
    assert "Do NOT prefix any path with invoice." in description
    assert "zero-based index" in description
    assert "NOT\ninvoice.vendor_name" in SYSTEM_PROMPT
    assert "invoice wrapper" in SYSTEM_PROMPT


def test_exact_prefix_normalization_is_copy_only_and_preserves_source_data():
    original = ExtractionResult.model_validate(prefixed_result())
    before = copy.deepcopy(original.model_dump())
    normalized = canonicalize_gemini_evidence(original)
    assert original.model_dump() == before
    assert normalized.invoice.model_dump() == original.invoice.model_dump()
    assert [e.field for e in normalized.evidence] == [e["field"] for e in sample_result()["evidence"]]
    assert [(e.page, e.quote) for e in normalized.evidence] == [(e.page, e.quote) for e in original.evidence]
    assert validate_evidence(normalized, pages()) is normalized
    assert canonicalize_gemini_evidence(normalized) is normalized
    # The underlying validator remains strict; only the explicit boundary handles aliases.
    with pytest.raises(EvidenceValidationError, match="evidence failed"):
        validate_evidence(original, pages())


@pytest.mark.parametrize("path", [
    "invoice.unknown", "invoice.invoice.total", "Invoice.total", "invoice. total", "invoice..total",
    "invoice.lines[0].quantity", "invoice.lines.00.quantity", "invoice.lines.1.quantity",
    "invoice.lines.-1.quantity", "invoice.lines.*.quantity", "invoice.lines.0", "invoice.lines",
    "#/invoice/total", "invoice/total", "invoice.total.extra", "total.extra",
], ids=["unknown", "repeated", "case", "space", "empty-component", "bracket", "leading-zero", "out-of-range",
        "negative-index", "wildcard", "object-target", "array-target", "json-pointer", "slash", "extra-suffix", "unknown-canonical"])
def test_unknown_or_ambiguous_syntax_remains_rejected(path):
    payload = sample_result()
    payload["evidence"][0]["field"] = path
    result = ExtractionResult.model_validate(payload)
    with pytest.raises(EvidenceValidationError):
        validate_evidence(canonicalize_gemini_evidence(result), pages())


def test_prefix_cannot_target_null_field():
    payload = prefixed_result()
    payload["invoice"]["vendor_name"] = None
    with pytest.raises(EvidenceValidationError):
        canonicalize_gemini_evidence(ExtractionResult.model_validate(payload))


@pytest.mark.parametrize("reverse", [False, True], ids=["canonical-first", "alias-first"])
def test_colliding_aliases_are_not_merged(reverse):
    payload = sample_result()
    alias = {**payload["evidence"][0], "field": "invoice.vendor_name"}
    payload["evidence"].append(alias)
    if reverse:
        payload["evidence"].reverse()
    with pytest.raises(EvidenceValidationError) as caught:
        canonicalize_gemini_evidence(ExtractionResult.model_validate(payload))
    assert caught.value.details()["evidence_reason"] == "AMBIGUOUS_FIELD_PATH"


@pytest.mark.parametrize("mutation,reason", [
    ("page", "INVALID_PAGE_REFERENCE"), ("quote", "QUOTE_NOT_IN_SOURCE"),
    ("numeric", "NUMERIC_VALUE_NOT_SUPPORTED"), ("coverage", "NON_NULL_FIELD_WITHOUT_EVIDENCE"),
    ("string-value", "FIELD_VALUE_NOT_SUPPORTED"),
])
def test_normalized_paths_never_bypass_verification(mutation, reason, monkeypatch):
    payload = prefixed_result()
    if mutation == "page":
        payload["evidence"][0]["page"] = 2
    elif mutation == "quote":
        payload["evidence"][0]["quote"] = "PRIVATE-SOURCE-CONTENT"
    elif mutation == "numeric":
        payload["invoice"]["total"] = "401.00"
    elif mutation == "coverage":
        payload["evidence"].pop()
    else:
        payload["invoice"]["vendor_name"] = "PRIVATE-SOURCE-CONTENT"
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-KEY")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        with pytest.raises(EvidenceValidationError) as caught:
            AIAdapter("gemini", client).extract(pages())
    assert caught.value.details()["evidence_reason"] == reason
    assert "PRIVATE" not in json.dumps(caught.value.details()) + "".join(traceback.format_exception(caught.value))


def test_gemini_response_is_canonical_but_openai_remains_strict(monkeypatch):
    payload = prefixed_result()
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        result = AIAdapter("gemini", client).extract(pages())
    assert all(not e.field.startswith("invoice.") for e in result.evidence)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("openai", payload)))) as client:
        with pytest.raises(EvidenceValidationError):
            AIAdapter("openai", client).extract(pages())


def test_live_check_and_diagnostic_use_same_normalization(monkeypatch, capsys):
    from scripts import check_gemini
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-KEY")
    payload = prefixed_result()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", payload)))) as client:
        monkeypatch.setattr(check_gemini, "AIAdapter", lambda provider: AIAdapter(provider, client))
        assert check_gemini.main() == 0
        probe = diagnostic.baseline_probes(pages())[3]
        report = diagnostic.run_probe(client, "https://generativelanguage.googleapis.com/test", "PRIVATE-KEY", probe, pages())
    output = capsys.readouterr().out
    assert json.loads(output)["evidence_validated"] is True
    assert "PRIVATE-KEY" not in output and "SYN-001" not in output
    assert report["category"] == "OK"
    assert report["evidence_validated"] is True


def test_normalized_extraction_still_requires_human_confirmation(client, monkeypatch):
    from scripts.seed import seed
    from test_workflows import upload_run
    seed(client.app.state.service.database.path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini", prefixed_result())))) as http:
        client.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        run = upload_run(client, provider="gemini")
    assert run["status"] == "Review"
    assert run["invoice_id"] is None
    assert run["stages"]["validation"]["status"] == "needs_review"
    assert all(not e["field"].startswith("invoice.") for e in run["extraction"]["evidence"])
    with client.app.state.service.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 0
