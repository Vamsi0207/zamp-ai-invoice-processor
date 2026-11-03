import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.extraction import ExtractionResult, ProviderError
from app.workflows import Conflict, ReviewRequest, Workflows
from conftest import invoice
from test_documents import FIXTURES


def upload_run(client, provider="manual", key="upload-1", data=None):
    response = client.post("/api/workflows", files={"file": ("invoice.pdf", data or (FIXTURES / "native_invoice.pdf").read_bytes(), "application/pdf")},
                           data={"provider": provider, "idempotency_key": key})
    assert response.status_code == 202, response.text
    return client.get(f"/api/workflows/{response.json()['id']}").json()


def confirm(client, wid, body=None):
    return client.post(f"/api/workflows/{wid}/review", json={"invoice": body or invoice(),
                       "confirmed": True, "reviewer": "Demo Reviewer", "note": "Checked fields against source and master data"})


def test_manual_upload_review_decision_end_to_end(seeded):
    run = upload_run(seeded)
    assert run["status"] == "Review"
    assert run["stages"]["ai_extraction"]["status"] == "skipped"
    assert run["stages"]["validation"]["status"] == "needs_review"
    assert run["stages"]["decision"]["status"] == "pending"
    assert run["document"]["pages"][0]["method"] == "native"
    assert confirm(seeded, run["id"]).status_code == 202
    detail = seeded.get(f"/workflows/{run['id']}").json()
    assert detail["status"] == "Approved"
    assert detail["decision"]["decision"] == "Approved"
    assert detail["stages"]["decision"]["status"] == "completed"
    assert any(e["status"] == "confirmed" and "Demo Reviewer" in e["detail"] for e in detail["events"])
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 5000


def test_duplicate_upload_and_retry_no_double_allocation(seeded):
    first = upload_run(seeded)
    confirm(seeded, first["id"])
    second = upload_run(seeded, key="different-upload-key")
    assert second["id"] == first["id"]
    assert second["status"] == "Approved"
    assert confirm(seeded, first["id"]).status_code == 202
    assert seeded.post(f"/workflows/{first['id']}/retry", json={}).status_code == 202
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 5000
    with seeded.app.state.service.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 1


def test_idempotency_key_cannot_change_document(client):
    upload_run(client)
    response = client.post("/workflows", files={"file": ("another.pdf", b"%PDF-different", "application/pdf")},
                           data={"provider": "manual", "idempotency_key": "upload-1"})
    assert response.status_code == 409


@pytest.mark.parametrize("changes,decision,reason", [
    ({}, "Approved", "ALL_CHECKS_PASSED"),
    ({"total": "150", "lines": [{"po_line_id": "L1", "description": "Widgets", "quantity": 15, "unit_price": "10"}]}, "Rejected", "PO_BALANCE_EXCEEDED"),
    ({"total": "49"}, "Rejected", "INVALID_TOTAL"),
])
def test_workflow_financial_cases(seeded, changes, decision, reason):
    run = upload_run(seeded)
    assert confirm(seeded, run["id"], invoice(**changes)).status_code == 202
    result = seeded.get(f"/workflows/{run['id']}").json()
    assert result["status"] == decision
    assert reason in result["decision"]["reasons"]


def test_partial_invoicing_and_business_duplicate(seeded):
    for index, number in enumerate(("PART-1", "PART-2", "part 1")):
        data = (FIXTURES / "native_invoice.pdf").read_bytes() + f"\n% version {index}".encode()
        run = upload_run(seeded, key=f"k{index}", data=data)
        assert confirm(seeded, run["id"], invoice(number=number)).status_code == 202
        decision = seeded.get(f"/workflows/{run['id']}").json()["decision"]
        assert decision["decision"] == ("Rejected" if index == 2 else "Approved")
        if index == 2:
            assert "DUPLICATE_INVOICE" in decision["reasons"]
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 10000


def test_missing_po_and_invented_identifiers_require_review(seeded):
    run = upload_run(seeded)
    for changes in ({"po_id": None}, {"po_id": "INVENTED"}, {"vendor_id": "INVENTED"},
                    {"lines": [{"po_line_id": "INVENTED", "description": "A", "quantity": 1, "unit_price": "50"}]}):
        assert confirm(seeded, run["id"], invoice(**changes)).status_code == 422
    assert seeded.get(f"/workflows/{run['id']}").json()["status"] == "Review"
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 0


def test_confirmed_invoice_immutable(seeded):
    run = upload_run(seeded)
    confirm(seeded, run["id"])
    assert confirm(seeded, run["id"], invoice(number="changed")).status_code == 409


