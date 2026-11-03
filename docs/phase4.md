# Phase 4: invoice operations

## Persistent workflow API

New endpoints exist directly and under `/api` for same-origin frontend requests.

- `POST /api/workflows`: multipart PDF, `provider` (`gemini`, `openai`, or `manual`),
  and required `idempotency_key`. Returns HTTP 202 and the canonical persisted run.
- `GET /api/workflows?limit=50&offset=0`: paginated history.
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
`gemini-2.5-flash`), exactly as `.env.example` and `AIAdapter` specify. OpenAI reads
`OPENAI_API_KEY` / `OPENAI_MODEL`. Export values only in the backend shell or secret
settings, restart the server, and inspect the configuration indicator. `.env` is
ignored and not automatically loaded; never use `VITE_` prefixes for credentials.
Gemini needs HTTPS access to `generativelanguage.googleapis.com`; OpenAI needs
`api.openai.com`. Existing proxy/CA settings are preserved. Keys stay in backend
request headers. The frontend receives only readiness booleans and model names.

Neither provider key is available in the current task. Live AI calls cannot be
verified. Test-provider contract responses are explicitly mocked in automated tests,
never served as application decisions or as a demo production mode. Use manual
review for an honest credential-free demo, or configure Gemini for live extraction.
