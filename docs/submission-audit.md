# Submission readiness audit

## Baseline and repository state

Audited main: `9499c8e`, merge of the canonical evidence-path fix. All six prior
application-fix PRs (#1–#6) were merged; no PR was open at the initial audit. Their
working application changes are already on main, so no application-fix merge was
needed. No unrelated PRs were merged and no user branches were deleted.

The over-budget PDF/test commit `df36cbe` was only on its feature branch. It was
cherry-picked into this branch as a fixture-only commit. The existing untracked
`fixtures/duplicate_invoice_variant.pdf` was preserved and committed with a focused
business-duplicate fixture test. Both are required for the documented A/B/C demo.
Native/scanned fixtures and the existing synthetic dataset remain unchanged.

## Findings and corrections

| Finding | Action |
| --- | --- |
| README dominated by implementation chronology and earlier troubleshooting | Rewritten around case-study context, real workflow, setup, tests and limitations |
| No complete architecture/sequence diagrams or dedicated rule reference | Updated architecture and added business-rules reference from code |
| Demo lacked the complete ordered approval/duplicate/over-budget sequence | Added state-aware `demo-walkthrough.md`; old `demo.md` redirects there |
| Owner's verified model differs from backend fallback | Setup explicitly selects `gemini-3.1-flash-lite`; code fallback `gemini-3.5-flash-lite` unchanged |
| Historical "live unverified" notes could be read as current status | Labeled historical diagnostics; current evidence provenance in `validation.md` |
| Old PR body and milestone validation obscured current docs | Preserved under `docs/history/` |
| Playwright backend command assumed Linux venv layout | Test configuration now selects Windows/Linux executable paths; no app change |
| Ignore rules covered only `.env` and one data directory | Added `.env.*` with example exception, SQLite/DB sidecars and diagnostic outputs |

## Focused security/reliability review

- Current tracked text was scanned for recognizable Google/OpenAI/GitHub token and
  private-key patterns. No matches were found; only placeholder/template key names
  are committed. This is not a complete historical secret audit or penetration test.
- No tracked local databases, `.env` secrets, dependency trees, generated caches,
  browser traces or build bundles were found. Built client assets were checked for
  credential patterns/key-variable references. Backend keys are not exposed by the
  frontend configuration API, and no `VITE_*` key is required.
- Documented provider errors/diagnostic output use static messages and safe metadata;
  source citations and model contents are not logged by the app's own diagnostics.
  Source text/PDFs/reviewed submissions are intentionally stored as local application
  data and visible to the local user; storage is not encrypted or access-controlled.
- PDF MIME/extension/size/page checks, source-evidence validation, financial controls
  and retry/atomicity behavior were inspected and tested. No demonstrated blocker
  justified changes to the application logic in this documentation phase.
- React uses text rendering for evidence/errors, not raw HTML injection. Provider
  requests use fixed HTTPS hosts; model-path validation and TLS verification remain.
- The largest tracked artifacts are useful synthetic browser screenshots (each under
  256 KB) and the frontend lockfile. The four PDFs are small synthetic fixtures;
  none was removed. Local data/caches were preserved and ignored, not blindly deleted.
- Python dependency consistency and frozen npm installation passed. No dependency
  versions changed. No comprehensive dependency-vulnerability certification is claimed.

## Verification and boundaries

See [validation](validation.md): 223 backend tests passed/2 skipped, 7 frontend
tests passed, 3 real Chromium scenarios passed, build/dependency/smoke checks passed.
The audited main CI run succeeded separately. Owner-reported Windows live Gemini
A/B/C results are labeled manual evidence, not Codex or CI execution.

The production `app/` files and dependency manifests/lockfiles are unchanged from
the audit baseline. The only executable configuration adjustment is the low-risk
test-harness Windows path selection, validated on Linux and awaiting Windows execution.
The financial engine, AI extraction/evidence logic, matching and human confirmation
were not refactored or changed.

## Submission recommendation and remaining limits

The branch is prepared for a **local case-study submission and demonstration** once
reviewed/merged and the evaluator follows the fresh-state setup. It is not a public
deployment recommendation. No authentication/roles, payment execution, encrypted
storage, tamper-evident audit, distributed queue, schema migrations, release/reversal
or confirmed-invoice correction workflow is implemented.

A new evaluator still needs provider access/quota for live Gemini, or must honestly
label the manual-review alternative. A fresh Windows installation and the updated
Windows browser-test launcher have not been executed in Codex. Recheck the final
Windows environment before presenting. Do not reset valuable DBs or bypass a failed
extraction to reproduce expected screenshots.

At the initial audit there were no unresolved application PRs. The submission PR
itself is the review gate for these docs, preserved fixtures and test-harness cleanup;
the remote over-budget branch may be retained until its included work is merged.
