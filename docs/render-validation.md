# Render packaging verification

This records the original private deployment pass. For the later opt-in login-free
mode and its current test results, see [public demo verification](public-demo.md#automated-verification).

Verified locally on Linux, 2026-11-11, starting from main `3b2080c` (submission
PR #7 merged). No hosted Render URL or live AI extraction was tested.

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 244 passed, 2 optional live-provider tests skipped; 6 existing upstream deprecation warnings |
| `npm test` in frontend | 7 passed |
| `npm run build` in frontend | TypeScript/Vite passed |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e` | 3 real browser/API tests passed |
| `.venv/bin/python -m scripts.smoke` | Built UI/assets and real HTTP financial/PDF smoke passed |
| Multi-stage Docker image | Built successfully, including frontend, locked Python dependencies and English Tesseract |
| `.venv/bin/python -m scripts.check_container` | Isolated volume/container regression passed; no provider credentials |

The container check verifies fail-closed startup without credentials, 401 for UI/API
and docs before login, protected HTML/assets/sample PDF downloads, runtime
`PORT=8765`, actual scanned-PDF OCR, synthetic manual review and approval, UID 10001,
and volume persistence of the approved run and its PDF after restart. It deliberately
deletes a receipt before restart and verifies no reseeding occurs. Approved retry
keeps allocation at $400. It removes only its own generated container/volume.

Backend regression tests additionally cover invalid/malformed credentials,
cross-origin mutation rejection, optional local access, and never seeding existing
empty or invalid database files. Financial/extraction/evidence/matching/approval
implementations and dependency versions are unchanged. Windows startup remains
optional-auth; this pass ran on Linux, not a fresh Windows host.
The existing GitHub workflow now also builds this image and runs the isolated
container regression; its remote outcome must be checked on the deployment PR.

To repeat Docker checks on an ordinary Docker installation:

```sh
docker build -t zamp-render:test .
python -m scripts.check_container
```

Use the project's virtual-environment Python. In the Codex TLS-intercepted build
environment, the build used an optional BuildKit secret containing the trusted CA
bundle: `--secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt`. It is not copied
into image layers; TLS verification remains enabled. Render ordinarily needs no such
secret. No Gemini key or demo password is supplied during image build.

The first runtime check exposed owner-only cloud-checkout source permissions; the
Dockerfile now explicitly grants read/traverse access to immutable application
files before dropping privileges. The final image must pass the container check.

Remaining hosted verification: create the Render service, configure secrets, obtain
its HTTPS URL, confirm authentication and live synthetic extraction, run A/B/C, and
verify persistence after restart if a paid disk is attached. Free storage is
temporary. Local Docker success does not establish a successful Render deployment.
