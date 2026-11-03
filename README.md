# Zamp PS-1 AI Invoice Processing

Reconstructed FastAPI/SQLite backend. No frontend or Phase 4 implementation.
Earlier reported tests were not recovered; this repository has a new test suite.

## Development

Python 3.12 is the validated runtime. Use the existing checkout; a Git worktree is
not necessary. Create a virtual environment and install the frozen dependency set:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.seed
ZAMP_DB_PATH=data/demo.sqlite3 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

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

Each milestone is tested and committed to a dedicated reconstruction branch; `main`
is not directly overwritten. AI extraction must never bypass financial checks.
