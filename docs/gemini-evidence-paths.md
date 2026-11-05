# Canonical Gemini evidence paths

> Historical troubleshooting context: these experiments describe earlier Gemini
> integration work, mostly with `gemini-3.5-flash-lite`. The current submission demo
> explicitly selects the owner-verified `gemini-3.1-flash-lite`. Past statements about
> absent Codex credentials or pending live checks are not current Windows failure
> claims. See [current validation](validation.md) and [setup](windows.md).

The supplied Windows run returned HTTP 200 and passed Pydantic, but evidence failed
with `UNEXPECTED_INVOICE_PREFIX`. This identifies a path-format mismatch: the model
returned response-root paths such as `invoice.total`, while the existing source
validator expects paths relative to the invoice object, such as `total`.

## Instructions and schema

The shared extraction instructions and `Evidence.field` schema description now
explicitly name the relative-path contract. The model should emit canonical paths:

- Scalar fields: `vendor_name`, `vendor_reference`, `invoice_number`, `po_number`,
  `currency`, `total`, `tax`, `shipping`, `discount`.
- Line fields: `lines.<zero-based index>.line_reference`, `.description`, `.quantity`
  or `.unit_price`, for an existing line. For example `lines.0.quantity`.

The instructions explicitly exclude the response's `invoice` wrapper, bracket
notation, slashes, wildcards and repeated prefixes. They still require one or more
source citations for every non-null scalar. The provider schema gains descriptions,
not an unsupported new regex or a change to local validation constraints.

## Narrow compatibility boundary

Gemini responses pass the original Pydantic model first. A separate helper may then
remove **one exact, case-sensitive leading `invoice.`**, only when the remainder
is an exact existing canonical path with a non-null scalar value. This is the only
added spelling alias. It is not a generic JSON-path parser or a recursive repair.

`invoice.vendor_name` can map to `vendor_name`; `invoice.lines.0.quantity` can map
to `lines.0.quantity` if that line/value exists. Unknown targets, repeated prefixes,
case changes, extra components, bracket/pointer syntax, leading-zero/negative/out-of-
range indices, array/object targets and null targets remain invalid. Different raw
aliases collapsing to the same path are rejected with `AMBIGUOUS_FIELD_PATH`, not
silently merged. Repeated citations with the same exact raw path keep their original
semantics: every citation still has to pass verification.

The helper returns copies when paths change. It does not edit the input result,
invoice values, quotes, pages, citation count or order. Canonical paths are unchanged.
The normalized result must immediately pass the **unchanged** `validate_evidence`:
strict actual-page lookup, source-quote matching, numeric/string support and full
non-null-field coverage. The helper never manufactures missing evidence, guesses a
field, fixes a page, drops a bad quote or changes an extracted value. OpenAI retains
its original strict path handling; this compatibility alias is Gemini-only.

The diagnostic's full-schema requests use the same helper and validator as the
adapter so a diagnostic cannot claim success under different source-verification
rules. Successful extracted evidence is returned/stored with canonical paths.
Human confirmation and the deterministic financial checks still follow extraction.

## Windows live check

From the repository root on this fix branch (or main after merge), with the existing
Gemini key securely available to the backend's environment:

```powershell
$env:GEMINI_MODEL='gemini-3.5-flash-lite'; .\.venv\Scripts\python.exe -m scripts.check_gemini
```

This makes one request using only the committed synthetic fixture. No key, headers,
source text or complete model response are printed. A result is successful only
when `status` is `passed`, both `pydantic_validated` and `evidence_validated` are
true, and the synthetic fixture checks passed. If another evidence error appears,
it remains a failure: report only the safe category/reason. Do not weaken source
checks or fabricate citations to turn it green. No automatic retries are added.

## Validation performed

Linux Python 3.12.14: **220 passed, 2 skipped**, with six existing upstream warnings.
The full backend suite, dependency check and built-app/HTTP smoke passed. New
provider tests use explicit HTTP mocks; they verify instructions/schema descriptions,
canonical output, exact prefix mapping without input mutation, invalid/ambiguous
path rejection, unchanged page/quote/numeric/coverage failures, diagnostic parity,
OpenAI's unchanged behavior, and that normalized extraction still stops at human
review with zero invoices/allocations created automatically.

The `validate_evidence` function's AST was compared with main and is unchanged.
Financial engine, matching/service, workflow safeguards and dependency files were
also verified unchanged. Local array and evidence constraints remain intact.

The Windows observation confirms the prior mismatch, not a live success of this
patch. Codex has no Gemini credential. Real Gemini generation of canonical paths,
and successful end-to-end extraction after this change, remain pending Windows
verification. Passing mocked responses are not presented as live model results.
