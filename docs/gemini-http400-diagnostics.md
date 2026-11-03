# Remaining Gemini HTTP 400: evidence before production changes

**Update:** Windows results isolate the emitted `maxItems` group (no `minItems`
was present). The production projection now omits that group while local limits
remain. Use [the focused array/evidence guide](gemini-array-evidence.md) and
`python -m scripts.diagnose_gemini --array-bounds` to test each historical bound
individually. The following describes the original broader diagnostic; its full
baseline always follows the current production projection.

The live 400 persists after PR #3. It is **not a verified schema-keyword root cause**.
This change adds a standalone experiment, not another production schema rewrite.
The adapter, Pydantic models, evidence validator, human review and financial engine
are unchanged. No backend server or database is needed to run the diagnostic.

## Exact Windows command

From the repository root in PowerShell, with your existing `GEMINI_API_KEY` securely
available in that same session:

```powershell
git fetch origin
git switch fix/gemini-request-diagnostics
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
.\.venv\Scripts\python.exe -m scripts.diagnose_gemini | Tee-Object -FilePath .\gemini-diagnostic.jsonl
```

If already merged, use latest main instead. Dependencies are unchanged. Do not
print the key, add it as a command-line argument, or put it in a `VITE_*` variable.
The script does not load `.env` automatically. Retain normal TLS/proxy settings and
allow HTTPS to `generativelanguage.googleapis.com`.

## Four baseline requests

Requests run sequentially, **once each**, to the same selected model/endpoint:

| Step | Request | Response check |
| --- | --- | --- |
| `01_plain_text` | Only `contents`, no generation config or structured output | Completed text with the expected marker; no JSON schema applies |
| `02_two_fields` | JSON MIME and a two-string-field `responseJsonSchema` | Strict two-field Pydantic model and expected synthetic values |
| `03_nested_invoice` | Small invoice object with a nested line array | Strict nested Pydantic model and expected synthetic values |
| `04_full_invoice_evidence` | Exactly the adapter's system instruction, fixture pages and complete projected schema | Original `ExtractionResult`, original evidence validator and expected synthetic invoice number/total |

Only hardcoded synthetic prompts and the committed `fixtures/native_invoice.pdf`
are used. There is no user-supplied file argument, financial invoice creation or
allocation. A regression test asserts that step 04's JSON payload matches the
unchanged production adapter's payload.

Each output line is a JSON report, not a provider response. It contains the step,
HTTP status, safe category, schema conformance, evidence validation and expected-data
check. `null` means not applicable or not checked, not a pass. The first text-only
request has `schema_conforms: null` because it requests no JSON. For example, HTTP
400 has no validated model response, so conformance is null. A full response can
pass Pydantic (`schema_conforms: true`) and fail evidence (`evidence_validated: false`);
that remains `INVALID_RESPONSE`, never a successful extraction.

No key, request/authorization headers, response text, invoice contents or arbitrary
upstream messages are printed. `provider_status` is an allowlisted Google status
enum only. `provider_field_hints` contains only known request-field roots extracted
from structured `google.rpc.BadRequest` metadata, never descriptions or arbitrary
path suffixes. If Google only returns a generic message, these hints remain empty.

## Interpret the final summary

`first_failed_level` includes both HTTP and response-validation failures.
`first_http_failure` identifies a non-200 HTTP boundary. `requests_sent` counts
actual diagnostic calls. `root_cause_verified` remains false: a boundary or one
successful variation is evidence, not automatically a conclusive causal finding.

- **Plain text fails with 400:** the structured schema is absent. Investigate model/
  endpoint/request/account prerequisites first; do not blame the full invoice schema.
- **Text succeeds; two fields return 400:** investigate structured-output wire fields
  and that model's support, before invoice complexity or evidence constraints.
- **Two fields succeed; nested schema returns 400:** the first observed boundary is
  nesting/array/schema shape or its request context. This alone does not identify
  a particular nested keyword.
- **Small schemas succeed; full schema returns 400:** narrow the full schema or its
  system instruction using the optional controlled probes below.
- **HTTP 200 but validation fails:** the server accepted the request. Investigate
  response quality/structure/evidence rather than treating this as HTTP 400.
