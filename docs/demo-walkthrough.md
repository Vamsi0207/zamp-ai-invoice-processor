# Submission demo: approval, duplicate prevention and over-invoicing

Allow about five minutes after setup. Use [Windows setup](windows.md), the explicit
`GEMINI_MODEL=gemini-3.1-flash-lite` selection and **one fresh seeded database**.
The owner reports observing all three scenarios locally through React with live
Gemini. Those reports are manual evidence; automated checks are listed separately
in [validation](validation.md). No live AI success is inferred from a mocked test.

## State before starting

| Record | Required value |
| --- | --- |
| Vendor | DEMO-VENDOR / Synthetic Office Supply, active |
| PO | DEMO-PO, USD 1,000 ceiling, tolerance disabled |
| PO line | L1 / Office chairs, 10 units at USD 100 |
| Receipt | 10 units on DEMO-PO / L1 |
| Invoices / allocations | None |

`seed(path)` initializes only those master/receipt records. The `invoices` array
in `fixtures/synthetic_dataset.json` is illustrative data, **not seeded records**.
Its SYN-002/$600 partial-invoice example is not scenario C; use the $700 PDF below.
Do not pre-create SYN-001/SYN-002 through low-level APIs before this sequence.

The initial Overview is empty, and Master data shows $1,000 remaining and 10/10
received. A stored but unapproved earlier invoice number can affect duplicates, so
zero monetary allocation alone does not establish a clean demo state.

## Common UI actions

Select Gemini as extraction method before dropping a PDF. Observe the real backend
timeline, then inspect Field evidence/Document text. A successful extraction enters
**Needs review**; it has not allocated money. Confirm the vendor, PO, each line,
currency, totals and explicit zero tax/shipping/discount. Enter reviewer name/note,
check the acknowledgement, and choose **Confirm & process**. The engine decides.

With no provider access, explicitly select Manual review and enter the same fields
from the source. Label that presentation as a manual-mode business-rule demo; it
does not demonstrate real AI extraction or AI-generated source evidence. Failed
provider/schema/evidence stages are not approvals and must not be bypassed.

## A — Valid invoice approval (about 90 seconds)

**Starting state:** the fresh state above. **Fixture:** `fixtures/native_invoice.pdf`.

1. Drag the PDF onto Overview (or use Upload invoice/Browse files).
2. With live Gemini, show the completed extraction/evidence stages and citations
   before confirmation. Expected facts are SYN-001, DEMO-VENDOR, DEMO-PO, USD,
   L1 Office chairs, quantity 4, unit price 100.00, subtotal/total 400.00 and zero
   tax/shipping/discount. Evidence must ground each non-null extracted scalar on
   the actual source page; it is not hardcoded to a particular quotation count.
3. Check mappings and source, enter the review acknowledgement, then process.
4. Show **Approved**, the confirmed immutable fields, decision reasons, audit event
   and Master data balance: **$400 allocated, $600 remaining**. Four units are
   allocated; six received units remain unconsumed.

**Evaluator message:** AI extracted facts; a human confirmed them; deterministic
checks committed the allocation. Neither extraction success nor the checkbox alone
was financial approval.

**State to preserve:** keep this same DB for B and C. Do not reseed/reset it.

## B — Duplicate prevention (about 90 seconds)

**Starting state:** A approved; $400 allocated/$600 available. **Fixture:**
`fixtures/duplicate_invoice_variant.pdf` (same SYN-001/vendor/PO, different bytes
and visible layout, four chairs/$400).

1. First re-upload the identical original `fixtures/native_invoice.pdf`. Show that
   it opens the same workflow/run and produces no second allocation or new AI call.
2. Upload the distinct variant with Gemini selected. It creates a **new** run because
   its SHA-256 differs. Observe real extraction again; verify that its business
   number is still SYN-001 and its vendor still DEMO-VENDOR. Do not change the number
   to avoid the duplicate check.
3. Confirm the valid source facts and mappings. Show **Rejected** with
   `DUPLICATE_INVOICE`. Its canonical arithmetic is valid; rejection is business-level.
4. Show separate run IDs, the same vendor/invoice identity, and unchanged Master
   data balance: **$400 allocated, $600 remaining**.

**Evaluator message:** file deduplication and vendor-scoped business duplicates solve
different problems. A changed layout cannot authorize a duplicate payment allocation.

**Reset note:** already uploading/confirming the variant changes stored run history.
Repeating it returns that rejected workflow. To re-demonstrate new-run behavior from
scratch, start the entire sequence with a fresh DB, not an edited invoice number.

## C — Over-budget invoice rejection (about 90 seconds)

**Starting state:** A approved, B has not allocated; $600 and six units available.
No earlier stored SYN-002 for this vendor. **Fixture:** `fixtures/over_budget_invoice.pdf`.

1. Upload it with Gemini and inspect source/evidence. Expected facts: unique
   SYN-002, DEMO-VENDOR, DEMO-PO, USD, L1 Office chairs, **7 × $100**, subtotal/total
   **$700**, tax/shipping/discount **$0**. Arithmetic is valid.
2. Confirm those exact facts; do not lower the amount or units to manufacture approval.
3. Show **Rejected**, not duplicate rejection, with the engine's applicable reasons:
   - `PO_BALANCE_EXCEEDED`: cumulative $400 + $700 = $1,100.
   - `ORDERED_QUANTITY_EXCEEDED`: cumulative 4 + 7 = 11 ordered units versus 10.
   - `RECEIPT_SHORTFALL`: cumulative 11 versus 10 received units.
4. Show **$400 allocated, $600 remaining** after rejection, and the recorded reasons
   and review submission in history/audit. No new financial allocation was written.

**Evaluator message:** this deliberately exceeds both monetary and quantity/receipt
availability. It does **not** isolate the financial ceiling alone. Receipt shortfall
by itself is Review; the amount/ordered-quantity violations make this case Rejected.

## Reset and troubleshooting

To repeat all scenarios, stop only your demo server, select fresh DB/document paths,
seed that new path and restart with the same secure provider environment. Do not
delete/overwrite a database with work to preserve. Reseeding an existing DB does
not reset balances or remove stored invoice numbers. Do not regenerate PDFs midway:
new bytes may create new workflows while the same business number remains reserved.

If the dashboard is absent, build the frontend before restarting FastAPI. If model
access/quota fails, inspect the recorded safe error and select an explicitly supported
mode; do not present a failed extraction as a successful AI demonstration. Source
citations are grounding checks, not proof of authenticity. See [business rules](business-rules.md).

Screenshots in `docs/screenshots/` show synthetic automated browser activity from an
earlier test run, not screenshots of the owner's live Gemini demonstration.
