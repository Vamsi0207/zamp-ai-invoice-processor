"""Exercise the real HTTP server against a disposable synthetic database."""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="zamp-smoke-") as directory:
        settings = {**os.environ, "ZAMP_DB_PATH": f"{directory}/smoke.sqlite3", "ZAMP_DOCUMENT_DIR": f"{directory}/documents"}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                   "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=settings)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as client:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("HTTP server failed to start")
                    try:
                        response = client.get("/health")
                        if response.status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("HTTP server readiness timed out")
                if (ROOT / "frontend/dist/index.html").exists():
                    index = client.get("/")
                    assert index.status_code == 200 and '<div id="root">' in index.text
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.text)
                    assert assets
                    for asset in assets:
                        assert client.get(asset).status_code == 200
                    assert client.get("/api/dashboard").status_code == 200
                    print("Built frontend smoke passed: HTML, compiled assets, same-origin API")
                data = json.loads((ROOT / "fixtures/synthetic_dataset.json").read_text())
                for route, record in (("/vendors", data["vendor"]), ("/purchase-orders", data["purchase_order"]),
                                      ("/receipts", data["receipt"])):
                    response = client.post(route, json=record)
                    assert response.status_code == 201, response.text
                response = client.post("/documents", files={"file": (
                    "native_invoice.pdf", (ROOT / "fixtures/native_invoice.pdf").read_bytes(), "application/pdf")})
                assert response.status_code == 201, response.text
                document_id = response.json()["id"]
                response = client.post(f"/documents/{document_id}/invoices", json=data["invoices"][0])
                assert response.status_code == 201, response.text
                invoice_id = response.json()["id"]
                route = f"/invoices/{invoice_id}/process"
                result = client.post(route, json={"idempotency_key": "smoke"}).json()
                assert result["decision"] == "Approved", result
                assert client.post(route, json={"idempotency_key": "retry"}).json() == result
                assert client.get("/purchase-orders/DEMO-PO/balance").json()["allocated_cents"] == 40000
                assert client.get(f"/invoices/{invoice_id}").json()["source_document_id"] == document_id
                print("HTTP smoke passed: health, master data, PDF upload, reviewed invoice, approval, retry, balance, provenance")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
