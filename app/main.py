import json
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .db import Database
from .schemas import Invoice, ProcessRequest, PurchaseOrder, Receipt, Vendor
from .service import Service


def create_app(db_path=None):
    app = FastAPI(title="Zamp PS-1 Invoice Processing", version="0.1.0")
    service = Service(Database(db_path))
    app.state.service = service

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request: Request, exc):
        return JSONResponse(status_code=409, content={"detail": "Duplicate identifier or invalid reference"})

    @app.exception_handler(LookupError)
    async def not_found(request: Request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid_value(request: Request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        with service.database.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/vendors", status_code=201)
    def vendor(body: Vendor):
        return service.create_vendor(body)

    @app.post("/purchase-orders", status_code=201)
    def po(body: PurchaseOrder):
        return service.create_po(body)

    @app.get("/purchase-orders/{po_id}/balance")
    def balance(po_id: str):
        return service.po_balance(po_id)

    @app.post("/receipts", status_code=201)
    def receipt(body: Receipt):
        return service.create_receipt(body)

    @app.post("/invoices", status_code=201)
    def invoice(body: Invoice):
        return service.create_invoice(body)

    @app.post("/invoices/{invoice_id}/process")
    def process(invoice_id: int, body: ProcessRequest):
        return service.process(invoice_id, body.idempotency_key)

    @app.get("/invoices/{invoice_id}")
    def get_invoice(invoice_id: int):
        with service.database.connect() as db:
            row = db.execute("SELECT payload FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if row is None:
                raise LookupError("Invoice not found")
            runs = [json.loads(r[0]) for r in db.execute(
                "SELECT result FROM processing_runs WHERE invoice_id=? ORDER BY id", (invoice_id,))]
            return {"id": invoice_id, "invoice": json.loads(row[0]), "processing_runs": runs}

    return app


app = create_app()
