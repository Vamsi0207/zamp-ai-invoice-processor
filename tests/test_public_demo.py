"""Public security boundary: synthetic fixtures, mocked AI, real financial engine."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.extraction import ProviderError
from app.public_demo import DemoLimit, NOTE, REVIEWER
from scripts.container_start import initialize_database

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def public(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAMP_PUBLIC_DEMO", "1")
    for name in ["ZAMP_REQUIRE_DEMO_AUTH", "ZAMP_DEMO_USERNAME", "ZAMP_DEMO_PASSWORD"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ZAMP_DOCUMENT_DIR", str(tmp_path / "public-documents"))
    path = tmp_path / "public.sqlite3"
    assert initialize_database(path)
    with TestClient(create_app(path)) as client:
        yield client


def upload(client, fixture="native_invoice.pdf", provider="manual", key="public-check"):
    return client.post("/api/workflows", data={"provider": provider, "idempotency_key": key},
                       files={"file": ("personal-name.pdf", (FIXTURES / fixture).read_bytes(), "application/pdf")})


def invoice(over=False):
    data = json.loads((FIXTURES / "synthetic_dataset.json").read_text())["invoices"][0]
    if over:
        data.update(number="SYN-002", total="700.00")
        data["lines"][0]["quantity"] = 7
    return data


def confirm(client, wid, body=None, **changes):
    return client.post(f"/api/workflows/{wid}/review", json={"invoice": body or invoice(),
                       "reviewer": REVIEWER, "note": NOTE, "confirmed": True, **changes})


def test_no_login_and_synthetic_configuration(public):
    for path in ["/", "/api/configuration", "/api/dashboard", "/api/master-data", "/api/workflows", "/api/samples/native"]:
        response = public.get(path)
        # Backend-only CI before frontend build legitimately has no index route yet.
        assert response.status_code in ({200, 404} if path == "/" else {200})
        assert "www-authenticate" not in response.headers
    assert public.get("/api/configuration").json()["public_demo"]["enabled"]


@pytest.mark.parametrize("path", ["/vendors", "/purchase-orders", "/receipts", "/api/receipts", "/invoices", "/invoices/1/process", "/documents", "/documents/unknown/extract", "/documents/unknown/invoices"])
def test_non_demo_mutations_blocked(public, path):
    assert public.post(path, json={"arbitrary": "data"}).status_code == 403


def test_personal_pdf_provider_and_free_text_rejected(public):
    response = public.post("/api/workflows", data={"provider": "manual", "idempotency_key": "private"},
                           files={"file": ("private.pdf", b"%PDF-not-a-bundled-sample", "application/pdf")})
    assert response.status_code == 403
    assert upload(public, provider="openai").status_code == 403
    wid = upload(public).json()["id"]
    assert public.get(f"/api/workflows/{wid}").json()["filename"] == "native_invoice.pdf"
    assert confirm(public, wid, reviewer="Personal name").status_code == 403
    assert confirm(public, wid, note="Private financial note").status_code == 403
    assert confirm(public, wid, {**invoice(), "number": "ARBITRARY"}).status_code == 403
    assert confirm(public, wid, confirmed=False).status_code == 422
    assert public.get(f"/api/workflows/{wid}").json()["invoice_id"] is None


def test_duplicate_and_over_budget_still_use_real_engine(public):
    first = upload(public).json()["id"]
    assert confirm(public, first).status_code == 202
    assert public.get(f"/api/workflows/{first}").json()["status"] == "Approved"
    assert upload(public, key="retry-key").json()["id"] == first
    assert confirm(public, first).status_code == 202
    assert public.post(f"/api/workflows/{first}/retry", json={}).status_code == 202
    duplicate = upload(public, "duplicate_invoice_variant.pdf", key="duplicate").json()["id"]
    assert confirm(public, duplicate).status_code == 202
    result = public.get(f"/api/workflows/{duplicate}").json()["decision"]
    assert result["decision"] == "Rejected" and result["reasons"] == ["DUPLICATE_INVOICE"]
    over = upload(public, "over_budget_invoice.pdf", key="over").json()["id"]
    assert confirm(public, over, invoice(over=True)).status_code == 202
    result = public.get(f"/api/workflows/{over}").json()["decision"]
    assert result["decision"] == "Rejected"
    assert set(result["reasons"]) == {"PO_BALANCE_EXCEEDED", "ORDERED_QUANTITY_EXCEEDED", "RECEIPT_SHORTFALL"}
    with public.app.state.service.database.connect() as db:
        assert db.execute("SELECT SUM(amount_cents) FROM allocations").fetchone()[0] == 40000
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 1
        assert "personal-name" not in " ".join(r[0] for r in db.execute("SELECT filename FROM workflows"))


def test_ai_caps_mocked_failure_and_http_429(public):
    calls = []

    class Fake:
        model = "mocked-test-model"

        def extract(self, pages):
            calls.append(True)
            raise ProviderError("Safe mocked provider failure", code="SERVICE_UNAVAILABLE", http_status=503)

    public.app.state.adapter_factory = lambda provider: Fake()
    guard = public.app.state.public_demo
    guard.limits["AI_TOTAL"] = 1
    wid = upload(public, provider="gemini").json()["id"]
    assert public.get(f"/api/workflows/{wid}").json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    response = public.post(f"/api/workflows/{wid}/retry", json={})
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert "www-authenticate" not in response.headers
    assert upload(public, "duplicate_invoice_variant.pdf", provider="gemini", key="second-ai").status_code == 429
    assert len(calls) == 1
    # Budget exhaustion does not disable the explicit no-AI manual alternative.
    assert public.post(f"/api/workflows/{wid}/retry", json={"provider": "manual"}).status_code == 202
    assert public.get(f"/api/workflows/{wid}").json()["status"] == "Review"


def test_mocked_gemini_success_still_validates_source_and_requires_confirmation(public, monkeypatch):
    import httpx
    from app.extraction import AIAdapter
    from test_extraction import response_body
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    calls = []

    def handler(request):
        calls.append(True)
        return httpx.Response(200, json=response_body("gemini"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        public.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        wid = upload(public, provider="gemini").json()["id"]
        run = public.get(f"/api/workflows/{wid}").json()
        assert run["status"] == "Review" and run["invoice_id"] is None
        assert len(run["extraction"]["evidence"]) == 13
        assert upload(public, provider="gemini", key="new-key").json()["id"] == wid
        assert len(calls) == 1
        assert confirm(public, wid, run["draft"]).status_code == 202
        assert public.get(f"/api/workflows/{wid}").json()["status"] == "Approved"


@pytest.mark.parametrize("name", ["WRITES_PER_MINUTE", "WRITES_TOTAL"])
def test_http_write_budgets(public, name):
    public.app.state.public_demo.limits[name] = 1
    wid = upload(public).json()["id"]
    assert confirm(public, wid).status_code == 429


def test_invalid_limits_and_nonempty_document_root_fail_closed(public, monkeypatch, tmp_path):
    monkeypatch.setenv("ZAMP_DEMO_AI_TOTAL", "0")
    with pytest.raises(RuntimeError):
        create_app(public.app.state.service.database.path)
    root = tmp_path / "already-existing-documents"
    root.mkdir()
    (root / "preserve.txt").write_text("preserve")
    monkeypatch.setenv("ZAMP_DOCUMENT_DIR", str(root))
    new_path = tmp_path / "new.sqlite3"
    with pytest.raises(RuntimeError, match="empty public-demo"):
        initialize_database(new_path)
    assert not new_path.exists() and (root / "preserve.txt").read_text() == "preserve"


@pytest.mark.parametrize("name,seconds", [("AI_PER_MINUTE", 60), ("AI_PER_DAY", 86400), ("AI_TOTAL", 0)])
def test_each_ai_budget_and_atomic_admission(public, name, seconds):
    guard = public.app.state.public_demo
    guard.limits[name] = 1
    guard.budget([(name, seconds)])
    with pytest.raises(DemoLimit):
        guard.budget([(name, seconds)])


def test_atomic_budget_under_thread_contention(public):
    guard = public.app.state.public_demo
    guard.limits["AI_TOTAL"] = 1

    def attempt(_):
        try:
            guard.budget([("AI_TOTAL", 0)])
            return True
        except DemoLimit:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 1


def test_ai_concurrency_slot_is_always_released(public):
    guard = public.app.state.public_demo
    started, finish = threading.Event(), threading.Event()

    class Fake:
        model = "mock"

        def extract(self, pages):
            started.set()
            assert finish.wait(timeout=5)
            raise ProviderError("Safe test error")

    adapter = guard.adapter(Fake())
    with ThreadPoolExecutor() as executor:
        future = executor.submit(adapter.extract, [])
        assert started.wait(timeout=5)
        try:
            with pytest.raises(DemoLimit):
                adapter.extract([])
        finally:
            finish.set()
        with pytest.raises(ProviderError):
            future.result()
    assert guard.ai.acquire(blocking=False)
    guard.ai.release()


def test_limits_fail_closed_and_upload_body_bounded(public):
    guard = public.app.state.public_demo
    assert guard.processing.acquire(blocking=False)
    try:
        assert upload(public).status_code == 429
    finally:
        guard.processing.release()
    response = public.post("/api/workflows", content=b"x" * (guard.limits["MAX_BODY_BYTES"] + 1))
    assert response.status_code == 413
    with guard.database.connect() as db:
        db.execute("DROP TABLE public_demo_budgets")
    response = public.get("/api/dashboard")
    assert response.status_code == 503
    assert "sqlite" not in response.text.lower()


def test_upload_write_read_caps_and_retry_cap(public):
    guard = public.app.state.public_demo
    guard.limits["UPLOADS_PER_MINUTE"] = 1
    wid = upload(public, provider="gemini").json()["id"]
    assert upload(public).status_code == 429
    guard.limits["MAX_RETRIES"] = 1
    assert public.post(f"/api/workflows/{wid}/retry", json={"provider": "manual"}).status_code == 429
    guard.limits["READS_PER_MINUTE"] = 1
    assert public.get("/api/dashboard").status_code == 200
    assert public.get("/api/dashboard").status_code == 429
    assert public.get("/health").status_code == 200


def test_public_marker_and_budgets_survive_restart(public):
    guard = public.app.state.public_demo
    path = guard.database.path
    guard.budget([("AI_TOTAL", 0)])
    wid = upload(public).json()["id"]
    # Browser number inputs commonly submit 400 rather than 400.00.
    assert confirm(public, wid, {**invoice(), "total": "400"}).status_code == 202
    # A second public worker/process must refuse to multiply concurrency limits.
    with pytest.raises(RuntimeError, match="exactly one process"):
        create_app(path)
    guard.close()
    with TestClient(create_app(path)) as restarted:
        assert restarted.get(f"/api/workflows/{wid}").json()["status"] == "Approved"
        with restarted.app.state.service.database.connect() as db:
            assert db.execute("SELECT used FROM public_demo_budgets WHERE name='AI_TOTAL'").fetchone()[0] == 1


@pytest.mark.parametrize("origin", ["https://unrelated.example", "null"])
def test_public_cross_origin_posts_rejected(public, origin):
    response = public.post("/api/workflows", content=b"ignored", headers={"Origin": origin})
    assert response.status_code == 403


def test_existing_private_database_is_not_made_public(public, tmp_path):
    path = tmp_path / "private.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE private_data (value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('preserve')")
    before = path.read_bytes()
    assert initialize_database(path) is False
    with pytest.raises(RuntimeError, match="isolated synthetic"):
        create_app(path)
    assert path.read_bytes() == before


def test_private_documents_in_previously_public_workspace_refuse_startup(public):
    from app.documents import DocumentStore
    guard = public.app.state.public_demo
    store = DocumentStore(public.app.state.service.database)
    # Simulate private-mode use after the public marker was originally created.
    store.save((FIXTURES / "native_invoice.pdf").read_bytes() + b"\n% private variation")
    guard.close()
    with pytest.raises(RuntimeError, match="isolated synthetic"):
        create_app(guard.database.path)


@pytest.mark.parametrize("setting,value", [("ZAMP_REQUIRE_DEMO_AUTH", "1"), ("ZAMP_DEMO_USERNAME", "reviewer"), ("ZAMP_DEMO_PASSWORD", "x"*32)])
def test_explicit_private_auth_never_bypassed(public, monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(RuntimeError, match="conflicts"):
        create_app(public.app.state.service.database.path)