- **429/503/timeouts:** quota, capacity or transport failures are confounders, not
  evidence of an incompatible schema construct. There are no automatic retries.
- **All four pass but the backend still fails:** compare the local checkout, selected
  model, inherited environment, proxy/client versions and actual request-building
  path. The diagnostic does not prove a historical request was identical.

Exit codes: **0** all four baselines validate; **1** at least one baseline failed;
**2** missing/invalid configuration or a local diagnostic error. No key produces
`PROVIDER_NOT_CONFIGURED`, `requests_sent: 0`, and no model calls.

## Optional controlled isolation (up to eight extra calls)

When needed, explicitly opt in:

```powershell
.\.venv\Scripts\python.exe -m scripts.diagnose_gemini --isolate | Tee-Object -FilePath .\gemini-diagnostic-isolation.jsonl
```

This is a new deliberate diagnostic run: four baseline calls plus **at most eight
distinct probes**, and may incur API charges. Extra probes run only when plain text
returned HTTP 200 and a structured baseline returned HTTP 400. There is no automatic
retry, no sleeping loop, no model cycling, and byte-equivalent JSON requests are
never resent within a run.

The extra probes compare the minimal request's documented `responseSchema` wire
contract and newer `responseFormat` contract, then vary the full-schema request by
one group at a time: titles, `additionalProperties`, numeric bounds, array bounds,
nullable `anyOf` versus a type array, and system instruction. Original prompts/data
remain constant within each comparison. These are diagnostic-only provider hints;
every full-schema variation still runs the **original** Pydantic/evidence validation.
There is no relaxed application validator or production fallback.

`successful_controlled_differences` lists groups where the corresponding baseline
was HTTP 400 but a controlled variation returned HTTP 200 **and** passed validation.
Multiple successful changes do not establish that each removed field is invalid.
Single-run results can be affected by provider behavior. If only step 03 fails, the
current extra probes do not isolate individual nested fields; retain that boundary
for the next targeted experiment rather than claiming a root cause.

Share the generated JSON report for investigation, not raw provider responses or
keys. The smallest production fix should follow reproducible request-pair evidence
or an authoritative provider field diagnostic, with a regression test for that
specific incompatibility. This PR intentionally makes no such unverified fix.

## Current official API contracts reviewed

- [Official REST discovery](https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta)
  describes `generateContent`, `generationConfig.responseJsonSchema` with JSON MIME,
  the alternative OpenAPI `responseSchema`, and newer
  `responseFormat.text.{mimeType,schema}` (`mimeType: APPLICATION_JSON`). The latter
  is probed only as an opt-in alternative, never enabled in the application here.
- [Official SDK models serializer](https://github.com/googleapis/python-genai/blob/main/google/genai/models.py)
  still maps `response_json_schema` to wire key `responseJsonSchema`; its
  [README](https://github.com/googleapis/python-genai/blob/main/README.md) uses that
  structured-output path. The legacy contract's mere presence is not proof it works
  for this account/model, but there is also no evidence requiring a migration.
- [Official Interactions client](https://github.com/googleapis/python-genai/blob/main/google/genai/_gaos/interactions.py)
  and [cookbook](https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_interactions_api.ipynb)
  describe `/{api_version}/interactions` with model/input at the request level,
  `system_instruction`, `response_format` plus the required `response_mime_type`,
  and interaction/state handling including `store`. Its interaction/output interface
  is different from `candidates[].content.parts`; it is not a drop-in request change.
  No Interactions calls or retention/state changes are made by this diagnostic.

The official website pages at `ai.google.dev` are not accessible through this
environment's current network policy; accessible Google REST discovery and official
SDK/cookbook sources were inspected directly. API documentation alone does not
verify account-specific model support or explain a generic live INVALID_ARGUMENT.

## Actual validation

Linux Python 3.12.14: **173 passed, 2 skipped**, with the existing six upstream
deprecation warnings. The entire backend suite ran; new diagnostic tests use explicit
HTTP mocks, not live Gemini. The script was also run locally without a key and
correctly reported zero requests sent. Codex has no Gemini key, so no authenticated
diagnostic calls were made and no live root cause is claimed. Windows/live execution
of these new diagnostics remains pending. Production application files, dependencies,
validators and financial rules are unchanged from main.
