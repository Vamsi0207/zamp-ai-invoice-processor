"""Pure deterministic policy evaluation; caller supplies transaction-consistent state."""
from .schemas import Invoice, cents


POLICY_VERSION = "ps1-reconstruction-v1"


def evaluate(invoice: Invoice, vendor, po, po_lines, receipts, allocated, used, duplicate, suggestions):
    reasons = []
    severity = 0

    def flag(code, level):
        nonlocal severity
        reasons.append(code)
        severity = max(severity, level)

    if vendor is None:
        flag("UNKNOWN_VENDOR", 2)
    elif not vendor["active"]:
        flag("INACTIVE_VENDOR", 2)
    if duplicate:
        flag("DUPLICATE_INVOICE", 2)
    expected = sum(cents(line.unit_price) * line.quantity for line in invoice.lines)
    expected += cents(invoice.tax) + cents(invoice.shipping) - cents(invoice.discount)
    if expected != cents(invoice.total) or expected < 0 or invoice.total <= 0:
        flag("INVALID_TOTAL", 2)
    if po is None:
        flag("PO_NOT_FOUND" if invoice.po_id else "PO_REQUIRED", 1)
    else:
        if po["vendor_id"] != invoice.vendor_id:
            flag("PO_VENDOR_MISMATCH", 2)
        if po["currency"] != invoice.currency:
            flag("CURRENCY_MISMATCH", 2)
        for line in invoice.lines:
            target = po_lines.get(line.po_line_id)
            if target is None:
                flag("UNKNOWN_PO_LINE", 2)
                continue
            cumulative = used.get(line.po_line_id, 0) + line.quantity
            if cumulative > target["quantity"]:
                flag("ORDERED_QUANTITY_EXCEEDED", 2)
            if cumulative > receipts.get(line.po_line_id, 0):
                flag("RECEIPT_SHORTFALL", 1)
            if cents(line.unit_price) != target["unit_price_cents"]:
                flag("UNIT_PRICE_VARIANCE", 1)
        cumulative_amount = allocated + cents(invoice.total)
        # Integer cross multiplication avoids rounding an extra cent into tolerance.
        if cumulative_amount * 100 > po["total_cents"] * 102:
            flag("PO_BALANCE_EXCEEDED", 2)
        elif cumulative_amount > po["total_cents"]:
            if not po["tolerance_enabled"]:
                flag("TOLERANCE_NOT_AUTHORIZED", 1)
            else:
                reasons.append("WITHIN_AUTHORIZED_2_PERCENT_TOLERANCE")
    return {
        "decision": ("Approved", "Review", "Rejected")[severity],
        "reasons": sorted(set(reasons)) or ["ALL_CHECKS_PASSED"],
        "suggested_po_ids": suggestions if po is None else [],
        "policy_version": POLICY_VERSION,
        "previously_allocated_cents": allocated,
        "invoice_total_cents": cents(invoice.total),
        "po_total_cents": po["total_cents"] if po else None,
    }
