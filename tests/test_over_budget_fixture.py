"""Fixture-only tests. Source fields are parsed locally, not claimed as Gemini output."""
import json
import re
from decimal import Decimal
from pathlib import Path

from app.db import Database
from app.documents import DocumentStore, parse_pdf
from app.extraction import ExtractionResult, validate_evidence
from app.schemas import Invoice
from app.service import Service
from scripts.seed import seed


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def read_fixture():
    pages = parse_pdf((FIXTURES / "over_budget_invoice.pdf").read_bytes())
    assert len(pages) == 1
    assert pages[0]["method"] == "native"
    text = pages[0]["text"]

    def field(label):
        match = re.search(re.escape(label) + r"([^\n]+)", text)
        assert match is not None, label
        return match.group(1).strip()

    row = re.search(r"(L1)\s+(Office chairs)\s+(\d+)\s+(\d+\.\d{2})\s+(\d+\.\d{2})", text)
    assert row is not None
    invoice = Invoice.model_validate({
        "vendor_id": field("Vendor reference: "), "number": field("Invoice number: "),
        "po_id": field("Purchase order: "), "currency": field("Currency: "),
        "total": field("TOTAL DUE: USD "), "tax": field("Tax: USD "),
        "shipping": field("Shipping: USD "), "discount": field("Discount: USD "),
        "lines": [{"po_line_id": row[1], "description": row[2], "quantity": int(row[3]), "unit_price": row[4]}],
    })
    return pages, invoice, Decimal(field("Subtotal: USD ")), Decimal(row[5]), row.group(0)


def test_over_budget_pdf_fields_arithmetic_and_evidence():
    pages, invoice, subtotal, line_amount, row_quote = read_fixture()
    assert "Synthetic Office Supply" in pages[0]["text"]
    assert invoice.vendor_id == "DEMO-VENDOR"
    assert invoice.number == "SYN-002"
    assert invoice.po_id == "DEMO-PO"
    assert invoice.currency == "USD"
    assert invoice.lines[0].description == "Office chairs"
    assert invoice.lines[0].quantity == 7
    assert invoice.lines[0].unit_price == Decimal("100.00")
    assert subtotal == line_amount == invoice.lines[0].quantity * invoice.lines[0].unit_price == Decimal("700.00")
    assert invoice.tax == invoice.shipping == invoice.discount == 0
    assert invoice.total == subtotal + invoice.tax + invoice.shipping - invoice.discount == Decimal("700.00")
    facts = {"vendor_name": "Synthetic Office Supply", "vendor_reference": invoice.vendor_id,
        "invoice_number": invoice.number, "po_number": invoice.po_id, "currency": invoice.currency,
        **{k: str(getattr(invoice, k)) for k in ("total", "tax", "shipping", "discount")},
        "lines": [{"line_reference": invoice.lines[0].po_line_id, "description": invoice.lines[0].description,
                   "quantity": invoice.lines[0].quantity, "unit_price": str(invoice.lines[0].unit_price)}]}
    quotes = {"vendor_name": "Synthetic Office Supply", "vendor_reference": "Vendor reference: DEMO-VENDOR",
        "invoice_number": "Invoice number: SYN-002", "po_number": "Purchase order: DEMO-PO", "currency": "Currency: USD",
        "total": "TOTAL DUE: USD 700.00", "tax": "Tax: USD 0.00", "shipping": "Shipping: USD 0.00", "discount": "Discount: USD 0.00"}
    for key in ("line_reference", "description", "quantity", "unit_price"):
        quotes[f"lines.0.{key}"] = row_quote
    # Deliberately manual source citations; tests do not impersonate real AI extraction.
    extraction = ExtractionResult.model_validate({"invoice": facts, "evidence": [
        {"field": key, "page": 1, "quote": quote} for key, quote in quotes.items()]})
    assert validate_evidence(extraction, pages) is extraction


def test_over_budget_fixture_rejected_without_duplicate_or_new_allocation(tmp_path):
    path = tmp_path / "isolated-demo.sqlite3"
    seed(path)
    database = Database(path)
    documents = DocumentStore(database, root=tmp_path / "documents")
    service = Service(database)
    dataset = json.loads((FIXTURES / "synthetic_dataset.json").read_text())
    first_document = documents.save((FIXTURES / "native_invoice.pdf").read_bytes())
    first = service.create_invoice(Invoice.model_validate(dataset["invoices"][0]), first_document["id"])
    assert first["number"] == "SYN-001"
    assert service.process(first["id"], "approve-original")["decision"] == "Approved"
    assert service.po_balance("DEMO-PO") == {
        "po_id": "DEMO-PO", "total_cents": 100000, "allocated_cents": 40000, "remaining_cents": 60000}
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
        received = db.execute("SELECT SUM(quantity) FROM receipts WHERE po_id='DEMO-PO' AND po_line_id='L1'").fetchone()[0]
        used = db.execute("SELECT SUM(quantity) FROM allocation_lines").fetchone()[0]
        assert received - used == 6
    _, invoice, _, _, _ = read_fixture()
    second_document = documents.save((FIXTURES / "over_budget_invoice.pdf").read_bytes())
    second = service.create_invoice(invoice, second_document["id"])
    result = service.process(second["id"], "test-over-budget")
    assert result["decision"] == "Rejected"
    assert "DUPLICATE_INVOICE" not in result["reasons"]
    assert "INVALID_TOTAL" not in result["reasons"]
    assert set(result["reasons"]) == {"PO_BALANCE_EXCEEDED", "ORDERED_QUANTITY_EXCEEDED", "RECEIPT_SHORTFALL"}
    assert service.process(second["id"], "test-over-budget") == result
    assert service.po_balance("DEMO-PO")["allocated_cents"] == 40000
    assert service.po_balance("DEMO-PO")["remaining_cents"] == 60000
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 1
        assert db.execute("SELECT SUM(quantity) FROM allocation_lines").fetchone()[0] == 4
    print("SYN-002:", result["decision"], ", ".join(result["reasons"]), "; allocated USD 400, remaining USD 600")
