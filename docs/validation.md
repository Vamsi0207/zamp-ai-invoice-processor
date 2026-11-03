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
