import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .documents import MAX_BYTES
from .extraction import DEFAULT_GEMINI_MODEL
from .schemas import Receipt
from .workflows import Conflict, Provider, RetryRequest, ReviewRequest, Workflows


def install_workflows(app, service, documents):
    public = app.state.public_demo

    def adapter(provider):
        inner = app.state.adapter_factory(provider)
        return public.adapter(inner) if public else inner

    workflows = Workflows(service, documents, adapter)
    app.state.workflows = workflows

    @asynccontextmanager
    async def lifespan(app):
        def resume(wid):
            if public:
                with public.processing:
                    workflows.execute(wid)
            else:
                workflows.execute(wid)
        try:
            with ThreadPoolExecutor(max_workers=1 if public else 2) as executor:
                for wid in workflows.recover():
                    executor.submit(resume, wid)
                yield
        finally:
            if public:
                public.close()

    app.router.lifespan_context = lifespan

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    # All new endpoints are available both directly and under /api for same-origin UI.
    router = APIRouter()

    @router.get("/configuration")
    def configuration():
        result = {"providers": {p: {"configured": bool(os.getenv(key)) and not (public and p == "openai"), "model": os.getenv(model, default).strip()}
                for p, key, model, default in (("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                                               ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini"))},
                "manual_review_available": True}
        if public:
            result["public_demo"] = public.configuration()
        return result

    @router.get("/master-data")
    def master_data():
        return workflows.master_data()

    @router.post("/receipts", status_code=201)
    def receipt(body: Receipt):
        return service.create_receipt(body)

    @router.get("/samples/{kind}")
    def sample(kind: Literal["native", "scanned", "duplicate", "over-budget"]):
        filename = {"native": "native_invoice.pdf", "scanned": "scanned_invoice.pdf",
                    "duplicate": "duplicate_invoice_variant.pdf", "over-budget": "over_budget_invoice.pdf"}[kind]
        return FileResponse(Path(__file__).resolve().parents[1] / "fixtures" / filename,
                            media_type="application/pdf", filename=f"synthetic_{filename}")

    @router.get("/dashboard")
    def dashboard():
        return workflows.dashboard()

    @router.get("/workflows")
    def history(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                status: Literal["", "Review", "Approved", "Rejected", "failed", "queued", "processing"] = "",
                search: str = Query("", max_length=120)):
        return workflows.history(limit, offset, status, search)

    @router.post("/workflows", status_code=202)
    def submit(background: BackgroundTasks, file: UploadFile = File(...),
               provider: Provider = Form("gemini"), idempotency_key: Annotated[str, Form(min_length=1, max_length=120)] = ""):
        if file.content_type != "application/pdf" or not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(415, "Upload an application/pdf file with a .pdf extension")
        data = file.file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "PDF exceeds 10 MiB")
        if not data:
            raise HTTPException(422, "PDF must not be empty")
        if not idempotency_key.strip():
            raise HTTPException(422, "Idempotency key is required")
        if public:
            filename, idempotency_key = public.upload(data, provider, idempotency_key)
        else:
            filename = file.filename
        run = workflows.submit(data, filename, provider, idempotency_key)
        background.add_task(workflows.execute, run["id"])
        return run

    @router.get("/workflows/{wid}")
    def detail(wid: str):
        return workflows.get(wid)

    @router.get("/workflows/{wid}/pdf")
    def source(wid: str):
        run = workflows.get(wid, include_document=False)
        return FileResponse(workflows.raw / f"{run['digest']}.pdf", media_type="application/pdf",
                            filename=run["filename"], headers={"X-Content-Type-Options": "nosniff"})

    @router.post("/workflows/{wid}/review", status_code=202)
    def review(wid: str, body: ReviewRequest, background: BackgroundTasks):
        if public:
            public.review(workflows, wid, body)
        try:
            run = workflows.review(wid, body)
        except ValueError as exc:
            with workflows.database.transaction() as db:
                workflows.event(db, wid, "validation", "submission_rejected", str(exc))
            raise
        background.add_task(workflows.execute, wid)
        return run

    @router.post("/workflows/{wid}/retry", status_code=202)
    def retry(wid: str, body: RetryRequest, background: BackgroundTasks):
        if public:
            public.retry(workflows, wid, body.provider)
        run = workflows.retry(wid, body.provider)
        background.add_task(workflows.execute, wid)
        return run

    app.include_router(router)
    app.include_router(router, prefix="/api", include_in_schema=False)