def test_failed_provider_persisted_and_manual_retry(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    run = upload_run(client, provider="gemini")
    assert run["status"] == "failed"
    assert run["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert run["stages"]["ai_extraction"]["status"] == "failed"
    response = client.post(f"/workflows/{run['id']}/retry", json={"provider": "manual"})
    assert response.status_code == 202
    run = client.get(f"/workflows/{run['id']}").json()
    assert run["status"] == "Review"
    assert run["attempt"] == 2
    assert run["error"] is None
    assert any(e["status"] == "failed" for e in run["events"])


def test_corrupt_pdf_failure_persisted(client):
    run = upload_run(client, data=b"%PDF-broken")
    assert run["status"] == "failed"
    assert run["error"]["code"] == "PDF_ERROR"
    assert run["stages"]["pdf_extraction"]["status"] == "failed"


def test_real_adapter_mocked_ai_pipeline_matching(client, monkeypatch):
    import httpx
    from app.extraction import AIAdapter
    from test_extraction import response_body
    from scripts.seed import seed
    seed(client.app.state.service.database.path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body("gemini")))) as http:
        client.app.state.adapter_factory = lambda provider: AIAdapter(provider, http)
        run = upload_run(client, provider="gemini")
    assert run["status"] == "Review"
    assert run["draft"]["vendor_id"] == "DEMO-VENDOR"
    assert run["draft"]["po_id"] == "DEMO-PO"
    assert run["draft"]["lines"][0]["po_line_id"] == "L1"
    assert run["matching"]["issues"] == ["HUMAN_CONFIRMATION_REQUIRED"]
    assert len(run["extraction"]["evidence"]) == 13
    assert confirm(client, run["id"], run["draft"]).status_code == 202
    assert client.get(f"/workflows/{run['id']}").json()["status"] == "Approved"


def test_missing_po_extraction_not_invented(seeded):
    workflows = seeded.app.state.workflows
    facts = {"vendor_reference": "V1", "po_number": None, "currency": "USD", "lines": []}
    draft, match = workflows.match({"invoice": facts})
    assert draft["po_id"] is None
    assert "PO_MAPPING_REQUIRED" in match["issues"]
    assert match["suggested_po_ids"] == ["PO1"]


def test_concurrent_review_only_creates_one_invoice(seeded):
    run = upload_run(seeded)
    request = ReviewRequest(invoice=invoice(), reviewer="A", note="Verified source", confirmed=True)
    workflows = seeded.app.state.workflows
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: workflows.review(run["id"], request), range(4)))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: workflows.execute(run["id"]), range(4)))
    with workflows.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 1


def test_restart_and_resume_after_committed_financial_result(seeded):
    run = upload_run(seeded)
    confirm(seeded, run["id"])
    workflows = seeded.app.state.workflows
    workflows.change(run["id"], "decision", "running", "Simulated lost response after allocation", status="processing")
    reopened = Workflows(workflows.service, workflows.documents, workflows.adapter_factory)
    reopened.recover()
    assert reopened.get(run["id"])["error"]["code"] == "INTERRUPTED"
    reopened.retry(run["id"])
    reopened.execute(run["id"])
    assert reopened.get(run["id"])["status"] == "Approved"
    assert workflows.service.po_balance("PO1")["allocated_cents"] == 5000


def test_dashboard_history_configuration_and_pdf(seeded, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-must-not-appear")
    run = upload_run(seeded)
    config = seeded.get("/api/configuration")
    assert config.json()["providers"]["gemini"]["configured"] is True
    assert "secret-must-not-appear" not in config.text
    assert seeded.get("/api/dashboard").json()["counts"]["Review"] == 1
    assert seeded.get("/api/workflows?limit=1").json()["total"] == 1
    assert seeded.get("/api/workflows?limit=0").status_code == 422
    assert seeded.get("/api/master-data").json()["purchase_orders"][0]["lines"][0]["received_quantity"] == 10
    assert seeded.get(f"/api/workflows/{run['id']}/pdf").content.startswith(b"%PDF-")
    assert seeded.get("/api/workflows/missing").status_code == 404


def test_financial_review_retry_after_receipt(seeded):
    with seeded.app.state.service.database.transaction() as db:
        db.execute("DELETE FROM receipts")
    run = upload_run(seeded)
    confirm(seeded, run["id"])
    detail = seeded.get(f"/workflows/{run['id']}").json()
    assert detail["status"] == "Review"
    assert "RECEIPT_SHORTFALL" in detail["decision"]["reasons"]
    seeded.post("/receipts", json={"id": "later", "po_id": "PO1", "po_line_id": "L1", "quantity": 10})
    seeded.post(f"/workflows/{run['id']}/retry", json={})
    assert seeded.get(f"/workflows/{run['id']}").json()["status"] == "Approved"
    assert seeded.get("/purchase-orders/PO1/balance").json()["allocated_cents"] == 5000


def test_ambiguous_vendor_name_never_auto_selects(seeded):
    seeded.post("/vendors", json={"id": "V2", "name": "Synthetic Supply Co"})
    draft, matching = seeded.app.state.workflows.match({"invoice": {"vendor_name": "Synthetic Supply Co"}})
    assert draft["vendor_id"] == ""
    assert "VENDOR_MAPPING_REQUIRED" in matching["issues"]
