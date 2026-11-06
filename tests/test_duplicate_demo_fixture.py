"""Verify the submission's distinct-document business duplicate, without AI mocks."""
import hashlib
import json
import re
from pathlib import Path

from app.db import Database
from app.documents import DocumentStore, parse_pdf
from app.schemas import Invoice
from app.service import Service
from scripts.seed import seed


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_duplicate_demo_pdf_is_distinct_but_rejected_for_same_business_invoice(tmp_path):
    original = (FIXTURES / "native_invoice.pdf").read_bytes()
    variant = (FIXTURES / "duplicate_invoice_variant.pdf").read_bytes()
    assert hashlib.sha256(original).digest() != hashlib.sha256(variant).digest()
    for data in (original, variant):
        pages = parse_pdf(data)
        assert len(pages) == 1 and pages[0]["method"] == "native"
        text = pages[0]["text"]
        for label in ("DEMO-VENDOR", "Invoice number: SYN-001", "Purchase order: DEMO-PO", "Currency: USD",
                      "TOTAL DUE: USD 400.00", "Tax: USD 0.00", "Shipping: USD 0.00", "Discount: USD 0.00"):
            assert label in text
        assert re.search(r"L1\s+Office chairs\s+4\s+100\.00\s+400\.00", text)
    path = tmp_path / "demo.sqlite3"
    seed(path)
    database = Database(path)
    store = DocumentStore(database, root=tmp_path / "documents")
    service = Service(database)
    # Explicitly supplied synthetic facts, not a claim of live AI extraction.
    facts = Invoice.model_validate(json.loads((FIXTURES / "synthetic_dataset.json").read_text())["invoices"][0])
    first_document, second_document = store.save(original), store.save(variant)
    assert first_document["id"] != second_document["id"]
    first = service.create_invoice(facts, first_document["id"])
    assert service.process(first["id"], "original")["decision"] == "Approved"
    second = service.create_invoice(facts, second_document["id"])
    result = service.process(second["id"], "business-duplicate")
    assert result["decision"] == "Rejected"
    assert result["reasons"] == ["DUPLICATE_INVOICE"]
    assert service.po_balance("DEMO-PO")["allocated_cents"] == 40000
    assert service.po_balance("DEMO-PO")["remaining_cents"] == 60000
