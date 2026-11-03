from concurrent.futures import ThreadPoolExecutor

import pytest

from app.schemas import Invoice
from app.service import Service
from conftest import invoice, submit


def test_partial_and_cumulative_balance(seeded):
    assert submit(seeded).json()["decision"] == "Approved"
    assert seeded.get("/purchase-orders/PO1/balance").json()["remaining_cents"] == 5000
    assert submit(seeded, invoice(number="INV-002")).json()["decision"] == "Approved"
    assert seeded.get("/purchase-orders/PO1/balance").json()["remaining_cents"] == 0
    result = submit(seeded, invoice(number="INV-003")).json()
    assert result["decision"] == "Rejected"
    assert "ORDERED_QUANTITY_EXCEEDED" in result["reasons"]


@pytest.mark.parametrize("changes,code,decision", [
    ({"vendor_id": "missing"}, "UNKNOWN_VENDOR", "Rejected"),
    ({"currency": "EUR"}, "CURRENCY_MISMATCH", "Rejected"),
    ({"po_id": "missing"}, "PO_NOT_FOUND", "Review"),
    ({"po_id": None}, "PO_REQUIRED", "Review"),
    ({"total": "49.99"}, "INVALID_TOTAL", "Rejected"),
    ({"total": "0"}, "INVALID_TOTAL", "Rejected"),
    ({"total": "55", "lines": [{"po_line_id": "L1", "description": "Widgets", "quantity": 5, "unit_price": "11"}]}, "UNIT_PRICE_VARIANCE", "Review"),
    ({"lines": [{"po_line_id": "wrong", "description": "Widgets", "quantity": 5, "unit_price": "10"}]}, "UNKNOWN_PO_LINE", "Rejected"),
])
def test_decisions(seeded, changes, code, decision):
    result = submit(seeded, invoice(**changes)).json()
    assert result["decision"] == decision
    assert code in result["reasons"]
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 0


def test_duplicate_normalized_number(seeded):
    assert submit(seeded).json()["decision"] == "Approved"
    result = submit(seeded, invoice(number="inv 001")).json()
    assert result["decision"] == "Rejected"
    assert "DUPLICATE_INVOICE" in result["reasons"]


def test_duplicate_reserved_before_approval(seeded):
    first = seeded.post("/invoices", json=invoice()).json()["id"]
    assert submit(seeded, invoice(number="inv001")).json()["decision"] == "Rejected"
    assert seeded.post(f"/invoices/{first}/process", json={"idempotency_key": "a"}).json()["decision"] == "Approved"


def test_retry_same_and_different_key(seeded):
    invoice_id = seeded.post("/invoices", json=invoice()).json()["id"]
    first = seeded.post(f"/invoices/{invoice_id}/process", json={"idempotency_key": "a"}).json()
    for key in ("a", "b"):
        assert seeded.post(f"/invoices/{invoice_id}/process", json={"idempotency_key": key}).json() == first
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 5000


def test_review_then_receipt_and_retry(client):
    client.post("/vendors", json={"id": "V1", "name": "Vendor"})
    client.post("/purchase-orders", json={"id": "PO1", "vendor_id": "V1", "total": "100", "lines": [
        {"id": "L1", "description": "Widgets", "quantity": 10, "unit_price": "10"}]})
    invoice_id = client.post("/invoices", json=invoice()).json()["id"]
    route = f"/invoices/{invoice_id}/process"
    original = client.post(route, json={"idempotency_key": "a"}).json()
    assert original["decision"] == "Review"
    assert "RECEIPT_SHORTFALL" in original["reasons"]
    client.post("/receipts", json={"id": "R", "po_id": "PO1", "po_line_id": "L1", "quantity": 5})
    assert client.post(route, json={"idempotency_key": "a"}).json() == original
    assert client.post(route, json={"idempotency_key": "b"}).json()["decision"] == "Approved"


@pytest.mark.parametrize("enabled,shipping,expected", [
    (True, "2.00", "Approved"), (True, "2.01", "Rejected"),
    (False, "2.00", "Review"), (False, "0", "Approved"),
])
def test_tolerance(client, enabled, shipping, expected):
    from decimal import Decimal
    client.post("/vendors", json={"id": "V1", "name": "Vendor"})
    client.post("/purchase-orders", json={"id": "PO1", "vendor_id": "V1", "total": "100", "tolerance_enabled": enabled,
        "lines": [{"id": "L1", "description": "Widgets", "quantity": 10, "unit_price": "10"}]})
    client.post("/receipts", json={"id": "R", "po_id": "PO1", "po_line_id": "L1", "quantity": 10})
    body = invoice(total=str(100 + Decimal(shipping)), shipping=shipping,
                   lines=[{"po_line_id": "L1", "description": "Widgets", "quantity": 10, "unit_price": "10"}])
    assert submit(client, body).json()["decision"] == expected


