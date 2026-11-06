# Zamp PS-1 · AI Invoice Processing

A local, auditable invoice-processing application built with React, FastAPI and
SQLite. PDF invoices become evidence-backed drafts matched to existing vendor and
purchase-order data. Human confirmation precedes deterministic financial checks
and any approved allocation. The application does **not** initiate payments.

## Problem and approach

Accounts payable must prevent duplicate invoices and spending beyond received
quantities or authorized PO balances. Invoice layouts vary, so AI helps extract
unstructured information. Financial authorization must remain reproducible: the
backend applies explicit rules instead of accepting an AI approval recommendation.

## Key capabilities

- Drag-and-drop PDF intake, SHA-256 upload deduplication and persisted stage status.
- Native PyMuPDF extraction and per-page English Tesseract OCR fallback.
- Gemini/OpenAI structured extraction, Pydantic validation and source citations.
- Exact master-data matching, PO suggestions and unresolved-field review.
- Business duplicates, partial invoicing, cumulative amounts, quantities, receipts
  and an explicitly authorized conditional 2% amount-tolerance policy.
- Human confirmation, Approved/Review/Rejected decisions, atomic allocations,
  safe retries, dashboard, history, evidence and audit views.
- Credential-free **Manual review** using real PDF text and financial checks;
  it does not generate AI fields or citations.

The owner reports successful Windows/React scenarios using **`gemini-3.1-flash-lite`**:
a $400 approval, business-duplicate rejection and $700 over-budget rejection.
These are manually observed local results, not CI results. Current automated
verification is recorded separately in [validation](docs/validation.md). No live
Gemini call was made in Codex during this submission pass.

## Technology and architecture

| Layer | Implementation |
| --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind CSS; real `/api` HTTP requests |
| Backend | Python 3.12, FastAPI, Pydantic; standard-library SQLite access |
| Documents | PyMuPDF, Pillow, pytesseract + separately installed Tesseract 5/English |
| Providers | Backend-only Gemini `generateContent` and OpenAI chat/completions adapters |
| Persistence | SQLite plus local content-addressed PDF storage |
| Tests | pytest, Vitest/Testing Library, Playwright/Chromium |

```mermaid
flowchart LR
    UI[React dashboard] --> API[FastAPI workflows]
    API --> PDF[PDF text / OCR]
    PDF --> AI[Structured AI extraction]
    AI --> EV[Pydantic + source evidence]
    EV --> HR[Master matching + human review]
    HR --> FE[Deterministic financial engine]
    API <--> DB[(SQLite + local PDFs)]
    FE --> DB
```

The UI polls recorded stages. AI cannot allocate money: after review, the engine
checks current balances and commits the financial run/allocation atomically. See
[architecture](docs/architecture.md) for the sequence and transaction boundaries,
and [business rules](docs/business-rules.md) for the exact policy.

## Installation and startup

Use **Python 3.12**, **Node.js 24**, Git and Tesseract 5 with English data. Python
and frontend dependencies are pinned in `requirements-lock.txt` and
`frontend/package-lock.json`.

The [Windows PowerShell setup](docs/windows.md) is the evaluator quickstart: clone,
virtual environment, OCR, secure key entry, fresh database, frontend build and startup.
`.env.example` documents variables; the application does **not** load `.env` files
automatically. Keys belong only in the backend environment, never `VITE_*` variables.

Linux equivalent, from the repository root after installing English Tesseract:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
npm --prefix frontend ci
npm --prefix frontend run build
export ZAMP_DB_PATH=data/submission-demo.sqlite3
export ZAMP_DOCUMENT_DIR=data/submission-documents
export GEMINI_MODEL=gemini-3.1-flash-lite
# Supply GEMINI_API_KEY through your secure backend environment when using Gemini.
# Seed only a fresh demo path:
.venv/bin/python -c "import os; from scripts.seed import seed; seed(os.environ['ZAMP_DB_PATH'])"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your browser. Build before starting FastAPI; it mounts
`frontend/dist` only when that directory exists at startup. `/docs` exposes the API
schema and `/health` checks database access. Use **one Uvicorn worker** and keep this
unauthenticated prototype on loopback.

