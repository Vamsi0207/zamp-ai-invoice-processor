import os
from pathlib import Path

import pytest
import pytesseract

from app.documents import DocumentError, ocr_image, parse_pdf, resolve_tesseract
from test_documents import FIXTURES, upload
from test_workflows import upload_run


def executable(directory):
    directory.mkdir(parents=True)
    path = directory / ("tesseract.exe" if os.name == "nt" else "tesseract")
    # Discovery tests only: this placeholder is never executed or treated as real OCR.
    path.write_bytes(b"placeholder")
    path.chmod(0o755)
    return path


def test_discover_tesseract_on_path(tmp_path, monkeypatch):
    path = executable(tmp_path / "bin")
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setenv("PATH", str(path.parent))
    assert Path(resolve_tesseract()).resolve() == path.resolve()


def test_configured_executable_with_spaces_overrides_path(tmp_path, monkeypatch):
    path = executable(tmp_path / "Program Files" / "Tesseract-OCR")
    monkeypatch.setenv("TESSERACT_CMD", str(path))
    monkeypatch.setenv("PATH", "")
    assert Path(resolve_tesseract()).resolve() == path.resolve()


def test_missing_explicit_executable_does_not_fall_back(tmp_path, monkeypatch):
    available = executable(tmp_path / "available")
    monkeypatch.setenv("PATH", str(available.parent))
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "missing" / "tesseract.exe"))
    with pytest.raises(DocumentError, match="TESSERACT_CMD"):
        resolve_tesseract()


def test_missing_path_executable_has_setup_diagnostic(monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr("app.documents.shutil.which", lambda command: None)
    with pytest.raises(DocumentError, match="Install Tesseract 5.*English"):
        resolve_tesseract()


def test_configured_command_is_used_and_restored(monkeypatch):
    previous = pytesseract.pytesseract.tesseract_cmd
    monkeypatch.setattr("app.documents.resolve_tesseract", lambda: "configured executable")
    sentinel = object()

    def recognize(image, **kwargs):
        assert image is sentinel
        assert pytesseract.pytesseract.tesseract_cmd == "configured executable"
        assert kwargs == {"lang": "eng", "timeout": 30}
        return " recognized text \n"

    monkeypatch.setattr("app.documents.pytesseract.image_to_string", recognize)
    assert ocr_image(sentinel) == "recognized text"
    assert pytesseract.pytesseract.tesseract_cmd == previous


@pytest.mark.parametrize("failure,diagnostic", [
    (pytesseract.TesseractNotFoundError(), "Tesseract OCR is unavailable"),
    (pytesseract.TesseractError(1, "missing eng data"), "English.*language data"),
    (OSError("invalid executable"), "could not be started"),
], ids=["not-found", "missing-language-data", "invalid-executable"])
def test_ocr_failure_restores_command(monkeypatch, failure, diagnostic):
    previous = pytesseract.pytesseract.tesseract_cmd
    monkeypatch.setattr("app.documents.resolve_tesseract", lambda: "configured executable")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("app.documents.pytesseract.image_to_string", fail)
    with pytest.raises(DocumentError, match=diagnostic):
        ocr_image(object())
    assert pytesseract.pytesseract.tesseract_cmd == previous


def test_native_pdf_does_not_require_tesseract(monkeypatch):
    def unavailable():
        raise AssertionError("Native extraction should not invoke OCR discovery")

    monkeypatch.setattr("app.documents.resolve_tesseract", unavailable)
    assert parse_pdf((FIXTURES / "native_invoice.pdf").read_bytes())[0]["method"] == "native"


def test_missing_tesseract_rejects_scan_and_records_workflow_failure(client, monkeypatch):
    monkeypatch.setattr("app.documents.shutil.which", lambda command: None)
    response = upload(client, "scanned_invoice.pdf")
    assert response.status_code == 422
    assert "TESSERACT_CMD" in response.json()["detail"]
    run = upload_run(client, data=(FIXTURES / "scanned_invoice.pdf").read_bytes())
    assert run["status"] == "failed"
    assert run["error"]["code"] == "PDF_ERROR"
    assert "Tesseract OCR is unavailable" in run["error"]["message"]
    assert run["invoice_id"] is None
