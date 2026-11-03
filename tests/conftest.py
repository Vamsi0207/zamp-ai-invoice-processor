import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite3")) as c:
        yield c


@pytest.fixture
def seeded(client):
    assert client.post("/vendors", json={"id": "V1", "name": "Synthetic Supply Co"}).status_code == 201
    assert client.post("/purchase-orders", json={
        "id": "PO1", "vendor_id": "V1", "total": "100.00", "lines": [
            {"id": "L1", "description": "Widgets", "quantity": 10, "unit_price": "10.00"}]
    }).status_code == 201
    assert client.post("/receipts", json={"id": "R1", "po_id": "PO1", "po_line_id": "L1", "quantity": 10}).status_code == 201
    return client


def invoice(**changes):
    body = {"vendor_id": "V1", "number": "INV-001", "po_id": "PO1", "total": "50.00",
            "lines": [{"po_line_id": "L1", "description": "Widgets", "quantity": 5, "unit_price": "10.00"}]}
    body.update(changes)
    return body


def submit(client, body=None, key="first"):
    response = client.post("/invoices", json=body or invoice())
    assert response.status_code == 201, response.text
    return client.post(f"/invoices/{response.json()['id']}/process", json={"idempotency_key": key})
