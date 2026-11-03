"""Idempotently populate an isolated synthetic demo database (never customer data)."""
import json
from pathlib import Path

from app.db import Database
from app.schemas import PurchaseOrder, Receipt, Vendor
from app.service import Service


def seed(path="data/demo.sqlite3"):
    service = Service(Database(path))
    dataset = json.loads((Path(__file__).resolve().parents[1] / "fixtures/synthetic_dataset.json").read_text())
    with service.database.connect() as db:
        present = db.execute("SELECT 1 FROM vendors WHERE id='DEMO-VENDOR'").fetchone()
    if present:
        return
    service.create_vendor(Vendor.model_validate(dataset["vendor"]))
    service.create_po(PurchaseOrder.model_validate(dataset["purchase_order"]))
    service.create_receipt(Receipt.model_validate(dataset["receipt"]))


if __name__ == "__main__":
    seed()
