# Financial and review rules

Authority: `app/engine.py`, `app/schemas.py`, `app/service.py`, `app/workflows.py`.
This documents the implemented prototype policy, not a universal accounting standard.
Policy version: `ps1-reconstruction-v1`.

## Representation and priority

One invoice has one vendor, one optional PO reference, one uppercase three-letter
currency, whole-unit quantities and money with at most two decimal places. No FX
conversion. Calculations use integer cents. Canonical inputs forbid unknown properties
and repeated PO line IDs within an invoice. Money inputs are nonnegative; the engine
also requires a positive total. Credit notes and fractional quantities are unsupported.

Reasons accumulate: **Rejected outranks Review**, which outranks Approved. Only
Approved creates money/quantity allocations. Human confirmation does not waive checks.

## Mandatory validation

| Check | Actual behavior |
| --- | --- |
| Vendor | Unknown/inactive: Rejected (`UNKNOWN_VENDOR`, `INACTIVE_VENDOR`) |
| PO vendor/currency | Mismatch: Rejected (`PO_VENDOR_MISMATCH`, `CURRENCY_MISMATCH`) |
| Missing PO | Low-level engine: Review (`PO_REQUIRED`/`PO_NOT_FOUND`). Workflow stays unresolved until a human selects an existing PO, before creating its financial invoice |
| PO line | Unknown: Rejected (`UNKNOWN_PO_LINE`); workflow confirmation first requires existing line IDs |
| Business duplicate | Earlier stored invoice with same vendor/normalized number: Rejected (`DUPLICATE_INVOICE`) |
| Arithmetic | `sum(quantity × unit_price) + tax + shipping − discount` must equal total and be positive; otherwise Rejected (`INVALID_TOTAL`) |
| Ordered quantity | Allocated + requested units above ordered units per line: Rejected (`ORDERED_QUANTITY_EXCEEDED`) |
| Receipts | Allocated + requested units above received units per line: Review (`RECEIPT_SHORTFALL`), unless another check rejects |
| Unit price | Any difference from PO price: Review (`UNIT_PRICE_VARIANCE`), unless another check rejects |
| Amount | Current allocated cents + invoice cents checked against original all-inclusive PO ceiling and the policy below |

Duplicate numbers are case-folded and all non-alphanumeric characters removed:
`SYN-001` and `syn 001` collide. The earliest **stored** invoice reserves the number,
even if not approved. No automatic deletion/replacement clears it. This is separate
from SHA-256 upload deduplication, which returns one workflow for identical bytes.

## Matching and suggestions

Workflow matching tries exact vendor reference, then one unique case-insensitive
exact vendor name. It prefills only the exact referenced PO for that vendor and exact
line references. Missing/ambiguous mappings stay blank. No fuzzy or AI-created IDs.

Workflow suggestions list that vendor's POs, filtered by extracted currency when
present; they are not reservations or approvals. Low-level engine suggestions for a
missing PO are more restrictive: up to five same-vendor/currency POs with nominal
unallocated balance, sorted by ID. Every workflow needs explicit reviewed selections
and final current-balance checks.

## Partial invoicing and conditional 2% tolerance

Unique invoices may partially consume a PO over time. Only Approved allocations
consume cents and quantities. Available receipts are received totals minus allocated
line quantities; receipt rows are not decremented.

The original PO total is an all-inclusive ceiling, including tax/shipping. For
cumulative amount `C` and ceiling `P`:

| Range | Policy |
| --- | --- |
| `C ≤ P` | Amount check passes; other checks still apply |
| `P < C ≤ 1.02 × P` | Passes only if PO `tolerance_enabled=true`; otherwise Review (`TOLERANCE_NOT_AUTHORIZED`) |
| `C > 1.02 × P` | Rejected (`PO_BALANCE_EXCEEDED`), regardless of the flag |

Integer cross-multiplication prevents rounding from authorizing another cent. The
flag never permits excess/unreceived units or price variance to auto-approve. Matching
prices/quantities plus small verified shipping may use monetary tolerance; raising a
unit price still triggers Review. The demo PO does **not** enable tolerance. These
thresholds/severities are policy choices; changing them is a separate coding task.

## Confirmation, audit and retries

Workflow review requires a name, note and explicit confirmation. Missing facts must
be verified, not assumed zero. Vendor, PO and line IDs must already exist. The
engine independently checks ownership, price, quantities, receipts and balances.
Reviewer identity is self-reported; no authenticated approval roles are implemented.

Confirmed invoice content is immutable. Identical confirmation reuses it; changed
content conflicts. Financial processing uses `BEGIN IMMEDIATE` and atomically writes
run/allocation/lines. Same-key retries replay a recorded result; an approved invoice
replays approval under any key, never allocating twice. A new service-level key can
reevaluate an unapproved invoice; workflow Approved/Rejected states are terminal
replays, while financial Review can rerun after receipts are supplied. Pre-invoice
Review needs the form, not a blind retry.

Stages, confirmation, decision, policy version and reasons are retained for inspection.
The audit is not cryptographically protected. There is no credit-note, cancellation,
allocation release or audited correction/reversal workflow.

## Submission scenarios

After SYN-001 approves 4 chairs/$400 on the $1,000/10-chair PO with 10 received chairs,
the available amount is $600 and unconsumed received quantity is 6.

- Another PDF with the same SYN-001/vendor is a business duplicate; allocation stays $400.
- Unique SYN-002 for 7 chairs/$700 takes cumulative usage to 11 chairs/$1,100. It
  reports `ORDERED_QUANTITY_EXCEEDED`, `PO_BALANCE_EXCEEDED`, `RECEIPT_SHORTFALL`.
  Final result: Rejected; no new allocation. This does **not** isolate amount alone.

See [the walkthrough](demo-walkthrough.md) for exact state and fixture ordering.
