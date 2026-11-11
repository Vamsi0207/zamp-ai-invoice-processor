# Login-free public Render demo

This mode is deliberately limited to the four bundled synthetic PDFs. It is not an
anonymous real-document service. Everyone shares the same runs, audit history,
quotas and PO balance; the screen says so. Never upload personal/financial records.

## Change the existing Render service

1. Review/merge the `deploy/public-demo` PR into `main`. Keep the Docker runtime,
   default Docker command, one instance, and `/health` health check. The repository
   blueprint defaults to **private**; simply redeploying does not remove its login.
2. In Render → this service → **Environment**, deliberately configure:

   ```text
   ZAMP_PUBLIC_DEMO=1
   ZAMP_REQUIRE_DEMO_AUTH=0
   ZAMP_DB_PATH=/data/public-demo-v1.sqlite3
   ZAMP_DOCUMENT_DIR=/data/public-demo-v1-documents
   GEMINI_MODEL=gemini-3.1-flash-lite
   ```

   **Delete `ZAMP_DEMO_USERNAME` and `ZAMP_DEMO_PASSWORD`**. Keep `GEMINI_API_KEY`
   exclusively in Render's server environment. Do not put it into source, a URL,
   `VITE_*`, build arguments or screenshots. Leave it absent to demonstrate explicit
   manual review without AI. Render supplies `PORT`; do not replace the startup
   command or increase workers/instances. For Blueprint-managed services, apply
   these deliberate overrides to the Blueprint before syncing; the committed
   `render.yaml` retains private defaults for other deployments.
3. Use the **new paths above**, not the existing private DB/document directory.
   Initial startup seeds a new synthetic vendor, PO and receipt set and marks this
   workspace public. It never resets an old DB. An unmarked existing DB, nonempty
   new document directory, changed master data, unavailable limiter, invalid limits,
   second public process, or conflicting private authentication causes startup to
   fail closed. Investigate the error and choose unused paths; do not delete valued
   data or copy a public marker into a private database.
4. Save settings and use **Manual Deploy → Deploy latest commit**. Keep `/health`
   configured. Render's service page displays the URL:
   `https://zamp-ai-invoice-processor.onrender.com`. Check the deployed commit in
   Render before checking its behavior. No Render service settings were changed
   by Codex; GitHub PR creation is not deployment.

On Render Free, `/data` is **temporary storage**, despite its name. Redeploys,
restarts/instance replacement can discard data and its usage counters; sleep/cold
starts affect availability. Back up valuable old data before redeploying. To retain
data/counters, use a paid persistent disk mounted at `/data` and keep both public
paths beneath it. New public paths leave existing private data untouched; attaching
a disk does not migrate old ephemeral files. Never expose private paths publicly.

## Usage limits

All limits are **global/shared**, not based on spoofable forwarded IP headers.
The first nine values can be configured with the listed variables. Invalid/zero or
above-maximum values fail startup. Counters use atomic SQLite transactions in a
fixed-size table, persist across process restarts with the DB, and are not refunded
after a failed attempt. There is no automatic provider retry.

| Environment variable | Default | Maximum | Scope |
| --- | ---: | ---: | --- |
| `ZAMP_DEMO_AI_PER_MINUTE` | 2 | 10 | Actual AI attempts per UTC epoch minute |
| `ZAMP_DEMO_AI_PER_DAY` | 20 | 100 | Actual AI attempts per UTC day |
| `ZAMP_DEMO_AI_TOTAL` | 100 | 1000 | Actual AI attempts for this database's lifetime |
| `ZAMP_DEMO_UPLOADS_PER_MINUTE` | 6 | 30 | Workflow upload requests, including repeats/invalid requests |
| `ZAMP_DEMO_WRITES_PER_MINUTE` | 20 | 60 | Upload, review and retry requests |
| `ZAMP_DEMO_WRITES_TOTAL` | 500 | 10000 | Total mutation attempts for this DB's lifetime |
| `ZAMP_DEMO_READS_PER_MINUTE` | 600 | 1200 | API reads, including polling |
| `ZAMP_DEMO_MAX_RETRIES` | 3 | 5 | Maximum total workflow attempts, including initial attempt |
| `ZAMP_DEMO_MAX_BODY_BYTES` | 1048576 | 10551296 | Entire upload HTTP body, including multipart overhead |

