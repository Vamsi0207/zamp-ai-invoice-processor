import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import Database
from .demo_access import DemoAccess, credentials
from .documents import DocumentStore, MAX_BYTES
from .extraction import AIAdapter, ExtractRequest, ProviderError, ProviderNotConfigured
from .schemas import Invoice, ProcessRequest, PurchaseOrder, Receipt, Vendor
from .service import Service
from .workflow_api import install_workflows


def create_app(db_path=None):
    demo_credentials = credentials()  # Validate before opening any application data.
    app = FastAPI(title="Zamp PS-1 Invoice Processing", version="0.1.0")
    if demo_credentials:
        app.add_middleware(DemoAccess, expected=demo_credentials)
    service = Service(Database(db_path))
    app.state.service = service
    documents = DocumentStore(service.database)
    app.state.adapter_factory = AIAdapter

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
            source = db.execute("SELECT document_id FROM invoice_documents WHERE invoice_id=?", (invoice_id,)).fetchone()
            return {"id": invoice_id, "invoice": json.loads(row[0]), "processing_runs": runs,
                    "source_document_id": source[0] if source else None}

    @app.post("/documents", status_code=201)
    def upload(file: UploadFile = File(...)):
        if file.content_type != "application/pdf" or not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(415, "Upload must be an application/pdf file with a .pdf extension")
        data = file.file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "PDF exceeds 10 MiB")
        return documents.save(data)

    @app.get("/documents/{document_id}")
    def document(document_id: str):
        return documents.get(document_id)

    @app.post("/documents/{document_id}/extract")
    def extract(document_id: str, body: ExtractRequest):
        document = documents.get(document_id)
        try:
            adapter = app.state.adapter_factory(body.provider)
            result = adapter.extract(document["pages"])
        except ProviderNotConfigured as exc:
            raise HTTPException(503, str(exc), headers={"X-Provider-Error-Code": exc.code}) from None
        except ProviderError as exc:
            documents.record(document_id, body.provider, adapter.model, None)
            raise HTTPException(502, str(exc), headers={"X-Provider-Error-Code": exc.code}) from None
        documents.record(document_id, body.provider, adapter.model, result)
        return documents.get(document_id)

    @app.post("/documents/{document_id}/invoices", status_code=201)
    def reviewed_invoice(document_id: str, body: Invoice):
        documents.get(document_id)
        # Explicit submission of the reviewed canonical invoice, not automatic AI mapping.
        return service.create_invoice(body, document_id=document_id)

    install_workflows(app, service, documents)
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
