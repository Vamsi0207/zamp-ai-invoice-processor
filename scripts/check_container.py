"""Local Docker regression check. Synthetic data only; cleans its own volume.

Build `zamp-render:test`, then run `python -m scripts.check_container`.
No provider credentials are passed to the container. Requires a local Docker daemon.
"""
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
import uuid

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    name = "zamp-check-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    env = {**os.environ, "ZAMP_DEMO_USERNAME": "synthetic-reviewer",
           "ZAMP_DEMO_PASSWORD": secrets.token_urlsafe(32)}
    docker = ["docker"]

    def run(*args, check=True):
        result = subprocess.run([*docker, *args], env=env, capture_output=True, check=False)
        if check and result.returncode:
            # Do not echo commands, env or daemon output into test diagnostics.
            raise RuntimeError("Container check Docker operation failed")
        return result

    def ready(client):
        for _ in range(150):
            running = run("inspect", "--format", "{{.State.Running}}", name)
            if running.stdout.strip() != b"true":
                raise RuntimeError("Synthetic container exited before readiness")
            try:
                if client.get("/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        raise RuntimeError("Container readiness timeout")

    def wait_run(client, wid, target):
        for _ in range(150):
            result = client.get(f"/api/workflows/{wid}").json()
            if result["status"] == target:
                return result
            if result["status"] == "failed":
                raise RuntimeError("Synthetic container workflow failed")
            time.sleep(0.2)
        raise RuntimeError("Container workflow timeout")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    try:
        # The normal container command must reject absent credentials.
        absent = run("run", "--rm", "zamp-render:test", check=False)
        assert absent.returncode != 0
        run("volume", "create", volume)
        run("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8765",
            "--mount", f"source={volume},target=/data", "-e", "PORT=8765",
            "-e", "ZAMP_DEMO_USERNAME", "-e", "ZAMP_DEMO_PASSWORD", "zamp-render:test")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=45) as client:
            ready(client)
            assert client.get("/health").json() == {"status": "ok"}
            for path in ["/", "/docs", "/openapi.json", "/api/master-data", "/documents/unknown"]:
                assert client.get(path).status_code == 401
            assert client.post("/documents", content=b"blocked").status_code == 401
            client.auth = (env["ZAMP_DEMO_USERNAME"], env["ZAMP_DEMO_PASSWORD"])
            index = client.get("/")
            assert index.status_code == 200 and '<div id="root">' in index.text
            for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.text):
                assert client.get(asset).status_code == 200
            for kind in ["native", "scanned"]:
                assert client.get(f"/api/samples/{kind}").content.startswith(b"%PDF")
            # Run actual English OCR in the final runtime image.
            scanned = client.post("/documents", files={"file": (
                "scanned_invoice.pdf", (root / "fixtures/scanned_invoice.pdf").read_bytes(), "application/pdf")})
            assert scanned.status_code == 201
            assert scanned.json()["pages"]
            native = (root / "fixtures/native_invoice.pdf").read_bytes()
            response = client.post("/api/workflows", data={"provider": "manual", "idempotency_key": "container-check"},
                                   files={"file": ("native_invoice.pdf", native, "application/pdf")})
            assert response.status_code == 202
            wid = response.json()["id"]
            wait_run(client, wid, "Review")
            invoice = json.loads((root / "fixtures/synthetic_dataset.json").read_text())["invoices"][0]
            reviewed = client.post(f"/api/workflows/{wid}/review", json={"invoice": invoice,
                                   "reviewer": "synthetic-reviewer", "confirmed": True, "note": "Synthetic Docker check"})
            assert reviewed.status_code == 202
            wait_run(client, wid, "Approved")
            assert client.get("/purchase-orders/DEMO-PO/balance").json()["allocated_cents"] == 40000
            # Delete a receipt deliberately: restart must not reseed or recreate it.
            code = "import sqlite3; c=sqlite3.connect('/data/zamp.sqlite3'); c.execute('DELETE FROM receipts'); c.commit()"
            run("exec", name, "python", "-c", code)
            uid = run("exec", name, "python", "-c", "print(open('/proc/1/status').read().split('Uid:')[1].splitlines()[0].strip().split()[0])")
            assert uid.stdout.strip() == b"10001"
            run("restart", name)
            ready(client)
            assert client.get(f"/api/workflows/{wid}").json()["status"] == "Approved"
            assert client.get(f"/api/workflows/{wid}/pdf").content == native
            assert client.get("/purchase-orders/DEMO-PO/balance").json()["allocated_cents"] == 40000
            count = run("exec", name, "python", "-c", "import sqlite3; print(sqlite3.connect('/data/zamp.sqlite3').execute('SELECT count(*) FROM receipts').fetchone()[0])")
            assert count.stdout.strip() == b"0"
            # Replaying the approved review must not consume balance again.
            replay = client.post(f"/api/workflows/{wid}/review", json={"invoice": invoice,
                                 "reviewer": "synthetic-reviewer", "confirmed": True, "note": "Retry"})
            assert replay.status_code == 202
            assert client.get("/purchase-orders/DEMO-PO/balance").json()["allocated_cents"] == 40000
        run("rm", "-f", name)
        # Public mode cannot expose the previous private database, even with no key.
        old = run("run", "--rm", "--mount", f"source={volume},target=/data", "-e", "ZAMP_PUBLIC_DEMO=1", "zamp-render:test", check=False)
        assert old.returncode != 0
        run("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8765",
            "--mount", f"source={volume},target=/data", "-e", "PORT=8765", "-e", "ZAMP_PUBLIC_DEMO=1",
            "-e", "ZAMP_DB_PATH=/data/public.sqlite3", "-e", "ZAMP_DOCUMENT_DIR=/data/public-documents",
            "-e", "ZAMP_DEMO_UPLOADS_PER_MINUTE=1", "zamp-render:test")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=45) as client:
            ready(client)
            index = client.get("/")
            assert index.status_code == 200 and "www-authenticate" not in index.headers
            assert client.get("/api/configuration").json()["public_demo"]["enabled"]
            assert client.post("/api/receipts", json={}).status_code == 403
            response = client.post("/api/workflows", data={"provider": "manual", "idempotency_key": "public"},
                                   files={"file": ("scan.pdf", (root / "fixtures/scanned_invoice.pdf").read_bytes(), "application/pdf")})
            assert response.status_code == 202
            wid = response.json()["id"]
            run_data = wait_run(client, wid, "Review")
            assert run_data["document"]["pages"][0]["method"] == "ocr"
            response = client.post("/api/workflows", data={"provider": "manual", "idempotency_key": "again"},
                                   files={"file": ("scan.pdf", (root / "fixtures/scanned_invoice.pdf").read_bytes(), "application/pdf")})
            assert response.status_code == 429
            response = client.post(f"/api/workflows/{wid}/review", json={"invoice": invoice,
                                   "reviewer": "demo-reviewer", "confirmed": True, "note": "Synthetic public demo confirmation"})
            assert response.status_code == 202
            wait_run(client, wid, "Approved")
            run("restart", name)
            ready(client)
            assert client.get(f"/api/workflows/{wid}").json()["status"] == "Approved"
            assert client.get("/api/master-data").json()["purchase_orders"][0]["remaining_cents"] == 60000
            count = run("exec", name, "python", "-c", "import sqlite3; print(sqlite3.connect('/data/public.sqlite3').execute(\"SELECT used FROM public_demo_budgets WHERE name='UPLOADS_PER_MINUTE'\").fetchone()[0])")
            assert count.stdout.strip() == b"1"
        print("Private and public container checks passed: private auth preserved, public login-free access, isolated synthetic data, PORT=8765, English OCR, manual approval, UID 10001, volume restart/PDF persistence, durable rate limits, restricted receipts, no reseeding or double allocation. No live AI request.")
    finally:
        run("rm", "-f", name, check=False)
        run("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
