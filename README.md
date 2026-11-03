# Zamp PS-1 AI Invoice Processing

React/TypeScript invoice operations application with a FastAPI/SQLite backend.
Phase 4 connects intake, extraction, matching, human review and financial decisions.
Earlier reported tests were not recovered; this repository has a new test suite.

## Development

Python 3.12 and Tesseract 5 with English language data are the validated runtimes.
For Debian/Ubuntu, install OCR with `sudo apt-get install tesseract-ocr tesseract-ocr-eng`.
For Windows installation, executable discovery and PowerShell commands, see
[Windows Python and Tesseract setup](docs/windows.md). Set `TESSERACT_CMD` to a full
executable path when Tesseract is not on PATH. Installing `pytesseract` alone does
not install the Tesseract executable or its English language data.
Use the existing checkout; a Git worktree is
not necessary. Create a virtual environment and install the frozen dependency set:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.smoke
.venv/bin/python -m scripts.seed
cd frontend && npm ci && npm run build && cd ..
ZAMP_DB_PATH=data/demo.sqlite3 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your own browser after starting the server. FastAPI
serves the compiled frontend and same-origin `/api` endpoints. To develop with Vite,
start the backend as above, then run `cd frontend && npm run dev` in another shell
and open the Vite address it prints. Its `/api` proxy targets port 8000; override
`ZAMP_API_TARGET` in the Vite server shell if needed (not a browser credential).

The database defaults to `data/zamp.sqlite3`. Set `ZAMP_DB_PATH` before startup.
`.env.example` documents configuration; export variables yourself (no automatic
dotenv loading). The seed command targets a separate synthetic demo database and
does not alter the application database. Never commit real invoices, databases, or keys.

## API workflow

Create a vendor (`POST /vendors`), PO (`POST /purchase-orders`), receipt
(`POST /receipts`), then invoice (`POST /invoices`). Call
`POST /invoices/{id}/process` with `{"idempotency_key":"unique-attempt"}`.
Read cumulative balances at `GET /purchase-orders/{id}/balance` and database
readiness at `GET /health`. Interactive schema documentation is served at `/docs`.
Identifiers and invoice data are immutable. Decimal money is accepted as strings.
See [architecture and decision policy](docs/architecture.md) before interpreting
Approved, Review, or Rejected results. Run on loopback: this prototype has no auth.

## Milestones

1. Deterministic financial engine, transactional allocations, persistence, API and tests.
2. PDF validation, native extraction/OCR, real structured AI adapters and evidence.
3. Phase 4: persistent workflows, React dashboard/history/review, actual stage polling,
   source evidence and master-data receipt entry. See the [five-minute demo guide](docs/demo.md)
   and [orchestration contracts / Gemini setup](docs/phase4.md).

Each milestone is tested and committed to a dedicated reconstruction branch; `main`
is not directly overwritten. AI extraction must never bypass financial checks.

## PDF and AI workflow

1. `POST /documents` with multipart field `file` (PDF MIME type and `.pdf` suffix,
   maximum 10 MiB, 20 pages). Encrypted, corrupt, empty, and unreadable documents
   are rejected. Storage uses SHA-256 names; repeat uploads reuse the stored result.
2. `GET /documents/{sha256}` shows per-page native/OCR text and extraction attempts.
3. Optionally `POST /documents/{sha256}/extract` with `{"provider":"gemini"}` or
   `{"provider":"openai"}`. Set the corresponding API key and optional model from
   `.env.example`. These are real HTTPS adapters using schema-constrained JSON.
   Missing configuration returns 503; upstream failures or invalid evidence return
   502, never invented extraction results. Provider requests send extracted text;
   they do not send the PDF binary. Calls may incur provider charges.
4. Review the facts, quotes, and original PDF yourself. Resolve vendor, PO, and
   PO-line references against master data; missing fields remain null, not guessed.
   Submit a complete canonical `Invoice` body to `POST /documents/{sha256}/invoices`.
   This records its document source; it does not approve or allocate anything.
5. Process that invoice through `/invoices/{id}/process`. The same deterministic
   financial checks apply to manually entered and document-derived invoices.

Quotes must exist on the cited page and support the extracted scalar value. This
checks textual grounding, not document authenticity or semantic correctness; human
review remains required. No automatically mapped IDs or AI payment decisions.

Real native and image-only PDF fixtures are committed under `fixtures/` and can be
regenerated with `.venv/bin/python -m scripts.generate_fixtures`. All are visibly
synthetic. Tests run real local OCR. Provider contract/error tests use HTTP mocks;
live provider checks are **skipped by default**. To opt in, export the appropriate
key and run `ZAMP_RUN_LIVE_AI=1 .venv/bin/python -m pytest -q -k live_provider`.
Do not print keys or commit `.env`. Network access to `generativelanguage.googleapis.com`
and/or `api.openai.com` is also required. Deprecation warnings from upstream
Starlette/AnyIO and PyMuPDF are currently non-fatal.

For Gemini request compatibility, safe error categories and Windows live verification,
see [Gemini integration diagnostics](docs/gemini-integration.md). The default Gemini
model is `gemini-3.5-flash-lite`; override `GEMINI_MODEL` with a model your account
can use. No automatic model fallback or paid-call retries are performed.

For a remaining HTTP 400, run `python -m scripts.diagnose_gemini` to compare four
synthetic requests without changing the adapter. See the
[PowerShell commands and interpretation guide](docs/gemini-http400-diagnostics.md)
before optionally enabling the bounded `--isolate` probes.