Fixed windows can admit a burst across their boundary; these are request caps, not
rolling token or monetary budgets. Gemini failures, invalid evidence, and missing
credentials still count if extraction reaches the adapter. Terminal/identical-file
replays do not call Gemini again. New AI requests and extraction retries are checked
before admission and counted atomically at the provider boundary. Exhausted quotas
return **HTTP 429** with a safe message and `Retry-After: 60`; a day/lifetime quota
will not necessarily renew after 60 seconds. At lifetime limits, the owner must
review usage; there is no public reset endpoint. Manual review avoids AI-only caps,
but still obeys mutation and workflow-attempt caps. Budget storage failures return
503 and stop new processing; they never fall back to unlimited calls.

One expensive HTTP operation (including its background task) and one AI call can
run at a time. Busy submissions return 429 instead of queuing arbitrarily. Restart
recovery is also serialized. A file lock refuses a second public process; this is
not a distributed multi-replica limiter. Container startup additionally sets a
16-connection Uvicorn limit, backlog 32, keepalive 5 seconds and a default single
Tesseract OpenMP thread. Upload bodies have a 15-second read timeout, one file/two
form fields, and review/retry JSON bodies are limited to 64 KiB. PDFs must still
pass the existing 10 MiB/20-page/12-million-OCR-pixel/100k-text checks and English OCR
timeouts. Only exact hashes of the bundled samples reach parsing/OCR, which further
bounds public work. These controls reduce resource use; they are not a benchmarked
512 MB memory guarantee or DDoS protection.

## Synthetic-only boundary and demo steps

The dashboard provides download links for native, scanned, duplicate-variant and
over-budget PDFs. Upload them unchanged. Unknown PDFs, appended bytes, unsupported
providers, arbitrary invoice fields and free-text audit signoffs are rejected.
Stored filenames are canonical sample names; idempotency keys are hashed before
storage. Public mode permits Gemini/manual workflows; OpenAI is disabled here.
The UI displays a fixed `demo-reviewer` and `Synthetic public demo confirmation`
signoff. A person must still inspect the source, select existing mappings, enter
printed fields, and explicitly tick confirmation. This is a demo signoff, not proof
of identity. The policy does not fill in or approve invoice facts on anyone's behalf.

Only the workflow HTTP surface is writable. Legacy document/invoice-processing
writes, vendor/PO edits and receipt recording are blocked with 403, even if called
directly or through an API alias. Master data/receipts remain the seeded synthetic
values. All financial decisions, matching, Pydantic checks and evidence validation
are still performed by the original code. In public mode PO balances are available
through `/api/master-data`, not unrestricted legacy routes.

For the ordered [A/B/C demo](demo-walkthrough.md), start a genuinely new public
workspace. A: native SYN-001/$400 → confirm → Approved, $600 left. B: duplicate
variant → confirm the same printed facts → duplicate rejection, $600 left. C:
SYN-002/$700 → confirm seven chairs → quantity/amount/receipt rejection, $600 left.
The scanned sample contains the same SYN-001 and will be a business duplicate after
A. Prior visitors may have processed these already. Identical uploads reuse those
runs; there are only four sample documents, no per-visitor sandbox and no automatic
reset. You can inspect existing decisions, evidence, PDFs and audits. Owner-controlled
fresh paths create a new demo without silently deleting previous work.

## Verify the hosted URL after deployment

Open a private browser session, with no saved Basic credentials. Check:

