"""Bounded, opt-in Gemini request isolation using only synthetic data.

No application request/validation rules are changed. No provider text is printed.
"""
import argparse
import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.documents import parse_pdf
from app.extraction import AIAdapter, ExtractionResult, ProviderError, SYSTEM_PROMPT, gemini_response_schema, http_failure, validate_evidence


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MinimalRecord(StrictModel):
    record_id: str
    amount: str


class SmallLine(StrictModel):
    description: str
    quantity: int


class SmallInvoice(StrictModel):
    invoice_number: str
    total: str
    lines: list[SmallLine]


class SmallResult(StrictModel):
    invoice: SmallInvoice


@dataclass
class Probe:
    name: str
    body: dict
    validation: str
    difference: str | None = None


def structured_body(prompt, schema):
    return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema}}


def baseline_probes(pages):
    minimal = {"type": "object", "properties": {
        "record_id": {"type": "string"}, "amount": {"type": "string"}},
        "required": ["record_id", "amount"]}
    nested = {"type": "object", "properties": {"invoice": {"type": "object", "properties": {
        "invoice_number": {"type": "string"}, "total": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "description": {"type": "string"}, "quantity": {"type": "integer"}},
            "required": ["description", "quantity"]}}}, "required": ["invoice_number", "total", "lines"]}},
        "required": ["invoice"]}
    full = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps({"pages": pages}, ensure_ascii=False)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": gemini_response_schema()}}
    return [
        Probe("01_plain_text", {"contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}]}, "plain"),
        Probe("02_two_fields", structured_body(
            "Return a synthetic record with record_id DIAG-001 and amount 12.00 as a string.", minimal), "minimal"),
        Probe("03_nested_invoice", structured_body(
            "Return a synthetic invoice with invoice_number DIAG-002, total 12.00 as a string, "
            "and one line with description Test item and integer quantity 2.", nested), "nested"),
        Probe("04_full_invoice_evidence", full, "full"),
    ]


def transform_schema(node, remove=(), nullable_types=False):
    """Diagnostic-only schema variations; never used by the production adapter."""
    result = {}
    for key, value in node.items():
        if key in remove:
            continue
        if key == "properties":
            result[key] = {name: transform_schema(schema, remove, nullable_types) for name, schema in value.items()}
        elif key == "items":
            result[key] = transform_schema(value, remove, nullable_types)
        elif key == "anyOf":
            result[key] = [transform_schema(schema, remove, nullable_types) for schema in value]
        else:
            result[key] = copy.deepcopy(value)
    choices = result.get("anyOf", [])
    if nullable_types and len(choices) == 2:
        nonnull = [choice for choice in choices if choice.get("type") != "null"]
        if len(nonnull) == 1 and any(choice.get("type") == "null" for choice in choices):
            branch = nonnull[0]
            if isinstance(branch.get("type"), str):
                del result["anyOf"]
                result.update(branch)
                result["type"] = [branch["type"], "null"]
    return result


def isolation_probes(baselines):
    """Eight distinct, controlled differences. No retries or endpoint migration."""
    minimal = baselines[1]
    old_contract = copy.deepcopy(minimal.body)
    schema = old_contract["generationConfig"].pop("responseJsonSchema")

    def openapi_types(node):
        result = copy.deepcopy(node)
        if "type" in result:
            result["type"] = result["type"].upper()
        if "properties" in result:
            result["properties"] = {key: openapi_types(value) for key, value in result["properties"].items()}
        return result

    old_contract["generationConfig"]["responseSchema"] = openapi_types(schema)
    new_contract = copy.deepcopy(minimal.body)
    new_contract["generationConfig"] = {"responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}}}
    probes = [Probe("05_minimal_responseSchema", old_contract, "minimal", "responseSchema_wire_contract"),
              Probe("06_minimal_responseFormat", new_contract, "minimal", "responseFormat_wire_contract")]
    full = baselines[3]
    for name, keywords in (("titles", ("title",)), ("additionalProperties", ("additionalProperties",)),
                           ("numeric_bounds", ("minimum", "maximum")), ("array_bounds", ("minItems", "maxItems"))):
        body = copy.deepcopy(full.body)
        body["generationConfig"]["responseJsonSchema"] = transform_schema(
            body["generationConfig"]["responseJsonSchema"], remove=keywords)
        probes.append(Probe(f"full_without_{name}", body, "full", f"remove_{name}"))
    body = copy.deepcopy(full.body)
    body["generationConfig"]["responseJsonSchema"] = transform_schema(
        body["generationConfig"]["responseJsonSchema"], nullable_types=True)
    probes.append(Probe("full_nullable_type_arrays", body, "full", "nullable_type_array_instead_of_anyOf"))
    body = copy.deepcopy(full.body)
    del body["systemInstruction"]
    probes.append(Probe("full_without_system_instruction", body, "full", "remove_systemInstruction"))
    return probes


# Never print arbitrary provider strings: even error descriptions can echo input.
SAFE_STATUSES = {"INVALID_ARGUMENT", "NOT_FOUND", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "PERMISSION_DENIED",
                 "UNAUTHENTICATED", "FAILED_PRECONDITION", "INTERNAL", "DEADLINE_EXCEEDED"}
SAFE_FIELDS = {"contents": "contents", "system_instruction": "systemInstruction", "systemInstruction": "systemInstruction",
               "generation_config": "generationConfig", "generationConfig": "generationConfig",
               "generation_config.response_json_schema": "generationConfig.responseJsonSchema",
               "generationConfig.responseJsonSchema": "generationConfig.responseJsonSchema",
               "generation_config.response_mime_type": "generationConfig.responseMimeType",
               "generationConfig.responseMimeType": "generationConfig.responseMimeType",
               "generation_config.response_schema": "generationConfig.responseSchema",
               "generationConfig.responseSchema": "generationConfig.responseSchema",
               "generation_config.response_format": "generationConfig.responseFormat",
               "generationConfig.responseFormat": "generationConfig.responseFormat"}


def safe_hints(response):
    status, fields = None, set()
    try:
        error = response.json().get("error", {})
        value = error.get("status")
        if isinstance(value, str) and value in SAFE_STATUSES:
            status = value
        for detail in error.get("details", []):
            if detail.get("@type") != "type.googleapis.com/google.rpc.BadRequest":
                continue
            for violation in detail.get("fieldViolations", []):
                field = violation.get("field")
                if isinstance(field, str):
                    # Report only a known request field, never an arbitrary suffix.
                    for known in sorted(SAFE_FIELDS, key=len, reverse=True):
                        if field == known or field.startswith(known + ".") or field.startswith(known + "["):
                            fields.add(SAFE_FIELDS[known])
                            break
    except (ValueError, TypeError, AttributeError):
        pass
    return status, sorted(fields)


def response_text(response):
    data = response.json()
    candidate = data["candidates"][0]
    if candidate.get("finishReason") != "STOP":
        raise ValueError("Incomplete response")
    text = "".join(part.get("text", "") for part in candidate["content"]["parts"] if not part.get("thought"))
    if not text:
        raise ValueError("Missing response text")
    return text


def run_probe(client, url, key, probe, pages):
    result = {"type": "probe", "step": probe.name, "http_status": None, "category": None,
              "schema_conforms": None, "evidence_validated": None, "expectation_passed": None,
              "difference": probe.difference, "provider_status": None, "provider_field_hints": []}
    try:
        response = client.post(url, headers={"x-goog-api-key": key}, json=probe.body)
        result["http_status"] = response.status_code
        if not response.is_success:
            result["category"] = http_failure(response.status_code).code
            if len(response.content) <= 2_000_000:
                result["provider_status"], result["provider_field_hints"] = safe_hints(response)
            return result
        if len(response.content) > 2_000_000:
            result["category"] = "RESPONSE_TOO_LARGE"
            return result
        text = response_text(response)
        if probe.validation == "plain":
            result["expectation_passed"] = text.strip() == "OK"
        else:
            result["schema_conforms"] = False
            if probe.validation == "minimal":
                parsed = MinimalRecord.model_validate_json(text)
                result["expectation_passed"] = parsed.record_id == "DIAG-001" and parsed.amount == "12.00"
            elif probe.validation == "nested":
                parsed = SmallResult.model_validate_json(text)
                result["expectation_passed"] = parsed.invoice.model_dump() == {
                    "invoice_number": "DIAG-002", "total": "12.00", "lines": [{"description": "Test item", "quantity": 2}]}
            else:
                parsed = ExtractionResult.model_validate_json(text)
                result["schema_conforms"] = True
                result["evidence_validated"] = False
                validate_evidence(parsed, pages)
                result["evidence_validated"] = True
                result["expectation_passed"] = parsed.invoice.invoice_number == "SYN-001" and parsed.invoice.total == "400.00"
            result["schema_conforms"] = True
        result["category"] = "OK" if result["expectation_passed"] else "FIXTURE_EXPECTATION_FAILED"
    except httpx.TimeoutException:
        result["category"] = "TIMEOUT"
    except httpx.HTTPError:
        result["category"] = "CONNECTION_ERROR"
    except ProviderError:
        result["category"] = "INVALID_RESPONSE"
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
        result["category"] = "INVALID_RESPONSE"
    return result


def diagnose(client, key, model, pages, isolate=False, emit=None):
    """Run four baselines once; optional distinct probes never replace app settings."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    baselines = baseline_probes(pages)
    results, fingerprints = [], set()

    def run(probe):
        fingerprint = hashlib.sha256(json.dumps(probe.body, sort_keys=True).encode()).digest()
        if fingerprint in fingerprints:
            return  # A no-op transform must never become a retry of the same request.
        fingerprints.add(fingerprint)
        result = run_probe(client, url, key, probe, pages)
        results.append(result)
        if emit:
            emit(result)

    for probe in baselines:
        run(probe)
    baseline_results = results[:]
    isolation_ran = isolate and baseline_results[0]["http_status"] == 200 and any(
        r["http_status"] == 400 for r in baseline_results[1:])
    if isolation_ran:
        for probe in isolation_probes(baselines):
            run(probe)
    boundary = next((r["step"] for r in baseline_results if r["category"] != "OK"), None)
    http_boundary = next((r["step"] for r in baseline_results if r["http_status"] is not None and r["http_status"] != 200), None)
    candidates = []
    for result in results[4:]:
        comparison = baseline_results[1] if result["step"].startswith(("05_", "06_")) else baseline_results[3]
        if comparison["http_status"] == 400 and result["category"] == "OK":
            candidates.append(result["difference"])
    summary = {"type": "summary", "requests_sent": len(results), "first_failed_level": boundary,
               "first_http_failure": http_boundary, "isolation_ran": isolation_ran,
               "successful_controlled_differences": candidates, "root_cause_verified": False,
               "all_baselines_passed": boundary is None,
               "next_action": "compare_controlled_differences" if candidates else "inspect_failure_boundary" if boundary else "investigate_local_backend_request_differences"}
    if emit:
        emit(summary)
    return results, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic-only Gemini request diagnosis. Four calls, at most twelve with --isolate; no retries.")
    parser.add_argument("--isolate", action="store_true", help="If text succeeds and a structured request returns 400, run up to eight distinct controlled probes")
    args = parser.parse_args(argv)
    emit = lambda value: print(json.dumps(value), flush=True)
    try:
        adapter = AIAdapter("gemini")
        if not adapter.key:
            emit({"type": "configuration", "category": "PROVIDER_NOT_CONFIGURED", "requests_sent": 0, "root_cause_verified": False})
            return 2
        pages = parse_pdf((Path(__file__).resolve().parents[1] / "fixtures/native_invoice.pdf").read_bytes())
        with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as client:
            _, summary = diagnose(client, adapter.key, adapter.model, pages, args.isolate, emit)
        return 0 if summary["all_baselines_passed"] else 1
    except ProviderError as error:
        emit({"type": "configuration", "category": error.code, "requests_sent": 0, "root_cause_verified": False})
        return 2
    except Exception:
        # No tracebacks: unexpected library exceptions can retain request contents.
        emit({"type": "diagnostic_error", "category": "DIAGNOSTIC_INTERNAL_ERROR", "root_cause_verified": False})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
