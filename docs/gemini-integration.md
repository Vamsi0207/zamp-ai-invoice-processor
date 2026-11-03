# Gemini integration: request contract and verification

**Follow-up:** live HTTP 400 persists after this compatibility change. The responsible
field is still unverified. Use [sequential HTTP 400 diagnostics](gemini-http400-diagnostics.md)
to collect controlled request evidence; do not assume another schema rewrite or
switching to Interactions will resolve it.

## Investigation and scope

The adapter previously sent raw `ExtractionResult.model_json_schema()` plus
`temperature: 0`. The generated schema includes string `minLength`, `maxLength`
and `pattern` constraints outside the documented `responseJsonSchema` subset.
Sending that unprojected schema assumed portability that Gemini does not promise.
This is a confirmed request-compatibility defect; without a live key in this task,
it is not proof of which individual keyword caused the observed HTTP 400.

Authoritative sources inspected for this fix:

- [Official Gemini REST discovery document](https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta):
  `GenerationConfig` describes the JSON Schema subset and MIME requirements. Its
  temperature description says 0–2 is a valid range and the parameter is silently
  ignored for Gemini 3.6 Flash and newer. Thus temperature 0 alone is not established
  as the cause of this 400. The adapter now omits sampling overrides for all Gemini
  models rather than imposing an unnecessary legacy setting.
- [Official Python SDK structured-output examples](https://github.com/googleapis/python-genai/blob/main/README.md):
  use `response_mime_type` and `response_json_schema`, including nullable `anyOf`.
  The REST request retains the equivalent `responseMimeType: application/json`
  and `responseJsonSchema`. It does not mix `responseSchema` and JSON Schema modes.
- [Official invoice cookbook](https://github.com/google-gemini/cookbook/blob/main/examples/Pdf_structured_outputs_on_invoices_and_forms.ipynb):
  demonstrates structured invoice extraction and lists current Gemini 3.x models,
  including `gemini-3.5-flash-lite` and `gemini-3.8-flash`.

The human documentation pages at `ai.google.dev` were blocked by this environment's
network policy; the official REST discovery and GitHub sources above were accessible.
The public [structured output guide](https://ai.google.dev/gemini-api/docs/structured-output)
is also useful when verifying from Windows.

## Exact behavior changes

- Only Gemini gets a projected schema: local `$ref` definitions are inlined and
  unsupported string constraints omitted from provider hints. All invoice/line/
  evidence fields, required lists, nullability, additional-properties restrictions,
  numeric bounds and array limits remain. The original Pydantic model is not mutated.
- After generation, the **same full Pydantic model and page/quote/value evidence
  validator** still run. Empty/oversized quotes, invalid currencies or money,
  unknown fields, missing facts and unsupported citations are rejected, never relaxed
  or silently repaired. Thoughts are not concatenated into the final JSON response.
- Gemini temperature is omitted; OpenAI's existing request schema/temperature remain.
- The default model is `gemini-3.5-flash-lite`, with the same default shown by the
  configuration API and `.env.example`. This avoids the reported new-user restriction
  on `gemini-2.5-flash`, but does not guarantee access or capacity for every account.
  Explicit `GEMINI_MODEL` overrides are still supported; surrounding whitespace is
  stripped and unsafe model paths remain invalid. Supply the ID without `models/`.
- Failures use safe static messages and classification metadata, never upstream error
  text, headers, key values or invoice contents. Validation exception chaining is
  suppressed so Pydantic input values do not appear in public tracebacks.

No financial policy, invoice validation rule, allocation logic, dependencies,
automatic retries or model fallback have been added or changed.

## Safe error categories

| Upstream condition | Code | Retry advisory |
| --- | --- | --- |
| HTTP 400 | `INVALID_REQUEST` | Fix request/configuration; do not loop unchanged calls |
| HTTP 404 | `MODEL_UNAVAILABLE` | Choose a model available to this account/endpoint |
| HTTP 429 | `RATE_LIMITED` | Check quota and wait before retrying |
| HTTP 503 | `SERVICE_UNAVAILABLE` | Temporary failure; retry later |
| HTTP 401 / 403 | `AUTHENTICATION_FAILED` / `ACCESS_DENIED` | Fix credentials or access |
| Other HTTP failure | `UPSTREAM_ERROR` | 5xx may be retried after diagnosis |
| Timeout / transport error | `TIMEOUT` / `CONNECTION_ERROR` | Check connectivity before retrying |
| Invalid JSON/schema/evidence, blocked or truncated output | `INVALID_RESPONSE` | Investigate response quality; never accept partial results |

`ProviderError` exposes `code`, `http_status`, `retryable` and a safe message.
Workflow failures persist these metadata. The document extraction HTTP endpoint
keeps its existing 502 (provider) / 503 (missing configuration) contract and safe
string detail, adding `X-Provider-Error-Code` for classification. Upstream HTTP status
does not become the status of a successful application extraction. Retry advisories
do not trigger automatic requests; 429 can mean exhausted quota rather than a
short-lived limit. HTTP 503 capacity and HTTP 404 model access are separate from
schema compatibility and cannot be corrected by pretending extraction succeeded.

## Windows verification

From the latest fix branch in PowerShell, with your existing key securely available
as **`GEMINI_API_KEY`** in the backend process:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_gemini
```

The full suite skips optional live checks unless `ZAMP_RUN_LIVE_AI` is explicitly
enabled. `scripts.check_gemini` makes one genuine extraction request using only the
committed `fixtures/native_invoice.pdf`. It does not create a financial invoice or
allocation. Success requires full Pydantic/evidence validation plus the expected
synthetic fixture's invoice number and total. It prints only validation flags and
evidence count, not extracted contents. Failure prints the safe category, upstream
status if available, retry advisory and static message, and exits with code 1.

The key is never printed. Do not put it into source code, chat, a `VITE_*` variable,
or diagnostic screenshots. `.env` is not loaded automatically; configure the key
in the backend's inherited environment and restart the server after changing it.
Allow HTTPS to `generativelanguage.googleapis.com`; retain TLS/proxy verification.
If a different model is available to your account, change `GEMINI_MODEL` explicitly.

## Actual validation in this task

Linux / Python 3.12.14: **154 passed, 2 skipped**, six existing upstream deprecation
warnings. The two optional live provider checks were skipped. Contract tests use
explicit HTTP mocks, including 400/404/429/503 classification and fail-closed
schema/evidence failures; they do not establish live-provider success. `pip check`
and the existing built-app/HTTP smoke also passed. The financial engine, financial
schemas and dependency files were verified unchanged from main.

No `GEMINI_API_KEY` is available here, so no authenticated extraction request was
made. Live confirmation of the corrected request, including the reported 400, and
Windows execution of this change remain pending. No model availability or capacity
success is claimed based only on mocked tests or public documentation.