def test_tolerance_is_cumulative(client):
    client.post("/vendors", json={"id": "V1", "name": "Vendor"})
    client.post("/purchase-orders", json={"id": "PO1", "vendor_id": "V1", "total": "100", "tolerance_enabled": True,
        "lines": [{"id": "L1", "description": "Widgets", "quantity": 10, "unit_price": "10"}]})
    client.post("/receipts", json={"id": "R", "po_id": "PO1", "po_line_id": "L1", "quantity": 10})
    assert submit(client, invoice(shipping="2", total="52")).json()["decision"] == "Approved"
    assert submit(client, invoice(number="second", shipping="0.01", total="50.01")).json()["decision"] == "Rejected"


def test_inactive_and_wrong_vendor(seeded):
    seeded.post("/vendors", json={"id": "V2", "name": "Inactive", "active": False})
    result = submit(seeded, invoice(vendor_id="V2")).json()
    assert result["decision"] == "Rejected"
    assert {"INACTIVE_VENDOR", "PO_VENDOR_MISMATCH"} <= set(result["reasons"])


def test_suggestions_only_same_vendor_currency(seeded):
    result = submit(seeded, invoice(po_id=None)).json()
    assert result["suggested_po_ids"] == ["PO1"]
    assert submit(seeded, invoice(po_id=None, number="different", currency="EUR")).json()["suggested_po_ids"] == []


def test_concurrent_competing_allocations(seeded):
    service = seeded.app.state.service
    ids = [service.create_invoice(Invoice.model_validate(invoice(number=f"INV-{i}", total="70",
        lines=[{"po_line_id": "L1", "description": "Widgets", "quantity": 7, "unit_price": "10"}])))["id"] for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: service.process(i, "concurrent"), ids))
    assert sorted(r["decision"] for r in results) == ["Approved", "Rejected"]
    assert service.po_balance("PO1")["allocated_cents"] == 7000


def test_concurrent_same_invoice(seeded):
    service = seeded.app.state.service
    invoice_id = service.create_invoice(Invoice.model_validate(invoice()))["id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: service.process(invoice_id, "retry"), range(6)))
    assert all(r == results[0] for r in results)
    assert service.po_balance("PO1")["allocated_cents"] == 5000


def test_failure_rolls_back_allocation_and_run(seeded):
    service = seeded.app.state.service
    invoice_id = service.create_invoice(Invoice.model_validate(invoice()))["id"]
    with service.database.connect() as db:
        db.execute("""CREATE TRIGGER simulated_failure BEFORE INSERT ON allocation_lines
            BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        service.process(invoice_id, "first")
    with service.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 0
        db.execute("DROP TRIGGER simulated_failure")
    assert service.process(invoice_id, "first")["decision"] == "Approved"


def test_persistence_across_service_instances(seeded):
    original = submit(seeded).json()
    service = Service(seeded.app.state.service.database)
    assert service.process(original["invoice_id"], "new") == original
    assert service.po_balance("PO1")["allocated_cents"] == 5000


def test_tax_shipping_discount_and_multiple_lines(client):
    client.post("/vendors", json={"id": "V1", "name": "Vendor"})
    client.post("/purchase-orders", json={"id": "PO1", "vendor_id": "V1", "total": "100", "lines": [
        {"id": "L1", "description": "A", "quantity": 5, "unit_price": "10"},
        {"id": "L2", "description": "B", "quantity": 2, "unit_price": "20"}]})
    for i, qty in ((1, 5), (2, 2)):
        client.post("/receipts", json={"id": f"R{i}", "po_id": "PO1", "po_line_id": f"L{i}", "quantity": qty})
    body = invoice(total="95", tax="7", shipping="3", discount="5", lines=[
        {"po_line_id": "L1", "description": "A", "quantity": 5, "unit_price": "10"},
        {"po_line_id": "L2", "description": "B", "quantity": 2, "unit_price": "20"}])
    assert submit(client, body).json()["decision"] == "Approved"
    assert client.get("/purchase-orders/PO1/balance").json()["remaining_cents"] == 500


def test_synthetic_dataset_end_to_end(client):
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parents[1] / "fixtures/synthetic_dataset.json").read_text())
    assert client.post("/vendors", json=data["vendor"]).status_code == 201
    assert client.post("/purchase-orders", json=data["purchase_order"]).status_code == 201
    assert client.post("/receipts", json=data["receipt"]).status_code == 201
    for body in data["invoices"]:
        assert submit(client, body).json()["decision"] == "Approved"
    assert client.get("/purchase-orders/DEMO-PO/balance").json()["remaining_cents"] == 0
