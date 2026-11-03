from pathlib import Path

import fitz
import pytest

from app.documents import DocumentError, MAX_BYTES, parse_pdf


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def upload(client, name="native_invoice.pdf"):
    return client.post("/documents", files={"file": (name, (FIXTURES / name).read_bytes(), "application/pdf")})


def test_native_pdf_upload_and_persistence(client):
    response = upload(client)
    assert response.status_code == 201, response.text
    document = response.json()
    assert len(document["id"]) == 64
    assert document["pages"][0]["method"] == "native"
    assert "TOTAL DUE: USD 400.00" in document["pages"][0]["text"]
    assert document["requires_human_review"] is True
    assert client.get(f"/documents/{document['id']}").json() == document
    assert upload(client).json() == document
    assert client.get("/documents/missing").status_code == 404


def test_real_scanned_pdf_ocr(client):
    response = upload(client, "scanned_invoice.pdf")
    assert response.status_code == 201, response.text
    page = response.json()["pages"][0]
    assert page["method"] == "ocr"
    assert "400.00" in page["text"]
    assert "SYN-001" in page["text"]
    assert "OFFICE SUPPLY" in page["text"]


@pytest.mark.parametrize("name,mime,content,status", [
    ("invoice.txt", "application/pdf", b"%PDF-test", 415),
    ("invoice.pdf", "text/plain", b"%PDF-test", 415),
    ("invoice.pdf", "application/pdf", b"not a pdf", 422),
    ("invoice.pdf", "application/pdf", b"", 422),
    ("invoice.pdf", "application/pdf", b"%PDF-broken", 422),
    ("invoice.pdf", "application/pdf", b"x" * (MAX_BYTES + 1), 413),
], ids=["wrong-extension", "wrong-mime", "invalid-signature", "empty", "corrupt", "oversized"])
def test_upload_validation(client, name, mime, content, status):
    assert client.post("/documents", files={"file": (name, content, mime)}).status_code == status


def test_filename_cannot_escape_storage(client):
    document = client.post("/documents", files={"file": ("../../escape.pdf",
        (FIXTURES / "native_invoice.pdf").read_bytes(), "application/pdf")}).json()
    root = Path(client.app.state.service.database.path).parent
    assert (root / "documents" / f"{document['id']}.pdf").exists()
    assert not (root / "escape.pdf").exists()


def test_encrypted_pdf_rejected():
    with fitz.open(FIXTURES / "native_invoice.pdf") as pdf:
        data = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="test")
    with pytest.raises(DocumentError, match="Encrypted"):
        parse_pdf(data)


def test_page_limit():
    with fitz.open() as pdf:
        for _ in range(21):
            pdf.new_page()
        data = pdf.tobytes()
    with pytest.raises(DocumentError, match="20 pages"):
        parse_pdf(data)


def test_pixel_budget():
    with fitz.open() as pdf:
        pdf.new_page(width=4000, height=4000)
        data = pdf.tobytes()
    with pytest.raises(DocumentError, match="pixel budget"):
        parse_pdf(data)


def test_mixed_native_scanned_pages():
    with fitz.open() as pdf, fitz.open(FIXTURES / "native_invoice.pdf") as native, fitz.open(FIXTURES / "scanned_invoice.pdf") as scan:
        pdf.insert_pdf(native)
        pdf.insert_pdf(scan)
        data = pdf.tobytes()
    pages = parse_pdf(data)
    assert [p["page"] for p in pages] == [1, 2]
    assert [p["method"] for p in pages] == ["native", "ocr"]


def test_no_text_rejected(monkeypatch):
    monkeypatch.setattr("app.documents.resolve_tesseract", lambda: "test-tesseract")
    monkeypatch.setattr("app.documents.pytesseract.image_to_string", lambda *a, **k: "")
    with fitz.open() as pdf:
        pdf.new_page()
        data = pdf.tobytes()
    with pytest.raises(DocumentError, match="No readable"):
        parse_pdf(data)


def test_ocr_unavailable_returns_validation_error(client, monkeypatch):
    import pytesseract
    def missing(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr("app.documents.resolve_tesseract", lambda: "test-tesseract")
    monkeypatch.setattr("app.documents.pytesseract.image_to_string", missing)
    response = upload(client, "scanned_invoice.pdf")
    assert response.status_code == 422
    assert "Tesseract OCR is unavailable" in response.json()["detail"]
    assert "TESSERACT_CMD" in response.json()["detail"]


def test_duplicate_upload_does_not_reparse(client, monkeypatch):
    first = upload(client).json()
    def unexpected(data):
        raise AssertionError("Should reuse stored content hash")
    monkeypatch.setattr("app.documents.parse_pdf", unexpected)
    assert upload(client).json() == first


def test_document_store_reopen(client):
    from app.documents import DocumentStore
    first = upload(client).json()
    store = DocumentStore(client.app.state.service.database)
    assert store.get(first["id"]) == first


def test_ocr_timeout_is_explicit(client, monkeypatch):
    def timeout(*args, **kwargs):
        raise RuntimeError("Tesseract process timeout")
    monkeypatch.setattr("app.documents.resolve_tesseract", lambda: "test-tesseract")
    monkeypatch.setattr("app.documents.pytesseract.image_to_string", timeout)
    assert upload(client, "scanned_invoice.pdf").status_code == 422


def test_native_text_limit(monkeypatch):
    monkeypatch.setattr("app.documents.MAX_TEXT", 5)
    with pytest.raises(DocumentError, match="character budget"):
        parse_pdf((FIXTURES / "native_invoice.pdf").read_bytes())
