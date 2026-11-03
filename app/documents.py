"""Bounded PDF parsing with per-page OCR, without executing embedded PDF content."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import fitz
import pytesseract
from PIL import Image


MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_PIXELS = 12_000_000
MAX_TEXT = 100_000


class DocumentError(ValueError):
    pass


def parse_pdf(data):
    if not data or len(data) > MAX_BYTES:
        raise DocumentError("PDF must be nonempty and at most 10 MiB")
    if not data.startswith(b"%PDF-"):
        raise DocumentError("Invalid PDF signature")
    try:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise DocumentError("Encrypted PDFs are not supported")
            if not 1 <= len(pdf) <= MAX_PAGES:
                raise DocumentError("PDF must contain 1 to 20 pages")
            pages = []
            text_size = 0
            for index, page in enumerate(pdf):
                text = page.get_text("text").strip()
                method = "native"
                # Sparse text layers often contain only a scan watermark/page number.
                if sum(c.isalnum() for c in text) < 30:
                    scale = 200 / 72
                    if page.rect.width * page.rect.height * scale * scale > MAX_PIXELS:
                        raise DocumentError("PDF page exceeds OCR pixel budget")
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    try:
                        text = pytesseract.image_to_string(image, lang="eng", timeout=30).strip()
                    finally:
                        image.close()
                    method = "ocr"
                text_size += len(text)
                if text_size > MAX_TEXT:
                    raise DocumentError("PDF extracted text exceeds character budget")
                pages.append({"page": index + 1, "method": method, "text": text})
            if not any(page["text"] for page in pages):
                raise DocumentError("No readable text found")
            return pages
    except DocumentError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError, pytesseract.TesseractNotFoundError) as exc:
        raise DocumentError("PDF parsing or OCR failed") from exc


class DocumentStore:
    def __init__(self, database, root=None):
        self.database = database
        self.root = Path(root or os.getenv("ZAMP_DOCUMENT_DIR", str(Path(database.path).parent / "documents")))
        self.root.mkdir(parents=True, exist_ok=True)
        with database.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL,
                    pages_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS extraction_runs (
                    id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS invoice_documents (
                    invoice_id INTEGER PRIMARY KEY REFERENCES invoices(id),
                    document_id TEXT NOT NULL REFERENCES documents(id));
            """)

    def save(self, data):
        digest = hashlib.sha256(data).hexdigest()
        with self.database.connect() as db:
            existing = db.execute("SELECT 1 FROM documents WHERE id=?", (digest,)).fetchone()
        if existing:
            return self.get(digest)
        pages = parse_pdf(data)
        # Content-addressed name ignores all user-controlled filename/path components.
        target = self.root / f"{digest}.pdf"
        # Publish only a completely written file, including under concurrent uploads.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise DocumentError("Stored PDF integrity check failed")
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        with self.database.transaction() as db:
            db.execute("INSERT OR IGNORE INTO documents(id,size_bytes,pages_json) VALUES (?,?,?)",
                       (digest, len(data), json.dumps(pages)))
        return self.get(digest)

    def get(self, document_id):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if row is None:
                raise LookupError("Document not found")
            runs = [{"id": r["id"], "provider": r["provider"], "model": r["model"], "status": r["status"],
                     "result": json.loads(r["result"]) if r["result"] else None}
                    for r in db.execute("SELECT * FROM extraction_runs WHERE document_id=? ORDER BY id", (document_id,))]
            return {"id": document_id, "size_bytes": row["size_bytes"], "pages": json.loads(row["pages_json"]),
                    "extraction_runs": runs, "requires_human_review": True}

    def record(self, document_id, provider, model, result):
        with self.database.transaction() as db:
            db.execute("INSERT INTO extraction_runs(document_id,provider,model,status,result) VALUES (?,?,?,?,?)",
                       (document_id, provider, model, "succeeded" if result else "failed",
                        result.model_dump_json() if result else None))
