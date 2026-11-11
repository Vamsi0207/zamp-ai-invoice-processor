"""Deployment gates and initial-only seeding; no provider calls."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from scripts.container_start import initialize_database
from scripts import container_start


@pytest.fixture
def gated(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAMP_REQUIRE_DEMO_AUTH", "1")
    monkeypatch.setenv("ZAMP_DEMO_USERNAME", "reviewer")
    monkeypatch.setenv("ZAMP_DEMO_PASSWORD", "synthetic-test-password-32-characters")
    with TestClient(create_app(tmp_path / "test.sqlite3")) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/docs", "/openapi.json", "/api/configuration", "/api/master-data", "/documents/unknown", "/assets/example.js"])
def test_gate_covers_application(gated, path):
    response = gated.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("header", ["Basic !!!", "Bearer wrong", "Basic YWJj", "Basic /w=="])
def test_bad_authorization(gated, header):
    assert gated.get("/api/master-data", headers={"Authorization": header}).status_code == 401


def test_health_and_valid_auth(gated):
    assert gated.get("/health").json() == {"status": "ok"}
    assert gated.post("/health").status_code == 401
    assert gated.get("/api/configuration", auth=("reviewer", "wrong")).status_code == 401
    response = gated.get("/api/configuration", auth=("reviewer", "synthetic-test-password-32-characters"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-test-password" not in response.text


def test_upload_blocked_before_parsing_and_csrf(gated):
    assert gated.post("/documents", content=b"not a PDF").status_code == 401
    auth = ("reviewer", "synthetic-test-password-32-characters")
    for origin in ["https://evil.example", "null"]:
        assert gated.post("/documents", auth=auth, headers={"Origin": origin}).status_code == 403
    # Same-origin or explicit non-browser callers reach existing validation.
    assert gated.post("/documents", auth=auth, headers={"Origin": "http://testserver"}).status_code == 422
    assert gated.post("/documents", auth=auth).status_code == 422


@pytest.mark.parametrize("username,password", [("", ""), ("reviewer", "short"), ("", "x"*32), ("bad:name", "x"*32)])
def test_required_auth_fails_closed(monkeypatch, tmp_path, username, password):
    monkeypatch.setenv("ZAMP_REQUIRE_DEMO_AUTH", "1")
    monkeypatch.setenv("ZAMP_DEMO_USERNAME", username)
    monkeypatch.setenv("ZAMP_DEMO_PASSWORD", password)
    path = tmp_path / "not-created.sqlite3"
    with pytest.raises(RuntimeError, match="Demo access requires"):
        create_app(path)
    assert not path.exists()


def test_local_auth_optional(monkeypatch, tmp_path):
    for key in ["ZAMP_REQUIRE_DEMO_AUTH", "ZAMP_DEMO_USERNAME", "ZAMP_DEMO_PASSWORD"]:
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "local.sqlite3")) as client:
        assert client.get("/api/configuration").status_code == 200


def test_seed_only_new_database_preserves_changes(tmp_path):
    path = tmp_path / "new" / "demo.sqlite3"
    assert initialize_database(path) is True
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM invoices").fetchone()[0] == 0
        db.execute("UPDATE vendors SET name='Persisted reviewer edit'")
        db.execute("DELETE FROM receipts")
    assert initialize_database(path) is False
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM vendors").fetchone()[0] == "Persisted reviewer edit"
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_existing_empty_or_invalid_file_never_seeded(tmp_path):
    for content in [b"", b"not a database"]:
        path = tmp_path / str(len(content))
        path.write_bytes(content)
        assert initialize_database(path) is False
        assert path.read_bytes() == content


def test_container_start_contract(monkeypatch, tmp_path):
    path = tmp_path / "custom" / "demo.sqlite3"
    documents = tmp_path / "custom" / "pdfs"
    for key, value in {"ZAMP_REQUIRE_DEMO_AUTH": "0", "ZAMP_DEMO_USERNAME": "reviewer",
                       "ZAMP_DEMO_PASSWORD": "synthetic-test-password-32-characters",
                       "ZAMP_DB_PATH": str(path), "ZAMP_DOCUMENT_DIR": str(documents), "PORT": "9876"}.items():
        monkeypatch.setenv(key, value)
    # Don't change this test process's identity, permissions or executable.
    monkeypatch.setattr(container_start.os, "geteuid", lambda: 10001, raising=False)
    monkeypatch.setattr(container_start.os, "umask", lambda value: None)
    calls = []
    monkeypatch.setattr(container_start.os, "execvp", lambda *args: calls.append(args))
    container_start.main()
    assert path.exists() and documents.is_dir()
    assert container_start.os.environ["ZAMP_REQUIRE_DEMO_AUTH"] == "1"
    assert calls == [("python", ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                                "--port", "9876", "--workers", "1", "--no-access-log"])]
