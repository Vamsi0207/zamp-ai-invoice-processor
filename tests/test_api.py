import pytest

from conftest import invoice


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_records(client):
    assert client.get("/purchase-orders/missing/balance").status_code == 404
    assert client.post("/invoices/999/process", json={"idempotency_key": "a"}).status_code == 404


def test_reference_and_duplicate_errors(seeded):
    assert seeded.post("/vendors", json={"id": "V1", "name": "Again"}).status_code == 409
    assert seeded.post("/receipts", json={"id": "bad", "po_id": "PO1", "po_line_id": "missing", "quantity": 1}).status_code == 422
    assert seeded.post("/receipts", json={"id": "bad", "po_id": "PO1", "po_line_id": "L1", "quantity": 1}).status_code == 422


@pytest.mark.parametrize("changes", [
    {"total": "-1"}, {"total": "1.001"}, {"total": "NaN"}, {"currency": "usd"},
    {"number": ""}, {"number": "---"}, {"unexpected": True},
    {"lines": []}, {"lines": [{"po_line_id": "L1", "description": "Widgets", "quantity": 0, "unit_price": "10"}]},
    {"lines": [{"po_line_id": "L1", "description": "Widgets", "quantity": 1.5, "unit_price": "10"}]},
])
def test_invalid_invoice_schema(client, changes):
    assert client.post("/invoices", json=invoice(**changes)).status_code == 422


def test_duplicate_line_rejected(client):
    body = invoice()
    body["lines"] *= 2
    assert client.post("/invoices", json=body).status_code == 422


def test_po_invalid_total(client):
    result = client.post("/purchase-orders", json={"id": "P", "vendor_id": "V", "total": "1", "lines": [
        {"id": "L", "description": "A", "quantity": 2, "unit_price": "1"}]})
    assert result.status_code == 422


def test_invoice_audit_history(seeded):
    from conftest import submit
    result = submit(seeded).json()
    response = seeded.get(f"/invoices/{result['invoice_id']}").json()
    assert response["invoice"]["number"] == "INV-001"
    assert response["processing_runs"] == [result]
    assert seeded.get("/invoices/999").status_code == 404
