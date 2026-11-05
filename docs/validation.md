# Submission validation and evidence provenance

Submission pass: 2026-11-05. Audit baseline: main `9499c8e` (PR #6 merged).
Verification ran on `docs/submission-readiness`, including the preserved over-budget
and duplicate-fixture tests and the platform-aware Playwright launcher. Older counts
and diagnostic history are [archived separately](history/validation-history.md).

## Automated checks actually executed in Codex

Environment: **Linux, Python 3.12.14, Node.js 24.22.1, Tesseract 5.5.0**, system
Chromium. These results are not a new Windows installation test or live-provider test.

| Command | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **223 passed, 2 skipped**, 6 upstream deprecation warnings |
| `.venv/bin/python -m pip check` | No broken requirements |
| `npm ci` in `frontend/` | Frozen frontend installation succeeded |
| `npm test` in `frontend/` | **7 passed**, one Vitest test file |
| `npm run build` in `frontend/` | TypeScript check and Vite production build passed |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e` | **3 passed**, real browser/HTTP with isolated SQLite |
| `.venv/bin/python -m scripts.smoke` | Built HTML/assets, same-origin API and financial/PDF HTTP smoke passed |
| `git diff --check` | Passed |
| Ignore-rule checks | Secret variants, DB/WAL files and browser output ignored; `.env.example` trackable |

The backend warnings are the Starlette/AnyIO deprecated BlockingPortal alias and
PyMuPDF SWIG type metadata warnings. Browser startup also emits a non-failing
NO_COLOR/FORCE_COLOR warning. No tests were disabled or assertions removed to obtain
these results. Existing test coverage was retained.

The two skips are the optional live Gemini/OpenAI tests: they require a key and
`ZAMP_RUN_LIVE_AI=1`. Codex has no Gemini key and did **not** execute authenticated
model extraction in this pass. Provider contract/error tests use explicit HTTP
mocks. Real local Tesseract OCR ran for scanned and mixed-page fixtures.

Playwright exercised real frontend/FastAPI requests for manual review/approval,
identical-file reuse, partial invoices, business duplicates, excessive values,
missing PO, configured-key absence/manual retry, filtering, drag/drop, modal upload,
receipt validation, and desktop/mobile layout. Its server deliberately clears keys;
its financial decisions are real engine results, not AI mocks.

The new fixture checks parse real PDF bytes and supply verified synthetic facts
locally. They do not claim to execute Gemini. The over-budget test starts after a
real engine-approved $400 SYN-001 and asserts all three actual violations and the
unchanged $400 allocation/$600 balance. The duplicate test asserts distinct hashes
and `DUPLICATE_INVOICE` as its sole rejection reason.

## Separately observed GitHub CI

The latest audited main run, on `9499c8e`, completed successfully:
[Backend tests workflow](https://github.com/Vamsi0207/zamp-ai-invoice-processor/actions/runs/42069047449).
The workflow includes backend checks, frontend tests/build and browser checks on
Ubuntu. This is an API-observed CI outcome for that commit, not the local counts
above or a claim about an uncompleted submission PR run.

## Owner-reported Windows live demonstration

The owner reports real Gemini extraction with **`gemini-3.1-flash-lite`** and the
following manually observed React flows. These are **not automated CI results**:

| Scenario | Reported result | Reported remaining PO balance |
| --- | --- | --- |
| SYN-001, 4 chairs/$400 | Approved | $600 |
| Identical PDF again | Existing run reused, no second allocation | $600 |
| Distinct PDF, same SYN-001/vendor | Rejected as business duplicate | $600 |
| Unique SYN-002, 7 chairs/$700 | Rejected for amount, ordered quantity and receipts | $600 |

These reports supersede a blanket statement that live Gemini has never worked.
They do not establish availability for a new evaluator's account, repeatability on
every model, or live OpenAI success. Earlier diagnostic notes mostly used
`gemini-3.5-flash-lite`; those historical failures must not be attributed to the
verified demo model without evidence.

## Windows verification scope

PowerShell setup commands were checked against actual variable names, entrypoints,
seeding behavior and native executable discovery. The owner has a working Windows
application, but this pass could not execute a fresh Windows setup. The Playwright
launcher now selects the Windows virtual-environment executable; its Windows branch
needs an actual Windows run. Linux e2e success does not substitute for that run.

Before the final presentation, follow [Windows setup](windows.md), use a fresh seeded
state and execute [A/B/C in order](demo-walkthrough.md). If provider access is absent,
label the supported manual mode accurately instead of presenting it as live AI.
