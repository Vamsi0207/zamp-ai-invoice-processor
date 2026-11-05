# Windows evaluator setup (PowerShell)

These commands follow the actual repository entrypoints and environment variables.
The owner reports a working Windows Python 3.12/React demo with real Gemini
`gemini-3.1-flash-lite`. This submission pass verified installation/build/test paths
on Linux, not a fresh Windows machine. See [validation](validation.md) for that distinction.

## Prerequisites and clone

Install Git, Python 3.12 and Node.js 24 (including npm) from their official installers.
Use the Python launcher `py`; activation and PowerShell execution-policy changes
are unnecessary because commands call the virtual environment executable directly.

```powershell
git clone https://github.com/Vamsi0207/zamp-ai-invoice-processor.git
Set-Location zamp-ai-invoice-processor
git switch main
git pull --ff-only
py -3.12 --version
node --version
npm --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
```

Before this submission PR merges, check out its `docs/submission-readiness` branch
to include the complete fixture set and documentation. Preserve any existing local
work instead of resetting an existing checkout. No worktree is required.

## Tesseract OCR

`pytesseract` is a Python wrapper, not the OCR executable. Install Tesseract 5 with
English (`eng`) data. One Windows installation option is:

```powershell
winget install --exact --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
& $env:TESSERACT_CMD --version
& $env:TESSERACT_CMD --list-langs
.\.venv\Scripts\python.exe -c "from app.documents import resolve_tesseract; print(resolve_tesseract())"
```

Adjust the path to your installation and confirm `eng` appears. If winget is not
available, follow the Windows installer links in the [official Tesseract guide](https://tesseract-ocr.github.io/tessdoc/Installation.html)
and [UB Mannheim distribution](https://github.com/UB-Mannheim/tesseract/wiki).
Alternatively add the executable's **directory** to PATH, open a new terminal, leave
`TESSERACT_CMD` unset, and check `Get-Command tesseract`. An invalid explicit
`TESSERACT_CMD` fails rather than silently falling back. Quotes in the PowerShell
assignment are not part of the value; do not add command arguments to it.

Native PDFs do not require OCR; scanned/sparse pages do. Missing OCR returns an
actionable error, not a successful empty invoice. Real OCR tests are not silently
skipped when the executable is missing.

## Frontend installation and build

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
```

The build includes TypeScript checks and creates ignored `frontend/dist`. Build
before starting FastAPI so it mounts the dashboard at `/`.

## Secure provider configuration

For the owner-verified demo, enter your own Gemini key without echoing it:

```powershell
$zampGeminiSecureKey = Read-Host 'Gemini API key (hidden)' -AsSecureString
$env:GEMINI_API_KEY = ([System.Net.NetworkCredential]::new('', $zampGeminiSecureKey)).Password
Remove-Variable zampGeminiSecureKey
$env:GEMINI_MODEL = 'gemini-3.1-flash-lite'
```

These settings apply to this terminal and its child backend process. Do not print
the key, use it in a command-line argument, commit it to `.env`, or use a `VITE_*`
variable. `.env.example` is a template only; `.env` is **not** loaded automatically.
Restart the backend to inherit changed variables. The application's unchanged
fallback is `gemini-3.5-flash-lite` only when `GEMINI_MODEL` is unset; the explicit
selection above is required for the reported demo configuration.

An account with access/quota for that model and HTTPS access to
`generativelanguage.googleapis.com` is required. The configured indicator checks
presence, not authorization. Optional real verification of only the synthetic fixture:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_gemini
```

Accept only `status: passed` with both validation flags true. Errors retain safe
categories; do not replace citations or bypass validation. This command incurs one
real provider request. Codex did not run it with live credentials in this pass.

Without a Gemini account/key, leave the key unset and choose **Manual review · no AI
call** in the UI. PDF/OCR and financial checks still run, but fields are entered by
the reviewer and no AI citations are generated. OpenAI is another implemented
adapter using `OPENAI_API_KEY`/`OPENAI_MODEL` (default `gpt-4.1-mini`) and access to
`api.openai.com`; live OpenAI verification is not claimed. There is no automatic
provider fallback.

## Fresh demo database and startup

Choose a fresh path once, before scenario A. Do not reuse a valued database as a
reset. A separate document directory keeps this run's artifacts together.

```powershell
$env:ZAMP_DB_PATH = 'data/submission-demo.sqlite3'
$env:ZAMP_DOCUMENT_DIR = 'data/submission-documents'
if (Test-Path $env:ZAMP_DB_PATH) { throw 'Demo database exists. Choose a new path to start a fresh A/B/C sequence.' }
.\.venv\Scripts\python.exe -c "import os; from scripts.seed import seed; seed(os.environ['ZAMP_DB_PATH'])"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave this process running. In another terminal open the local dashboard:

```powershell
Start-Process 'http://127.0.0.1:8000'
```

The seed creates vendor/PO/receipt records, not invoices. The no-argument
`python -m scripts.seed` targets `data/demo.sqlite3`, **not** `ZAMP_DB_PATH`, so use
the explicit call above for the submission database. Seeding skips when DEMO-VENDOR
already exists; it does not repair partial seeds or restore consumed balances.
To restart the same demo, rerun only the Uvicorn command with the same environment.
To repeat A/B/C from the beginning, choose fresh DB/document paths, seed and restart.

For Vite development, keep FastAPI running and in another terminal:

```powershell
Set-Location frontend
$env:ZAMP_API_TARGET = 'http://127.0.0.1:8000'
npm run dev
```

Use the URL Vite prints. The built dashboard needs only the FastAPI process. There
is no authentication: keep the demo on loopback and use one backend worker.

## Automated tests

Run from the repository root in a **separate test terminal**, without demo-specific
`ZAMP_DB_PATH`/`ZAMP_DOCUMENT_DIR` or live-test opt-in settings. Preserve your server
terminal; the following removal affects only this test process's environment:

```powershell
Remove-Item Env:ZAMP_DB_PATH -ErrorAction SilentlyContinue
Remove-Item Env:ZAMP_DOCUMENT_DIR -ErrorAction SilentlyContinue
Remove-Item Env:ZAMP_RUN_LIVE_AI -ErrorAction SilentlyContinue
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.smoke
Push-Location frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
Pop-Location
```

Playwright now selects `.venv\Scripts\python.exe` on Windows and `.venv/bin/python`
on Linux. Its isolated server seeds a temporary database and deliberately clears
provider credentials. Ports 8911 and 5178 must be free; the demo can remain on 8000.
These browser tests do not use live AI. Optional pytest live-provider checks require
both a key and explicit `ZAMP_RUN_LIVE_AI=1`; they are skipped by default. The full
suite includes real local scanned/mixed OCR tests. Upload cases have short explicit
IDs so the oversized payload is not embedded in Windows' `PYTEST_CURRENT_TEST` value.

These PowerShell commands are reviewed against the implementation. The new
Playwright Windows path selection still needs a fresh Windows run; a Linux pass is
not presented as Windows verification. See [current test results](validation.md).
