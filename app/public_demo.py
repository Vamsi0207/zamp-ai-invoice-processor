"""Synthetic-only public boundary and durable global budgets; no financial policy."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import re
import sqlite3
import threading
import time

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from .db import Database
from .extraction import ProviderError
from .schemas import Invoice


ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "demo-reviewer"
NOTE = "Synthetic public demo confirmation"
LIMITS = {  # default, maximum; every budget must be positive and bounded
    "AI_PER_MINUTE": (2, 10), "AI_PER_DAY": (20, 100), "AI_TOTAL": (100, 1000),
    "UPLOADS_PER_MINUTE": (6, 30), "WRITES_PER_MINUTE": (20, 60),
    "WRITES_TOTAL": (500, 10000), "READS_PER_MINUTE": (600, 1200),
    "MAX_RETRIES": (3, 5), "MAX_BODY_BYTES": (1048576, 10485760 + 65536),
}


def enabled():
    value = os.getenv("ZAMP_PUBLIC_DEMO", "0")
    if value not in {"0", "1"}:
        raise RuntimeError("ZAMP_PUBLIC_DEMO must be 0 or 1")
    return value == "1"


def settings():
    result = {}
    for key, (default, maximum) in LIMITS.items():
        try:
            value = int(os.getenv("ZAMP_DEMO_" + key, str(default)))
        except ValueError:
            raise RuntimeError("Invalid public-demo limit configuration") from None
        if not 1 <= value <= maximum:
            raise RuntimeError("Public-demo limits must be positive and within documented safe maxima")
        result[key] = value
    return result


def samples():
    data = json.loads((ROOT / "fixtures/synthetic_dataset.json").read_text())
    standard = data["invoices"][0]
    over = {**standard, "number": "SYN-002", "total": "700.00",
            "lines": [{**standard["lines"][0], "quantity": 7}]}
    names = {"native_invoice.pdf": standard, "scanned_invoice.pdf": standard,
             "duplicate_invoice_variant.pdf": standard, "over_budget_invoice.pdf": over}
    return {hashlib.sha256((ROOT / "fixtures" / name).read_bytes()).hexdigest():
            (name, Invoice.model_validate(invoice)) for name, invoice in names.items()}


def mark_new_workspace(path, document_root):
    """Called ONLY after exclusive database creation and successful demo seed."""
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE public_demo_workspace (version INTEGER PRIMARY KEY, document_root TEXT NOT NULL)")
        db.execute("INSERT INTO public_demo_workspace VALUES (1,?)", (str(Path(document_root).resolve()),))
        db.execute("CREATE TABLE public_demo_budgets (name TEXT PRIMARY KEY, window INTEGER NOT NULL, used INTEGER NOT NULL)")


class DemoLimit(ProviderError):
    def __init__(self):
        super().__init__("Shared demo usage limit reached; try later or use manual review", code="PUBLIC_DEMO_LIMIT", http_status=429, retryable=True)


class PublicDemo:
    def __init__(self, path, document_root):
        self.limits, self.samples = settings(), samples()
        self.processing = threading.BoundedSemaphore(1)
        self.ai = threading.BoundedSemaphore(1)
        self.lock = None
        try:
            # Read-only verification first: never initialize or expose an old private DB.
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                marker = db.execute("SELECT version,document_root FROM public_demo_workspace").fetchall()
                if marker != [(1, str(Path(document_root).resolve()))]:
                    raise ValueError("workspace marker")
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                # A previously public DB might since have been used privately.
                # Check bounded row counts before loading anything into memory.
                maxima = {"vendors": 1, "purchase_orders": 1, "po_lines": 1, "receipts": 1,
                          "invoices": 4, "documents": 4, "workflows": 4, "workflow_keys": 10000,
                          "workflow_events": 1000, "extraction_runs": 20, "public_demo_budgets": len(LIMITS)}
                for table, maximum in maxima.items():
                    if table in tables and db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > maximum:
                        raise ValueError("non-demo workspace size")
                db.execute("SELECT name,window,used FROM public_demo_budgets").fetchall()
                data = json.loads((ROOT / "fixtures/synthetic_dataset.json").read_text())
                vendor, po, receipt = data["vendor"], data["purchase_order"], data["receipt"]
                expected_rows = [
                    ("SELECT id,name,active FROM vendors", [(vendor["id"], vendor["name"], 1)]),
                    ("SELECT id,vendor_id,currency,total_cents,tolerance_enabled FROM purchase_orders", [(po["id"], po["vendor_id"], po["currency"], 100000, 0)]),
                    ("SELECT po_id,id,description,quantity,unit_price_cents FROM po_lines", [(po["id"], "L1", "Office chairs", 10, 10000)]),
                    ("SELECT id,po_id,po_line_id,quantity FROM receipts", [(receipt["id"], po["id"], "L1", 10)]),
                ]
                for query, expected in expected_rows:
                    if db.execute(query).fetchall() != expected:
                        raise ValueError("non-demo master data")
                allowed = [item[1].model_dump() for item in self.samples.values()]
                for row in db.execute("SELECT payload FROM invoices"):
                    if Invoice.model_validate_json(row[0]).model_dump() not in allowed:
                        raise ValueError("non-demo invoice")
                if "documents" in tables:
                    if any(row[0] not in self.samples for row in db.execute("SELECT id FROM documents")):
                        raise ValueError("non-demo document")
                if "workflows" in tables:
                    for digest, filename, provider in db.execute("SELECT digest,filename,provider FROM workflows"):
                        if digest not in self.samples or filename != self.samples[digest][0] or provider not in {"gemini", "manual"}:
                            raise ValueError("non-demo workflow")
                if "workflow_keys" in tables:
                    if any(not re.fullmatch(r"public:[a-f0-9]{64}", row[0]) for row in db.execute("SELECT key FROM workflow_keys")):
                        raise ValueError("non-demo idempotency metadata")
                if "workflow_events" in tables:
                    for row in db.execute("SELECT detail FROM workflow_events WHERE status='confirmed'"):
                        event = json.loads(row[0])
                        if event["reviewer"] != REVIEWER or event["note"] != NOTE:
                            raise ValueError("non-demo audit identity")
            # A second worker/process must fail, never multiply in-memory concurrency.
            self.lock = open(str(path) + ".public.lock", "a+b")
            if os.name == "nt":
                import msvcrt
                self.lock.seek(0)
                self.lock.write(b"0")
                self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.database = Database(path)
            self.budget([], consume=False)  # Verify durable limiter access now.
        except Exception:
            self.close()
            raise RuntimeError("Public demo requires a new isolated synthetic workspace, valid budgets, and exactly one process; existing data was not reset") from None

    def close(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def budget(self, names, consume=True):
        try:
            with self.database.transaction() as db:
                updates = []
                for name, seconds in names:
                    window = int(time.time()) // seconds if seconds else 0
                    row = db.execute("SELECT window,used FROM public_demo_budgets WHERE name=?", (name,)).fetchone()
                    if row and (not all(isinstance(v, int) and v >= 0 for v in row)):
                        raise sqlite3.DatabaseError("Invalid limiter state")
                    used = row[1] if row and window <= row[0] else 0
                    window = max(window, row[0]) if row else window
                    if used >= self.limits[name]:
                        raise DemoLimit()
                    updates.append((name, window, used + 1))
                if consume:
                    db.executemany("INSERT INTO public_demo_budgets VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET window=excluded.window,used=excluded.used", updates)
        except sqlite3.Error:
            raise ProviderError("Public demo usage controls unavailable; processing is disabled", code="DEMO_GUARD_UNAVAILABLE", http_status=503) from None

    def ai_available(self):
        self.budget([("AI_PER_MINUTE", 60), ("AI_PER_DAY", 86400), ("AI_TOTAL", 0)], consume=False)

    def adapter(self, inner):
        guard = self

        class LimitedAdapter:
            model = inner.model

            def extract(self, pages):
                if not guard.ai.acquire(blocking=False):
                    raise DemoLimit()
                try:
                    guard.budget([("AI_PER_MINUTE", 60), ("AI_PER_DAY", 86400), ("AI_TOTAL", 0)])
                    return inner.extract(pages)  # Original Pydantic/evidence checks unchanged.
                finally:
                    guard.ai.release()
        return LimitedAdapter()

    def upload(self, data, provider, key):
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.samples:
            raise HTTPException(403, "Public demo accepts only the unmodified bundled synthetic PDF samples")
        if provider not in {"manual", "gemini"}:
            raise HTTPException(403, "Public demo supports Gemini or manual review only")
        # Reused runs do not incur AI admission or spend another provider request.
        with self.database.connect() as db:
            exists = db.execute("SELECT 1 FROM workflows WHERE digest=?", (digest,)).fetchone()
        if provider == "gemini" and not exists:
            self.ai_available()
        return self.samples[digest][0], "public:" + hashlib.sha256(key.encode()).hexdigest()

    def review(self, workflows, wid, body):
        run = workflows.get(wid, include_document=False)
        expected = self.samples[run["digest"]][1]
        # No personal free text or arbitrary invoice data enters the shared audit.
        if (body.invoice.model_dump() != expected.model_dump() or body.reviewer != REVIEWER or body.note != NOTE):
            raise HTTPException(403, "Use the printed synthetic invoice values and the fixed public-demo signoff")

    def retry(self, workflows, wid, provider):
        run = workflows.get(wid, include_document=False)
        if provider not in {None, "manual", "gemini"}:
            raise HTTPException(403, "Public demo supports Gemini or manual review only")
        if run["status"] in {"Approved", "Rejected", "queued", "processing"}:
            return
        if run["attempt"] >= self.limits["MAX_RETRIES"]:
            raise DemoLimit()
        if not run["invoice_id"] and (provider or run["provider"]) == "gemini":
            self.ai_available()

    def configuration(self):
        return {"enabled": True, "reviewer": REVIEWER, "note": NOTE,
                "message": "Public synthetic demo · shared temporary state · upload only the supplied samples; never personal documents",
                "limits": self.limits}


class PublicBoundary:
    def __init__(self, app, guard):
        self.app, self.guard = app, guard

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if path == "/health" and method == "GET":
            return await self.app(scope, receive, send)
        locked = False
        try:
            if len(scope.get("query_string", b"")) > 2048:
                raise HTTPException(413, "Demo request exceeds size limit")
            if method in {"GET", "HEAD"}:
                if path != "/" and not path.startswith("/assets/"):
                    allowed = r"/(?:api/)?(?:configuration|master-data|dashboard|samples/(?:native|scanned|duplicate|over-budget)|workflows(?:/[a-f0-9]{32}(?:/pdf)?)?)"
                    if not re.fullmatch(allowed, path):
                        raise HTTPException(403, "Operation unavailable in the public demo")
                    self.guard.budget([("READS_PER_MINUTE", 60)])
            else:
                if method != "POST" or not re.fullmatch(r"/(?:api/)?workflows(?:/[a-f0-9]{32}/(?:review|retry))?", path):
                    raise HTTPException(403, "Public demo master data, receipts and legacy write APIs are read-only")
                headers = dict(scope["headers"])
                if b"origin" in headers:
                    try:
                        origin = urlsplit(headers[b"origin"].decode("ascii"))
                        same = origin.scheme in {"http", "https"} and origin.netloc.lower() == headers.get(b"host", b"").decode("ascii").lower()
                    except (ValueError, UnicodeError):
                        same = False
                    if not same:
                        raise HTTPException(403, "Cross-origin request forbidden")
                if not self.guard.processing.acquire(blocking=False):
                    raise DemoLimit()
                locked = True
                names = [("WRITES_PER_MINUTE", 60), ("WRITES_TOTAL", 0)]
                if path in {"/api/workflows", "/workflows"}:
                    names.append(("UPLOADS_PER_MINUTE", 60))
                self.guard.budget(names)
                # Bound the complete HTTP body BEFORE multipart parsing/spooling.
                request = Request(scope, receive)
                limit = self.guard.limits["MAX_BODY_BYTES"] if path.endswith("workflows") else 65536

                async def body():
                    chunks = bytearray()
                    async for chunk in request.stream():
                        if len(chunks) + len(chunk) > limit:
                            raise HTTPException(413, "Demo request exceeds size limit")
                        chunks.extend(chunk)
                    return bytes(chunks)
                try:
                    data = await asyncio.wait_for(body(), timeout=15)
                except asyncio.TimeoutError:
                    raise HTTPException(408, "Demo upload timed out") from None

                async def replay():
                    return {"type": "http.request", "body": data, "more_body": False}
                if path.endswith("workflows"):
                    # Reject multipart floods before FastAPI creates UploadFile objects.
                    async with Request(scope, replay).form(max_files=1, max_fields=2, max_part_size=65536):
                        pass
                receive = replay

            async def no_cache(message):
                if message["type"] == "http.response.start":
                    message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                    message["headers"].append((b"cache-control", b"no-store"))
                await send(message)
            await self.app(scope, receive, no_cache)
        except (HTTPException, ProviderError) as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else exc.http_status or 503
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            headers = {"Cache-Control": "no-store"}
            if status == 429:
                headers["Retry-After"] = "60"
            await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)
        finally:
            if locked:
                self.guard.processing.release()