For Vite development, keep FastAPI running and execute `npm --prefix frontend run dev`
in a second terminal. Vite proxies `/api` to port 8000; optional `ZAMP_API_TARGET`
changes that target. The built app needs no separate Vite server.

### Configuration and seeding

| Variable | Purpose |
| --- | --- |
| `ZAMP_DB_PATH` | Database; default `data/zamp.sqlite3` |
| `ZAMP_DOCUMENT_DIR` | PDF directory; defaults beside the selected database |
| `TESSERACT_CMD` | Optional full executable path; otherwise PATH discovery |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Backend Gemini credential and model selection |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Optional OpenAI alternative; model fallback `gpt-4.1-mini` |

Explicitly select **`GEMINI_MODEL=gemini-3.1-flash-lite`** for the owner-verified demo.
The unchanged application's fallback, used only if unset, is `gemini-3.5-flash-lite`.
Access, quota and model availability are account-specific. No automatic provider/
model fallback or retries of paid calls are performed.

`seed(path)` creates DEMO-VENDOR, DEMO-PO ($1,000, 10 chairs at $100) and a receipt
for 10 chairs. It inserts **no invoices**. `python -m scripts.seed` specifically
targets `data/demo.sqlite3`, ignoring `ZAMP_DB_PATH`; use the explicit command above
for another path. Seeding is not a reset: existing allocations remain.

## Reproducible demo

Follow [the ordered A/B/C walkthrough](docs/demo-walkthrough.md) on one fresh seeded
database. It covers React actions, expected evidence, evaluator checkpoints and state.

| Fixture | Business identity | Role |
| --- | --- | --- |
| `fixtures/native_invoice.pdf` | SYN-001, 4 chairs, $400 | Approval; leaves $600 |
| `fixtures/duplicate_invoice_variant.pdf` | Same SYN-001/vendor, different bytes | Business duplicate; balance stays $600 |
| `fixtures/over_budget_invoice.pdf` | Unique SYN-002, 7 chairs, $700 | Amount, quantity and receipt violations; balance stays $600 |
| `fixtures/scanned_invoice.pdf` | Image-only SYN-001 | Optional separate OCR check |

All are synthetic and not payable. The generator recreates only native/scanned
fixtures; do not regenerate PDFs mid-demo because byte identities can change.

## Automated tests

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke
npm --prefix frontend test
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npm run test:e2e
```

On Windows use `.\.venv\Scripts\python.exe`; complete PowerShell commands are in
[Windows setup](docs/windows.md). Provider contract tests use explicit HTTP mocks.
Optional live tests need credentials **and** `ZAMP_RUN_LIVE_AI=1`. Separately,
`python -m scripts.check_gemini` makes one live synthetic request and reports safe
validation flags without invoice contents. Manual-mode browser tests do not test
live AI. See [results and evidence provenance](docs/validation.md).

## Known limitations and future improvements

Single-host prototype: no authentication/roles, tamper-evident audit, encrypted
storage, distributed queue, migration system or payment execution. Reviewer identity
is self-reported. Money uses two decimal places, one PO/currency per invoice and
whole units; credit notes and fractional units are unsupported. Confirmed invoices
are immutable; there is no correction/release workflow. Source evidence establishes
textual grounding, not authenticity or complete business-semantic correctness.

Future work includes authenticated roles, audited corrections/reversals, migrations,
isolated document workers, production backup/monitoring and broader invoice/currency
coverage. These are proposals, not implemented features. Real data requires suitable
access control and retention policies before use.

## Documentation

- [Windows setup](docs/windows.md) · [Demo walkthrough](docs/demo-walkthrough.md)
- [Architecture](docs/architecture.md) · [Financial rules](docs/business-rules.md)
- [Validation](docs/validation.md) · [Submission audit](docs/submission-audit.md)
- [API/workflow reference](docs/phase4.md) · [Gemini troubleshooting](docs/gemini-integration.md)
- [Synthetic browser screenshot](docs/screenshots/dashboard.png): automated local
  browser activity, not the owner's live Gemini session.
