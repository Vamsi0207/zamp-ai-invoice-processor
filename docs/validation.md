# Reconstruction validation

Validated with Python 3.12.14 and Tesseract 5.5.0 on Linux.
These are newly implemented tests; none of the earlier reported 84 tests were recovered.

## Milestone 1

`.venv/bin/python -m pytest -q`: **42 passed**, one upstream deprecation warning.
Includes concurrent allocations/retries, transaction rollback, tolerance boundaries,
partial invoices, receipts, vendor/PO checks, duplicates, API schemas, audit history,
multi-line tax/shipping/discount arithmetic, persistence and synthetic dataset replay.

Committed and pushed separately as `e907c79` on `reconstruction/ps1-backend`.
Fetched from GitHub and verified application, lockfile, fixture and test paths.

## Milestone 2

`.venv/bin/python -m pytest -q`: **90 passed, 2 skipped**, six upstream warnings
(Starlette/AnyIO alias and PyMuPDF SWIG types). No failed tests.

Actual local OCR executed against image-only and mixed native/scanned PDFs. Upload
validation, limits, encrypted/corrupt documents, OCR errors/timeouts, persistent
content hashes, evidence validation, provider request contracts/errors, and document
provenance through deterministic financial processing are covered.

Provider tests use explicit HTTP mocks. The two optional live API tests were skipped
because live opt-in and credentials were not available. Gemini/OpenAI key and model
variables were absent; no secret values were printed. Live provider compatibility,
credentials, network access, and extraction quality remain unverified.

Additional commands:

```sh
.venv/bin/python -m scripts.seed    # executed twice, idempotent
.venv/bin/python -m scripts.generate_fixtures
.venv/bin/python -m pip install --no-index -r requirements-lock.txt
.venv/bin/python -m pip check
.venv/bin/python -m scripts.smoke
git diff --check
```

Frozen installation requirements were already satisfied; pip check reported no
broken requirements. The real Uvicorn HTTP smoke passed health, master data, PDF
upload, reviewed invoice, approval, safe retry, PO balance and source provenance,
using a disposable database. The server was stopped after validation.

This environment's command sandbox prevents the sockets used by the FastAPI test
client; tests and the HTTP smoke were run with approved local socket permissions.
GitHub CI configuration is included but its execution is not claimed here.

## Phase 4

Backend orchestration milestone: **108 passed, 2 skipped** before commit `51de587`.
That commit was pushed to `phase4/invoice-automation`, fetched back, and verified.

Final backend suite after UI-support APIs: **110 passed, 2 skipped**, six existing
upstream deprecation warnings. All earlier tests remain in place. New coverage
includes durable stages/history, exact/ambiguous matching, confirmed review,
upload/business duplicates, partial invoicing, excessive amounts, missing POs,
concurrent confirmation, safe recovery after a committed allocation, persisted
provider/PDF failures, manual retry, receipt shortfalls, filters and validation audit.

Frontend: **7 Vitest tests passed**; TypeScript checking and Vite production build
passed. Vitest HTTP-contract tests explicitly mock fetch. They check request paths,
validation messages, multipart uploads, no invented timeline progress and retry keys.

Browser: **3 Playwright tests passed in real system Chromium**, using real HTTP
requests to Vite and FastAPI/SQLite. Covered approval, reload, byte-duplicate replay,
partial invoicing, business duplicate/excessive-value rejection, missing-PO review,
provider-not-configured failure and manual retry, history filtering, upload modal,
drag-and-drop, receipt validation errors, desktop and mobile layout. No financial
decisions are mocked. The isolated test server intentionally has no provider keys.

Actual built-app smoke also passed: FastAPI served the HTML and compiled CSS/JS
assets and responded to same-origin `/api/dashboard`; the prior financial/PDF smoke
passed. Screenshots in `docs/screenshots/` are captures from synthetic browser tests.

Commands executed from the repository root (frontend commands use `frontend/`):

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke
cd frontend
npm run build
npm test
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e
```

Gemini/OpenAI credentials remain absent. The two live provider checks are skipped;
the Gemini adapter contract is exercised with explicit mocked HTTP responses in
backend orchestration tests. No live-provider success or GitHub CI success is claimed.

The environment permits Git pushes but currently denies `api.github.com` requests.
Both `gh pr list` (GraphQL) and REST pull-list operations returned Forbidden. A draft
network addition for `api.github.com` was saved without changing other destinations;
it requires review/save and publication in environment settings before activation.
PR API authentication remains unverified until that network prerequisite is applied.