- `/` returns the React dashboard immediately, no popup or `WWW-Authenticate`.
- `/api/configuration` reports `public_demo.enabled: true`, no credential values.
- `/api/master-data` and history load; shared synthetic-data notice is visible.
- `/health` reports only `{"status":"ok"}`.
- Direct master-data/receipt writes return 403; excessive operations return 429.
- The supplied PDF reaches real native/OCR stages; Gemini either validates evidence
  and stops for human review or records a safe actual provider failure. Do not
  describe a manual/no-key test as successful Gemini extraction.
- On a fresh state, A/B/C preserves the expected $400 allocation/$600 balance.
  With a paid disk, restart and verify runs, PDFs and limiter counts persist.

In PowerShell, safe read-only checks (do not publish full workflow contents):

```powershell
$zampDemoUrl = 'https://zamp-ai-invoice-processor.onrender.com'
curl.exe -sS -o NUL -w '%{http_code}\n' "$zampDemoUrl/"
curl.exe -sS "$zampDemoUrl/health"
(Invoke-RestMethod "$zampDemoUrl/api/configuration").public_demo.enabled
```

Codex's outbound network policy currently denies this Render hostname, and no live
Gemini credential is available here. Local/mock/browser/container results do not
establish hosted success. No deployment claim is made until the actual URL passes.

## Remaining risks and private-mode rollback

Unauthenticated visitors can consume shared quotas, finish another visitor's
synthetic review or deny service by exhausting the lifetime write budget. There
are no user identities or isolated sessions. Network-level DDoS, provider billing
and platform memory limits require owner monitoring. Configure separate low
provider-project quotas/billing controls and a demo-only key: app counters cannot
survive lost ephemeral storage or enforce a monetary/token cap. Remove the key
for a zero-provider-cost manual demo. This mode must never contain real data.

To return to private mode: set `ZAMP_PUBLIC_DEMO=0`, restore the required flag and
a valid username/long random password, and redeploy. Existing private authentication
behavior and local Windows defaults are preserved. Public mode **refuses** any
explicit private auth flag/credentials rather than bypassing them.

## Automated verification

Actually executed on Linux for this change:

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **276 passed, 2 skipped**, 6 existing upstream deprecation warnings |
| `.venv/bin/python -m scripts.smoke` | Built HTML/assets and real HTTP PDF/financial smoke passed |
| `npm test` in frontend | **9 passed**; HTTP contract tests use explicit fetch mocks |
| `npm run build` in frontend | TypeScript/Vite production build passed |
| `npm run test:e2e` | **3 passed**, existing private/local browser/API suite |
| `ZAMP_E2E_PUBLIC_DEMO=1 npm run test:e2e` | **1 passed**, login-free browser/API A/B/C flow |
| Multi-stage Docker build | Passed |
| `.venv/bin/python -m scripts.check_container` | Private and public modes passed; actual English OCR, approval, restart, PDF and quota persistence |

Browser tests used `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium` on this host;
CI uses Playwright's installed Chromium. On Windows set
`$env:ZAMP_E2E_PUBLIC_DEMO='1'` in a separate clean test shell before the public
browser command, then remove it for the existing suite. Local Windows defaults
remain unchanged, but a fresh Windows run was not performed here.

Backend AI success/error tests use HTTP mocks with the real adapter's Pydantic and
evidence validation, or explicit failing test adapters for quota/concurrency checks.
They verify exactly one admission under contention, durable budgets, safe 429/503,
unknown-document and private-workspace rejection, master-data restrictions,
mandatory human confirmation, duplicate rejection, financial/receipt/quantity
constraints, and allocation staying $400. A previously public workspace containing
subsequent private documents is also refused on re-publication. The two skipped
tests require live provider credentials and explicit opt-in; no live Gemini request
was performed. The warnings are Starlette/AnyIO and PyMuPDF SWIG deprecations;
browser startup emits a non-failing NO_COLOR/FORCE_COLOR warning.

The public browser pass initially caught Vite rewriting Host during proxying; Vite
now preserves the original Host so legitimate same-origin mutations pass the same
origin check as the single-service deployment. No exception for arbitrary forwarded
headers was added. Container checks remain local evidence, not hosted Render proof.
