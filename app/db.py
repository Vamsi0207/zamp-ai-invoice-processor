import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_orders (
 id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL REFERENCES vendors(id),
 currency TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
 tolerance_enabled INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS po_lines (
 po_id TEXT NOT NULL REFERENCES purchase_orders(id), id TEXT NOT NULL,
 description TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0), PRIMARY KEY(po_id,id));
CREATE TABLE IF NOT EXISTS receipts (
 id TEXT PRIMARY KEY, po_id TEXT NOT NULL, po_line_id TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity > 0),
 FOREIGN KEY(po_id,po_line_id) REFERENCES po_lines(po_id,id));
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY, vendor_id TEXT NOT NULL, number TEXT NOT NULL,
 normalized_number TEXT NOT NULL, po_id TEXT, currency TEXT NOT NULL,
 total_cents INTEGER NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS invoice_duplicate ON invoices(vendor_id, normalized_number);
CREATE TABLE IF NOT EXISTS processing_runs (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 idempotency_key TEXT NOT NULL, decision TEXT NOT NULL,
 result TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(invoice_id,idempotency_key));
CREATE TABLE IF NOT EXISTS allocations (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL UNIQUE REFERENCES invoices(id),
 po_id TEXT NOT NULL REFERENCES purchase_orders(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
 run_id INTEGER NOT NULL UNIQUE REFERENCES processing_runs(id));
CREATE TABLE IF NOT EXISTS allocation_lines (
 allocation_id INTEGER NOT NULL REFERENCES allocations(id),
 po_line_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
 PRIMARY KEY(allocation_id,po_line_id));
"""


class Database:
    def __init__(self, path=None):
        self.path = str(path or os.getenv("ZAMP_DB_PATH", "data/zamp.sqlite3"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
