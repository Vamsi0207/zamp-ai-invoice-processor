# Phase 4: invoice operations

API/implementation reference. For current evaluator setup use [Windows setup](windows.md),
the [submission walkthrough](demo-walkthrough.md) and [validation](validation.md).

## Persistent workflow API

New endpoints exist directly and under `/api` for same-origin frontend requests.

- `POST /api/workflows`: multipart PDF, `provider` (`gemini`, `openai`, or `manual`),
  and required `idempotency_key`. Returns HTTP 202 and the canonical persisted run.
- `GET /api/workflows?limit=50&offset=0`: paginated history.
- Optional `status` and `search` query parameters filter history across the database,
  not just the current page. Search matches filenames or confirmed/draft invoice numbers.
- `GET /api/workflows/{id}`: stages, timestamps, audit events, document pages,
  evidence, matching issues, review draft, invoice link, final engine result/errors.
- `GET /api/workflows/{id}/pdf`: original source download.
- `POST /api/workflows/{id}/review`: `{invoice, reviewer, note, confirmed:true}`.
  Validates an explicit canonical invoice against existing master references,
  atomically creates its invoice/document link, queues deterministic processing.
- `POST /api/workflows/{id}/retry`: `{}` or optional provider on an unconfirmed,
  failed run. Does not create another invoice or allocation.
- `GET /api/master-data`: vendors, POs, lines, receipts and current balances.
- `GET /api/dashboard`: real invoice/workflow counts, decision totals and recent runs.
- `GET /api/configuration`: provider configured booleans and nonsecret model names.
- `POST /api/receipts`: validated receipt entry from the master-data screen.
- `GET /api/samples/native` or `/scanned`: committed synthetic PDF download.

The original backend APIs and financial policy are preserved. The only Service
change lets invoice creation participate in an existing transaction so the workflow
link and invoice cannot diverge on concurrent confirmation or a crash.

## Workflow contracts

`workflows`, `workflow_keys` and append-only `workflow_events` tables are additive.
PDF bytes are written durably before enqueueing. Upload retries and byte-identical
PDFs resolve to one canonical workflow. A key cannot be reused for different bytes.
Different PDFs with the same business invoice number are still rejected by the
financial engine. Only an atomic queued→processing claim may execute a run.

Stages are upload, PDF/OCR, AI extraction, matching, validation and decision. Each
stage transition commits before the next begins. UI polling only reads those states.
Manual review skips AI explicitly, retaining real PDF text; it never synthesizes AI
fields or results. Every extraction requires a human confirmation before creating a
financial invoice. Exact printed references or a unique exact vendor name may
prefill mappings; missing/ambiguous matches remain blank. Suggestions never select
an ID. Tax, shipping or discount missing from extraction remain null, not zero.

Confirmation saves the reviewer, note and canonical submitted invoice to the audit
trail. Reviewer identity is self-reported in this local prototype, not authenticated.
Confirmed invoices are immutable. Financial Review caused by missing receipts can
be retried after master data is corrected, with a new processing key. Incorrect
confirmed fields require an audited correction workflow, not a silent edit here.
Approved/Rejected runs replay their existing result on retry. The engine's unique
allocation constraint and transactional balance checks remain the final safeguards.

Use **one Uvicorn worker/process**. FastAPI background tasks run after the 202
response. On startup queued jobs resume; previously processing jobs become visibly
failed with `INTERRUPTED` and require explicit retry. A crash after an allocation
but before a workflow update is safe: processing the linked invoice replays approval.
This is a persisted local workflow, not a distributed job queue. Parsing, model calls,
and storage require production isolation, auth, rate limits and backups before public
deployment. Invalid file/MIME/size requests are rejected before workflow creation;
in-workflow PDF/provider/processing failures retain a stage, code and safe message.

## Gemini configuration

The backend reads **`GEMINI_API_KEY`** and **`GEMINI_MODEL`** (default
`gemini-3.5-flash-lite` if unset). The submission `.env.example` recommends the
explicit owner-verified `gemini-3.1-flash-lite` selection; it is not auto-loaded.
OpenAI reads
`OPENAI_API_KEY` / `OPENAI_MODEL`. Export values only in the backend shell or secret
settings, restart the server, and inspect the configuration indicator. `.env` is
ignored and not automatically loaded; never use `VITE_` prefixes for credentials.
Gemini needs HTTPS access to `generativelanguage.googleapis.com`; OpenAI needs
`api.openai.com`. Existing proxy/CA settings are preserved. Keys stay in backend
request headers. The frontend receives only readiness booleans and model names.

The original Phase 4 Codex run had no provider key, and its provider contract tests
used explicit HTTP mocks. The owner now reports a working local Windows Gemini
demo using `gemini-3.1-flash-lite`; this is separate from automated evidence.
See [current validation](validation.md). Manual review remains the credential-free
alternative, with no invented AI fields, citations or financial decisions.

## Frontend

React/TypeScript, Vite and Tailwind implement overview counts, paginated/filterable
history, drag/drop intake, persisted stage polling, source text/quotes, matching
explanations, manual review, immutable confirmed fields, engine decisions, retry,
receipt entry and audit events. UI API requests use `/api`. Vite proxies those in
development; FastAPI serves `frontend/dist` if present at startup for a single-origin
built application. Navigation uses URL hashes so reloadable detail views work with
static hosting. Polling never fabricates intermediate steps or progress percentages.
Provider credentials remain server-side; browser configuration
contains only readiness booleans and model names. See `demo.md` for run commands.
