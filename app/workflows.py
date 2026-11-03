"""Persistent orchestration. Financial decisions remain exclusively in Service.process."""
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .documents import DocumentError
from .extraction import ProviderError, ProviderNotConfigured
from .schemas import Identifier, Invoice, Model


STAGES = ("upload", "pdf_extraction", "ai_extraction", "matching", "validation", "decision")
Provider = Literal["gemini", "openai", "manual"]


class Conflict(ValueError):
    pass


class ReviewRequest(Model):
    invoice: Invoice
    reviewer: Identifier
    note: str = Field(min_length=1, max_length=2000)
    confirmed: bool

    @model_validator(mode="after")
    def confirmation(self):
        if not self.confirmed:
            raise ValueError("Explicit human confirmation is required")
        return self


class RetryRequest(Model):
    provider: Provider | None = None


class Workflows:
    def __init__(self, service, documents, adapter_factory):
        self.service, self.documents, self.adapter_factory = service, documents, adapter_factory
        self.database = service.database
        self.raw = documents.root / "incoming"
        self.raw.mkdir(exist_ok=True)
        with self.database.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
              id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
              provider TEXT NOT NULL, status TEXT NOT NULL, stages TEXT NOT NULL,
              document_id TEXT REFERENCES documents(id), invoice_id INTEGER REFERENCES invoices(id),
              extraction TEXT, draft TEXT, matching TEXT, decision TEXT, error TEXT,
              attempt INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS workflow_keys (
              key TEXT PRIMARY KEY, digest TEXT NOT NULL, workflow_id TEXT NOT NULL REFERENCES workflows(id));
            CREATE TABLE IF NOT EXISTS workflow_events (
              id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id),
              stage TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)

    def event(self, db, wid, stage, status, detail):
        db.execute("INSERT INTO workflow_events(workflow_id,stage,status,detail) VALUES (?,?,?,?)",
                   (wid, stage, status, detail))

    def change(self, wid, stage=None, stage_status=None, detail="", **fields):
        allowed = {"status", "document_id", "extraction", "draft", "matching", "decision", "error"}
        if not set(fields) <= allowed:
            raise ValueError("Unsupported workflow update")
        with self.database.transaction() as db:
            if stage:
                stages = json.loads(db.execute("SELECT stages FROM workflows WHERE id=?", (wid,)).fetchone()[0])
                stages[stage] = {"status": stage_status, "detail": detail}
                fields["stages"] = json.dumps(stages)
                self.event(db, wid, stage, stage_status, detail)
            for key in ("extraction", "draft", "matching", "decision", "error"):
                if key in fields and fields[key] is not None:
                    fields[key] = json.dumps(fields[key])
            if fields:
                db.execute("UPDATE workflows SET " + ",".join(f"{key}=?" for key in fields) +
                           ",updated_at=CURRENT_TIMESTAMP WHERE id=?", (*fields.values(), wid))

    def get(self, wid, include_document=True):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
            if row is None:
                raise LookupError("Workflow not found")
            result = dict(row)
            for key in ("stages", "extraction", "draft", "matching", "decision", "error"):
                result[key] = json.loads(result[key]) if result[key] else None
            result["events"] = [dict(r) for r in db.execute(
                "SELECT * FROM workflow_events WHERE workflow_id=? ORDER BY id", (wid,))]
        if include_document:
            result["document"] = self.documents.get(result["document_id"]) if result["document_id"] else None
        return result

    def submit(self, data, filename, provider, key):
        digest = hashlib.sha256(data).hexdigest()
        # Write raw bytes durably before publishing a queued DB record.
        target = self.raw / f"{digest}.pdf"
        temporary = self.raw / f"{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise DocumentError("Incoming PDF integrity check failed")
        finally:
            temporary.unlink(missing_ok=True)
        with self.database.transaction() as db:
            existing_key = db.execute("SELECT * FROM workflow_keys WHERE key=?", (key,)).fetchone()
            if existing_key and existing_key["digest"] != digest:
                raise Conflict("Idempotency key was already used for a different document")
            existing = db.execute("SELECT id FROM workflows WHERE digest=?", (digest,)).fetchone()
            if existing:
                wid = existing[0]
            else:
                wid = uuid.uuid4().hex
                stages = {s: {"status": "pending", "detail": "Waiting"} for s in STAGES}
                stages["upload"] = {"status": "completed", "detail": "PDF bytes stored durably"}
                safe_name = Path(filename.replace("\\", "/")).name[:200]
                db.execute("INSERT INTO workflows(id,digest,filename,provider,status,stages) VALUES (?,?,?,?,?,?)",
                           (wid, digest, safe_name, provider, "queued", json.dumps(stages)))
                self.event(db, wid, "upload", "completed", "PDF bytes stored durably")
            db.execute("INSERT OR IGNORE INTO workflow_keys VALUES (?,?,?)", (key, digest, wid))
        return self.get(wid)

    def master_data(self):
        with self.database.connect() as db:
            vendors = [dict(v) for v in db.execute("SELECT * FROM vendors ORDER BY name,id")]
            orders = []
            for row in db.execute("SELECT * FROM purchase_orders ORDER BY id"):
                po = dict(row)
                po["lines"] = [dict(l) for l in db.execute("SELECT * FROM po_lines WHERE po_id=? ORDER BY id", (po["id"],))]
                for line in po["lines"]:
                    line["received_quantity"] = db.execute("SELECT COALESCE(SUM(quantity),0) FROM receipts WHERE po_id=? AND po_line_id=?",
                                                          (po["id"], line["id"])).fetchone()[0]
                po.update(self.service.po_balance(po["id"]))
                orders.append(po)
        return {"vendors": vendors, "purchase_orders": orders}

    def match(self, extraction):
        data = self.master_data()
        facts = extraction["invoice"] if extraction else {}
        vendors = [v for v in data["vendors"] if facts.get("vendor_reference") == v["id"]]
        if not vendors and facts.get("vendor_name"):
            vendors = [v for v in data["vendors"] if v["name"].casefold() == facts["vendor_name"].casefold()]
        vendor = vendors[0] if len(vendors) == 1 else None
        po = next((p for p in data["purchase_orders"] if p["id"] == facts.get("po_number") and vendor
                   and p["vendor_id"] == vendor["id"]), None)
        issues = ["HUMAN_CONFIRMATION_REQUIRED"]
        if not vendor:
            issues.append("VENDOR_MAPPING_REQUIRED")
        if not po:
            issues.append("PO_MAPPING_REQUIRED")
        draft = {"vendor_id": vendor["id"] if vendor else "", "po_id": po["id"] if po else None,
                 "number": facts.get("invoice_number") or "", "currency": facts.get("currency") or "",
                 **{k: facts.get(k) for k in ("total", "tax", "shipping", "discount")}, "lines": []}
        for line in facts.get("lines", []):
            reference = line.get("line_reference")
            mapped = next((l for l in po["lines"] if l["id"] == reference), None) if po else None
            if not mapped:
                issues.append("PO_LINE_MAPPING_REQUIRED")
            draft["lines"].append({"po_line_id": mapped["id"] if mapped else "",
                **{k: line.get(k) for k in ("description", "quantity", "unit_price")}})
        if any(draft[k] is None or draft[k] == "" for k in ("number", "currency", "total", "tax", "shipping", "discount")) or not draft["lines"]:
            issues.append("MISSING_FIELDS")
        suggestions = [p["id"] for p in data["purchase_orders"] if vendor and p["vendor_id"] == vendor["id"]
                       and (not facts.get("currency") or p["currency"] == facts["currency"])]
        return draft, {"issues": sorted(set(issues)), "suggested_po_ids": suggestions,
                       "explanation": "Only exact existing references or a unique exact vendor name are prefilled. Suggestions are not selections."}

    def execute(self, wid):
        # Compare-and-set claim makes duplicate task scheduling harmless.
        with self.database.transaction() as db:
            claimed = db.execute("UPDATE workflows SET status='processing',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'", (wid,))
            if claimed.rowcount != 1:
                return
        stage = "decision"
        try:
            run = self.get(wid)
            if not run["invoice_id"]:
                stage = "pdf_extraction"
                self.change(wid, stage, "running", "Reading PDF text; OCR if needed")
                data = (self.raw / f"{run['digest']}.pdf").read_bytes()
                if hashlib.sha256(data).hexdigest() != run["digest"]:
                    raise DocumentError("Incoming PDF integrity check failed")
                document = self.documents.save(data)
                self.change(wid, stage, "completed", f"Extracted {len(document['pages'])} page(s)", document_id=document["id"])
                stage = "ai_extraction"
                extraction = None
                if run["provider"] == "manual":
                    self.change(wid, stage, "skipped", "Manual review selected; no AI request made")
                else:
                    self.change(wid, stage, "running", "Requesting structured, evidence-backed extraction")
                    adapter = self.adapter_factory(run["provider"])
                    try:
                        result = adapter.extract(document["pages"])
                    except ProviderError:
                        self.documents.record(document["id"], run["provider"], adapter.model, None)
                        raise
                    extraction = result.model_dump()
                    self.documents.record(document["id"], run["provider"], adapter.model, result)
                    self.change(wid, stage, "completed", "Extracted fields and validated source quotes", extraction=extraction)
                stage = "matching"
                self.change(wid, stage, "running", "Looking up existing vendors, POs and line references")
                draft, matching = self.match(extraction)
                self.change(wid, stage, "completed", "Master-data matching recorded", draft=draft, matching=matching)
                self.change(wid, "validation", "needs_review", "Confirm source fields and resolve mappings before financial processing", status="Review")
                return
            self.change(wid, "validation", "completed", "Confirmed invoice; financial checks run with current PO balances")
            stage = "decision"
            self.change(wid, stage, "running", "Running deterministic checks and atomic allocation")
            result = self.service.process(run["invoice_id"], f"workflow:{wid}:{run['attempt']}")
            self.change(wid, stage, "completed", "; ".join(result["reasons"]), status=result["decision"], decision=result, error=None)
        except Exception as exc:
            if isinstance(exc, ProviderNotConfigured):
                code, detail = "PROVIDER_NOT_CONFIGURED", str(exc)
            elif isinstance(exc, ProviderError):
                code, detail = exc.code, str(exc)
            elif isinstance(exc, DocumentError):
                code, detail = "PDF_ERROR", str(exc)
            else:
                code, detail = "INTERNAL_ERROR", f"Stage interrupted by {type(exc).__name__}; retry is safe"
            error = {"code": code, "stage": stage, "message": detail}
            if isinstance(exc, ProviderError):
                error.update(exc.details())
            self.change(wid, stage, "failed", detail, status="failed", error=error)

    def review(self, wid, request):
        with self.database.transaction() as db:
            row = db.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
            if row is None:
                raise LookupError("Workflow not found")
            if row["invoice_id"]:
                original = db.execute("SELECT payload FROM invoices WHERE id=?", (row["invoice_id"],)).fetchone()[0]
                if original != request.invoice.model_dump_json():
                    raise Conflict("A confirmed invoice is immutable; this workflow already has a different submission")
                return self.get(wid)
            if row["status"] != "Review":
                raise Conflict("Only a workflow awaiting review can be confirmed")
            invoice = request.invoice
            if not db.execute("SELECT 1 FROM vendors WHERE id=?", (invoice.vendor_id,)).fetchone():
                raise ValueError("Select an existing vendor; identifiers cannot be invented")
            if not invoice.po_id or not db.execute("SELECT 1 FROM purchase_orders WHERE id=?", (invoice.po_id,)).fetchone():
                raise ValueError("Select an existing purchase order before confirming")
            for line in invoice.lines:
                if not db.execute("SELECT 1 FROM po_lines WHERE po_id=? AND id=?", (invoice.po_id, line.po_line_id)).fetchone():
                    raise ValueError("Select existing PO line references before confirming")
            saved = self.service.create_invoice(invoice, row["document_id"], db=db)
            db.execute("UPDATE workflows SET invoice_id=?,draft=?,status='queued',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (saved["id"], invoice.model_dump_json(), wid))
            self.event(db, wid, "validation", "confirmed", json.dumps({"reviewer": request.reviewer, "note": request.note,
                       "invoice": invoice.model_dump(mode="json")}))
        return self.get(wid)

    def retry(self, wid, provider=None):
        with self.database.transaction() as db:
            row = db.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
            if row is None:
                raise LookupError("Workflow not found")
            if row["status"] in ("Approved", "Rejected", "queued", "processing"):
                return self.get(wid)
            if row["status"] == "Review" and not row["invoice_id"]:
                raise Conflict("Resolve the review form rather than retrying an unconfirmed invoice")
            if provider and row["invoice_id"]:
                raise Conflict("A confirmed invoice cannot change extraction provider")
            stages = json.loads(row["stages"])
            for name in STAGES[1:]:
                if not row["invoice_id"] or name == "decision":
                    stages[name] = {"status": "pending", "detail": "Retry queued"}
            db.execute("UPDATE workflows SET status='queued',provider=?,attempt=attempt+1,stages=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (provider or row["provider"], json.dumps(stages), wid))
            self.event(db, wid, "workflow", "queued", "Explicit retry requested")
        return self.get(wid)

    def recover(self):
        # One application process owns background execution; interrupted work is visible,
        # never silently stuck or blindly recharged to the provider on restart.
        with self.database.transaction() as db:
            rows = db.execute("SELECT id,stages FROM workflows WHERE status='processing'").fetchall()
            for row in rows:
                stages = json.loads(row["stages"])
                stage = next((s for s in STAGES if stages[s]["status"] == "running"), "decision")
                stages[stage] = {"status": "failed", "detail": "Server restarted; explicit retry required"}
                error = {"code": "INTERRUPTED", "stage": stage, "message": "Server restarted; retry is safe"}
                db.execute("UPDATE workflows SET status='failed',stages=?,error=? WHERE id=?",
                           (json.dumps(stages), json.dumps(error), row["id"]))
                self.event(db, row["id"], stage, "failed", error["message"])
            return [r[0] for r in db.execute("SELECT id FROM workflows WHERE status='queued'")]

    def history(self, limit=50, offset=0, status=None, search=""):
        clauses, values = [], []
        if status:
            clauses.append("status=?")
            values.append(status)
        if search:
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append("(filename LIKE ? ESCAPE '\\' OR json_extract(draft,'$.number') LIKE ? ESCAPE '\\')")
            values.extend((pattern, pattern))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.database.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM workflows" + where + " ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?", (*values, limit, offset))]
            total = db.execute("SELECT COUNT(*) FROM workflows" + where, values).fetchone()[0]
        return {"items": [self.get(wid, include_document=False) for wid in ids], "total": total}

    def dashboard(self):
        with self.database.connect() as db:
            counts = {r[0]: r[1] for r in db.execute("SELECT status,COUNT(*) FROM workflows GROUP BY status")}
            invoices = db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        return {"total": sum(counts.values()), "invoice_count": invoices, "counts": counts,
                "recent": self.history(8)["items"]}
