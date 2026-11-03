import json

from .engine import evaluate
from .schemas import Invoice, cents


def normalize_number(number):
    return "".join(c for c in number.casefold() if c.isalnum())


class Service:
    def __init__(self, database):
        self.database = database

    def create_vendor(self, vendor):
        with self.database.transaction() as db:
            db.execute("INSERT INTO vendors VALUES (?,?,?)", (vendor.id, vendor.name, vendor.active))
        return vendor.model_dump()

    def create_po(self, po):
        with self.database.transaction() as db:
            db.execute("INSERT INTO purchase_orders VALUES (?,?,?,?,?)", (
                po.id, po.vendor_id, po.currency, cents(po.total), po.tolerance_enabled))
            db.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?)", [
                (po.id, line.id, line.description, line.quantity, cents(line.unit_price)) for line in po.lines])
        return po.model_dump(mode="json")

    def create_receipt(self, receipt):
        with self.database.transaction() as db:
            line = db.execute("SELECT quantity FROM po_lines WHERE po_id=? AND id=?",
                              (receipt.po_id, receipt.po_line_id)).fetchone()
            if line is None:
                raise ValueError("PO line not found")
            received = db.execute("SELECT COALESCE(SUM(quantity),0) FROM receipts WHERE po_id=? AND po_line_id=?",
                                  (receipt.po_id, receipt.po_line_id)).fetchone()[0]
            if received + receipt.quantity > line["quantity"]:
                raise ValueError("Receipt exceeds ordered quantity")
            db.execute("INSERT INTO receipts VALUES (?,?,?,?)", (
                receipt.id, receipt.po_id, receipt.po_line_id, receipt.quantity))
        return receipt.model_dump()

    def create_invoice(self, invoice, document_id=None):
        with self.database.transaction() as db:
            cursor = db.execute("""INSERT INTO invoices
                (vendor_id,number,normalized_number,po_id,currency,total_cents,payload)
                VALUES (?,?,?,?,?,?,?)""", (invoice.vendor_id, invoice.number,
                normalize_number(invoice.number), invoice.po_id, invoice.currency,
                cents(invoice.total), invoice.model_dump_json()))
            if document_id is not None:
                db.execute("INSERT INTO invoice_documents VALUES (?,?)", (cursor.lastrowid, document_id))
            return {"id": cursor.lastrowid, **invoice.model_dump(mode="json")}

    def process(self, invoice_id, key):
        with self.database.transaction() as db:
            invoice_row = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if invoice_row is None:
                raise LookupError("Invoice not found")
            cached = db.execute("SELECT result FROM processing_runs WHERE invoice_id=? AND idempotency_key=?",
                                (invoice_id, key)).fetchone()
            if cached:
                return json.loads(cached["result"])
            # An approved invoice is immutable and must never allocate a second time,
            # even if the caller supplies a different retry key.
            approved = db.execute("""SELECT r.result FROM allocations a JOIN processing_runs r ON r.id=a.run_id
                WHERE a.invoice_id=?""", (invoice_id,)).fetchone()
            if approved:
                return json.loads(approved["result"])
            invoice = Invoice.model_validate_json(invoice_row["payload"])
            vendor = db.execute("SELECT * FROM vendors WHERE id=?", (invoice.vendor_id,)).fetchone()
            po = db.execute("SELECT * FROM purchase_orders WHERE id=?", (invoice.po_id,)).fetchone()
            lines = {r["id"]: r for r in db.execute("SELECT * FROM po_lines WHERE po_id=?", (invoice.po_id,))}
            receipts = {r[0]: r[1] for r in db.execute("""SELECT po_line_id,SUM(quantity) FROM receipts
                WHERE po_id=? GROUP BY po_line_id""", (invoice.po_id,))}
            allocated = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM allocations WHERE po_id=?",
                                   (invoice.po_id,)).fetchone()[0]
            used = {r[0]: r[1] for r in db.execute("""SELECT l.po_line_id,SUM(l.quantity)
                FROM allocation_lines l JOIN allocations a ON a.id=l.allocation_id
                WHERE a.po_id=? GROUP BY l.po_line_id""", (invoice.po_id,))}
            duplicate = db.execute("""SELECT 1 FROM invoices WHERE vendor_id=? AND normalized_number=?
                AND id<? LIMIT 1""", (invoice.vendor_id, normalize_number(invoice.number), invoice_id)).fetchone()
            suggestions = [r[0] for r in db.execute("""SELECT p.id FROM purchase_orders p
                LEFT JOIN allocations a ON a.po_id=p.id
                WHERE p.vendor_id=? AND p.currency=? GROUP BY p.id
                HAVING COALESCE(SUM(a.amount_cents),0) < p.total_cents ORDER BY p.id LIMIT 5""",
                (invoice.vendor_id, invoice.currency))]
            result = evaluate(invoice, vendor, po, lines, receipts, allocated, used, bool(duplicate), suggestions)
            result["invoice_id"] = invoice_id
            run = db.execute("INSERT INTO processing_runs(invoice_id,idempotency_key,decision,result) VALUES (?,?,?,?)",
                             (invoice_id, key, result["decision"], "{}"))
            result["run_id"] = run.lastrowid
            db.execute("UPDATE processing_runs SET result=? WHERE id=?", (json.dumps(result), run.lastrowid))
            if result["decision"] == "Approved":
                allocation = db.execute("INSERT INTO allocations(invoice_id,po_id,amount_cents,run_id) VALUES (?,?,?,?)",
                                        (invoice_id, invoice.po_id, cents(invoice.total), run.lastrowid))
                db.executemany("INSERT INTO allocation_lines VALUES (?,?,?)", [
                    (allocation.lastrowid, line.po_line_id, line.quantity) for line in invoice.lines])
            return result

    def po_balance(self, po_id):
        with self.database.connect() as db:
            po = db.execute("SELECT * FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
            if po is None:
                raise LookupError("PO not found")
            allocated = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM allocations WHERE po_id=?", (po_id,)).fetchone()[0]
            return {"po_id": po_id, "total_cents": po["total_cents"], "allocated_cents": allocated,
                    "remaining_cents": po["total_cents"] - allocated}
