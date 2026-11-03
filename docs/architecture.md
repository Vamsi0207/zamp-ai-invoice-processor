# Zamp PS-1 reconstruction

This is a reconstruction, not recovery of the earlier implementation or its 84 tests.

## Financial policy v1

All arithmetic uses integer cents; inputs allow at most two decimal places. Quantities
are whole units. One invoice targets one PO and each PO line appears at most once.
The PO total is an all-inclusive ceiling (including tax and shipping). Invoice total
must equal quantity × unit price + tax + shipping − discount. Zero totals are rejected.
Currency conversion, fractional quantities, credit notes, and receipt reversals are
outside this version's scope and must not be inferred.

Unknown/inactive vendors, vendor/currency mismatch, unknown lines, invalid totals,
duplicate numbers, quantities above ordered amounts, and cumulative spend above
102% of the original PO total are Rejected. Missing POs/receipts, any unit-price
variance, and spend over 100% without explicit tolerance authorization are Review.
Only POs with `tolerance_enabled=true` may approve cumulative spend up to exactly
102%, with exact unit prices, all quantities received, and all other checks passing.
Tolerance never permits additional ordered or unreceived units. Rejected outranks
Review. Only Approved results allocate funds or received quantities.

Vendor-scoped invoice numbers are case-folded with punctuation removed. The earliest
stored invoice reserves that number, even if it is not approved; later duplicates
are rejected. Corrections require an explicit future audited workflow, not changing
invoice contents on retry. Missing POs produce up to five deterministic same-vendor,
same-currency suggestions with an unallocated nominal balance; suggestions never
auto-approve or automatically bind a PO.

## Persistence and transactions

FastAPI validates transport schemas; Service implements storage and transaction
orchestration; the pure engine only evaluates supplied state. SQLite foreign keys
protect master/receipt/allocation references. Unknown vendor/PO references on invoices
are intentionally retained for auditable rejection/review. Invoice lines are stored
in the immutable JSON payload. PO and allocation lines are relational records.

`BEGIN IMMEDIATE` serializes processing and receipt updates before reading balances.
Run, allocation, and allocation lines commit together or roll back together.
`UNIQUE(invoice_id)` prevents a second allocation. Processing keys are scoped to each
immutable invoice. Reusing a key returns the recorded result; a new key reevaluates a
Review/Rejected invoice. Once Approved, every key returns its original approval.
Amounts and received quantities are consumed cumulatively per PO/line.

SQLite is suitable for a single-host prototype with bounded write contention, not
multi-host production. There is currently no user authentication or authorization;
run on loopback only. Production deployment requires access control, migrations,
operational backups, retention policy, and resource isolation for document parsers.

## Validation

Tests cover API validation, partial invoices, cumulative balances, tolerance boundaries,
receipt shortfalls, duplicates, concurrent competing allocations and retries,
rollback on an injected allocation failure, and persistent approved-run replay.

## Documents and AI boundary

DocumentStore persists content-addressed PDF files plus SQLite page text/method
metadata. A temporary file is fully written before an atomic hard-link publishes
the SHA-256 filename. A crash may leave an unreferenced PDF, never a partially
published document; an operator can reconcile orphaned files during maintenance.
PDF bytes and database metadata must be backed up together. Uploaded documents are
deduplicated by bytes, independently of business duplicate detection.

PyMuPDF extracts native text page by page. Pages with fewer than 30 alphanumeric
characters use Tesseract OCR at 200 DPI with a 30-second per-page timeout and a
12-million-pixel rendering ceiling. Documents have a 100,000-character text budget.
Sparse native text can be OCRed; a misleading long hidden text layer is not detected.
Parser/AI operations are synchronous threadpool jobs. Production needs process-level
CPU/memory isolation, request-body limits, rate limits, and a durable background queue.
These application-level bounds are not a complete hostile-PDF sandbox.

Gemini generateContent and OpenAI chat/completions use schema-constrained JSON with
nullable missing facts. Every returned non-null scalar requires a page quote that
exists in extracted text and includes the string or numeric value. Invalid schemas,
refusals, truncation, unsupported citations, timeouts and upstream errors fail closed.
There is no provider fallback that fabricates results. API keys are used only in
headers to fixed provider hosts, never query strings, persisted records or responses.
TLS verification and inherited proxy/CA configuration remain enabled. The selected
provider receives invoice text: configure consent/retention before using real data.

Extraction attempts retain provider, model, status and evidence. No AI adapter can
allocate money. Explicit reviewed-invoice submission creates an immutable invoice
and document link in one database transaction. Only the deterministic engine can
approve and allocate it. Evidence checks do not establish that a document is genuine,
or that a quoted amount is the right business field. Human review is mandatory.

## Operational scope

Schema creation is additive for this initial reconstruction; versioned migrations
are not implemented. There is no master-data editing, PO close/cancel operation,
allocation release, credit-note or duplicate-correction workflow. This backend does
not initiate payments. Synthetic seeds and PDFs support repeatable local validation.
CI runs the frozen Python dependencies and real English OCR without provider keys.
