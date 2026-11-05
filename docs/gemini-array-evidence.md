# Gemini array bounds and safe evidence failures

## What is established

The Windows live results supplied for `gemini-3.5-flash-lite` show full-schema HTTP
400, and HTTP 200 after removing array-bound hints, followed by evidence failure.
Inspection of the exact emitted schema shows **zero `minItems`** and two
`maxItems`: `invoice.lines` at 200 and `evidence` at 1000. Thus the reported
successful request differs by `maxItems` only; `minItems` cannot explain that 400.

The Gemini projection now omits **only `maxItems`** in addition to its prior
compatibility projection. Every other existing hint is retained. This reproduces
the provider-facing change accepted in the supplied Windows experiment. Both
original Pydantic array limits remain unchanged and enforced after generation.
OpenAI continues to receive the original schema with those limits.

It is **not yet established** whether the line bound, evidence bound, or their
combination is responsible. Codex has no Gemini key. Removing both is the narrow
group-level workaround supported by the supplied evidence, not a claim that both
locations have individually been proven incompatible. No prompt or evidence
acceptance rule has been relaxed to obtain success.

## One-command Windows live check

From this branch in the repository root, with `GEMINI_API_KEY` already securely
available to the same PowerShell session:

```powershell
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'; .\.venv\Scripts\python.exe -m scripts.check_gemini
```

This makes one request using only `fixtures/native_invoice.pdf`. It creates no
financial invoice or allocation. A passing result requires the original Pydantic
and source-evidence validation plus the synthetic fixture expectations. A failed
result now distinguishes HTTP acceptance from validation: e.g. `http_status: 200`,
`pydantic_validated: true`, `evidence_validated: false` is **not success**. It includes
only static category/reason codes and validation flags, never model values/quotes,
field paths, complete responses, key values or headers. API error code remains
`INVALID_RESPONSE`, preserving existing callers. No automatic retries.

## Pinpoint the individual bounds

Explicitly run this separate four-request diagnostic (may incur provider charges):

```powershell
.\.venv\Scripts\python.exe -m scripts.diagnose_gemini --array-bounds
```

The same synthetic pages, system instruction, model and schema are used in all
four calls. Only the following historical hints are restored independently from
the **unchanged local Pydantic schema**:

| Variant | Lines max | Evidence max |
| --- | --- | --- |
| `no_array_bounds` | absent | absent |
| `lines_max_only` | 200 | absent |
| `evidence_max_only` | absent | 1000 |
| `both_max_bounds` | 200 | 1000 |

There is no artificial `minItems` experiment because it was absent in the failing
request. Each variant is sent once. The summary separately reports
`http_accepted_variants`, `http_400_variants` and `fully_validated_variants`.
Evidence failure does **not** erase the fact that a request returned HTTP 200.
The matrix exits nonzero if any deliberately restored-bound variant fails; use the
separate one-call check to assess the current application request's success.

If no-bounds succeeds, compare statuses: only evidence-max failing implicates the
evidence bound; only lines-max failing implicates the line bound; both single bounds
accepted but the combination rejected implicates the combination; both single bounds
rejected suggests each or a common `maxItems` restriction. A 429/503/transport failure
is not compatibility proof. A single controlled run should be assessed with those
confounders in mind; the tool never auto-declares a verified root cause.

The original four-stage diagnostic also now separates
`http_accepted_controlled_differences` from `successful_controlled_differences`.
After this fix its full baseline is the current unbounded provider projection;
`--array-bounds` is the way to restore the historical failing hints. A no-op removal
is skipped rather than becoming a repeated request.

## Evidence classification and interpretation

The first evidence failure is classified without exposing the offending data:

| `evidence_category` | Meaning / selected `evidence_reason` |
| --- | --- |
| `UNSUPPORTED_SOURCE_QUOTE` | Quote not found in supplied text: `QUOTE_NOT_IN_SOURCE` |
| `MISSING_FIELD_EVIDENCE` | A non-null field has no citation: `NON_NULL_FIELD_WITHOUT_EVIDENCE` |
| `INCORRECT_NUMERIC_EVIDENCE` | Quoted numeric tokens do not support the value: `NUMERIC_VALUE_NOT_SUPPORTED` |
| `INVALID_FIELD_OR_PAGE_REFERENCE` | Invalid path, `UNEXPECTED_INVOICE_PREFIX`, invalid page, or `QUOTE_ON_DIFFERENT_PAGE` |
| `OTHER_SCHEMA_EVIDENCE_MISMATCH` | Structural schema failure, evidence for a null field, or unsupported string value |

`validation_stage` distinguishes `response`, `pydantic`, `evidence` and synthetic
`fixture_expectation` checks. Pydantic failures have not yet reached evidence checks.
Field paths are still canonical (`total`, `lines.0.unit_price`), not prefixed with
`invoice.`. Pages remain 1-based. Existing case/whitespace normalization, numeric
token matching and complete non-null-field coverage are unchanged. Invalid paths,
missing citations and invented quotes are not silently repaired or fabricated.

The supplied live summary does not contain the offending citation, so it cannot
establish whether model output, prompt design or a genuine validator defect caused
the failure. Canonical synthetic citations still pass locally; each specified bad
case remains rejected. That demonstrates those controlled cases, not that every
possible validator edge case is correct. The next live category/reason narrows the
investigation without blaming the model or changing the validator speculatively.

## Validation actually performed

Linux Python 3.12.14: **191 passed, 2 skipped**, six existing upstream deprecation
warnings. The full backend suite ran. New mocked tests cover the provider omission,
exact local limits and oversized-response rejection, all evidence categories,
four-way request isolation, HTTP/evidence reporting separation and CLI redaction.
The dependency check and built-app/HTTP smoke passed.

Both live commands were invoked without a key in Codex and failed safely without
making authenticated calls. Windows/live validation of this change remains pending.
No real extraction success is claimed. Financial engine, master-data matching,
duplicate prevention, human confirmation and dependency versions are unchanged.
