# Windows Python 3.12 and Tesseract setup

The Python dependencies include `pytesseract`, a wrapper. You must also install
Tesseract OCR itself to process image-only/scanned pages. Native text PDFs do not
require the OCR executable. Missing OCR is a document/workflow failure, never an
empty successful extraction or a reason to bypass financial validation.

## Install and configure Tesseract

1. Follow the Windows installer links in the
   [official Tesseract installation documentation](https://tesseract-ocr.github.io/tessdoc/Installation.html).
   The Windows builds maintained by [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
   are linked there. Install Tesseract 5 and English (`eng`) trained language data.
2. Either add the installation directory (often `C:\Program Files\Tesseract-OCR`)
   to PATH and open a new terminal, or configure the full executable path in the
   same PowerShell session that launches the backend/tests:

   ```powershell
   $env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
   & $env:TESSERACT_CMD --version
   & $env:TESSERACT_CMD --list-langs
   ```

   Verify that `eng` is listed. Adjust the path to your actual installation. The
   PowerShell quotes group the value; do not include literal quote characters or
   command arguments inside `TESSERACT_CMD`.
3. For PATH discovery, leave `TESSERACT_CMD` unset/blank and check:

   ```powershell
   Get-Command tesseract
   tesseract --version
   tesseract --list-langs
   ```

`TESSERACT_CMD` takes precedence over PATH. An invalid explicit value fails with a
setup diagnostic rather than silently choosing another executable. No fixed
Windows installation directory is assumed. The setting is resolved when OCR is
needed; restart the running backend after changing its inherited environment.
`.env.example` is documentation: the application does not automatically load `.env`.
Do not change your whole PATH to the executable filename; add its directory.

## Install dependencies and run tests

From the repository root in PowerShell (activation is not required):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "from app.documents import resolve_tesseract; print(resolve_tesseract())"
.\.venv\Scripts\python.exe -m pytest -q
```

Run the real scanned/mixed OCR checks specifically with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_documents.py -k 'real_scanned_pdf_ocr or mixed_native_scanned_pages'
```

The upload-validation cases have short explicit pytest IDs, including `oversized`.
The 10 MiB + 1 payload and all original assertions are retained; pytest no longer
embeds the payload in `PYTEST_CURRENT_TEST`, which has a Windows length limit.

## Failure behavior and verification scope

Missing executable diagnostics name PATH and `TESSERACT_CMD`; Tesseract execution
failures also point to English language data. Scanned uploads return HTTP 422 and
workflow processing records `PDF_ERROR`. Empty OCR output still fails. OCR keeps
the existing English language, 30-second timeout, 200 DPI rendering and pixel/text
budgets. No OCR tests are silently skipped when Tesseract is missing.

The changes are validated on Linux with Python 3.12 and real Tesseract, plus portable
discovery tests covering PATH, explicit paths with spaces, invalid paths and command
restoration. They do not establish an actual Windows Python 3.12.10 pass. Run the
commands above on Windows after installing Tesseract to confirm your local setup.

Implementation validation: Linux Python 3.12.14 / Tesseract 5.5.0, **120 passed,
2 skipped** (optional live-provider tests). Real scanned and mixed-page OCR tests
ran. All six upload case IDs were collected; the longest node ID was 66 characters.
`pip check` and the existing built-app/HTTP smoke passed. The full-suite command was:

```sh
GEMINI_MODEL=gemini-2.5-flash OPENAI_MODEL=gpt-4.1-mini .venv/bin/python -m pytest -q
```

Those model settings applied only to the test process: this cloud session's inherited
`GEMINI_MODEL` has surrounding whitespace and initially caused three unrelated
mock-provider tests to fail validation. No AI adapter, credential, deployment, or
financial engine change is included. No Windows execution result is claimed.
