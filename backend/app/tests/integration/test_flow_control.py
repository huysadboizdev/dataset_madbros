from __future__ import annotations

"""P06-P10, P12, P15: pause/cancel/resume/retry, doi soat sau restart, cache, loi trang."""

import json
import time

from backend.app.db import Database
from backend.app.services.job_service import JobManager

from ..conftest import engine_dispatched, job_ops, make_app, make_pdf, start_job, upload, wait_status


def _wait_page_op(client, job_id, page_no, op, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(o["page_no"] == page_no and o["op"] == op
               for o in job_ops(client, job_id)):
            return True
        time.sleep(0.05)
    return False


def test_p06_pause_then_resume(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [5, 6, 7, 8, 9, 10])
    assert _wait_page_op(client, job_id, 6, "dispatched")
    r = client.post(f"/api/jobs/{job_id}/pause")
    assert r.status_code == 200
    j = wait_status(client, job_id, ("PAUSED",))
    assert j["status"] == "PAUSED"
    # khong bat dau trang 7 truoc khi resume
    assert 7 not in [o["page_no"] for o in job_ops(client, job_id)]
    r = client.post(f"/api/jobs/{job_id}/resume")
    assert r.status_code == 200
    j = wait_status(client, job_id, ("COMPLETED",))
    assert j["succeeded_pages"] == 6
    assert sorted(set(engine_dispatched(client.dispatch_log_path))) == \
        list(range(5, 11))


def test_p07_cancel_now_keeps_completed(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [5, 6, 7])
    assert _wait_page_op(client, job_id, 5, "committed")
    client.post(f"/api/jobs/{job_id}/cancel")
    j = wait_status(client, job_id, ("CANCELLED",))
    assert j["succeeded_pages"] >= 1  # trang da xong con nguyen
    dispatched = {o["page_no"] for o in job_ops(client, job_id)}
    assert dispatched <= {5, 6, 7}
    assert 8 not in dispatched
    # khong trang nao o trang thai RUNNING sau khi huy
    assert all(p["status"] != "RUNNING" for p in j["pages"])


def test_p15_one_page_error_completes_with_errors(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [5, 6, 7])
    # trang 6 loi: chuan bi bang cache fail khong the; thay vao do, kiem tra bang retry sau
    j = wait_status(client, job_id, ("COMPLETED",))
    assert j["succeeded_pages"] == 3
    # mo app thu hai voi fail_pages=6 tren cung job ko duoc; kiem tra retry path
    r = client.post(f"/api/jobs/{job_id}/retry", json={"page_no": 5})
    assert r.status_code == 422  # khong retry duoc trang thanh cong


def test_p15_real_error_page(tmp_path):
    from fastapi.testclient import TestClient
    dlog = tmp_path / "engine_dispatch.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--fail-pages", "6"])
    with TestClient(app) as c:
        token = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": token})
        c.dispatch_log_path = dlog
        c.settings = settings
        doc = upload(c)
        job_id = start_job(c, doc["document_id"], [5, 6, 7])
        j = wait_status(c, job_id, ("COMPLETED_WITH_ERRORS",))
        assert j["failed_pages"] == 1
        assert j["succeeded_pages"] == 2
        page6 = c.get(f"/api/jobs/{job_id}/pages/6").json()
        assert page6["status"] == "FAILED" and "OCR_FAILED" in (page6["error"] or "")
        # retry chi trang loi
        r = c.post(f"/api/jobs/{job_id}/retry", json={"page_no": 6})
        assert r.status_code == 200
        # lan 2 van fail vi fail-pages gi nguyên -> that bai lan nua, khong vong lap vo han
        j = wait_status(c, job_id, ("COMPLETED_WITH_ERRORS",))
        assert j["failed_pages"] == 1


def test_p08_restart_reconcile(tmp_path):
    db = Database(tmp_path / "t.db")
    db.execute("INSERT INTO documents VALUES('d1','h1','p','n',1,10,'{}','now')")
    db.execute("INSERT INTO jobs(job_id,document_id,selected_pages_json,pages_fingerprint,"
               "mode,ocr_again,config_hash,status,notes_json,created_at)"
               " VALUES('j1','d1','[5,6,7]','5,6,7','auto_text_formula',0,'cfg','RUNNING','{}','now')")
    db.execute("INSERT INTO page_runs(job_id,page_no,status) VALUES('j1',5,'SUCCEEDED')")
    db.execute("INSERT INTO page_runs(job_id,page_no,status) VALUES('j1',6,'RUNNING')")
    db.execute("INSERT INTO page_runs(job_id,page_no,status) VALUES('j1',7,'PENDING')")
    ids = JobManager.reconcile_on_boot(db)
    assert ids == ["j1"]
    job = db.get_job("j1")
    assert job["status"] == "INTERRUPTED"
    rows = {r["page_no"]: r["status"] for r in db.list_page_runs("j1")}
    assert rows == {5: "SUCCEEDED", 6: "INTERRUPTED", 7: "PENDING"}
    # khong tu chay lai: khong co worker nao duoc sinh; page 5 giu nguyen


def test_p09_cache_same_config(tmp_path):
    from fastapi.testclient import TestClient
    dlog1 = tmp_path / "e1.log"
    app1, settings = make_app(tmp_path, ["--dispatch-log", str(dlog1)])
    with TestClient(app1) as c:
        tok = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": tok})
        c.dispatch_log_path = dlog1
        c.settings = settings
        doc = upload(c)
        job1 = start_job(c, doc["document_id"], [6])
        wait_status(c, job1, ("COMPLETED",))
    dlog2 = tmp_path / "e2.log"
    app2, _ = make_app(tmp_path, ["--dispatch-log", str(dlog2)])
    with TestClient(app2) as c:
        tok = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": tok})
        c.dispatch_log_path = dlog2
        c.settings = settings
        job2 = start_job(c, doc["document_id"], [6])
        j = wait_status(c, job2, ("COMPLETED",))
        assert j["pages"][0]["method"] == "cached"
        assert engine_dispatched(dlog2) == []  # khong OCR lai ngoai y muon
        page = c.get(f"/api/jobs/{job2}/pages/6").json()
        assert "gia dinh" in page["blocks"][0]["text"]


def test_p10_reprocess_new_revision(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    rev0 = page["revision_id"]
    # sua tay
    blocks = page["blocks"]
    blocks[0]["text"] = "BAN SUA TAY CUA NGUOI DUNG"
    r = client.patch(f"/api/jobs/{job_id}/pages/6",
                     json={"base_revision_id": rev0, "blocks": blocks})
    assert r.status_code == 200
    rev1 = r.json()["revision_id"]
    # OCR lai: tao revision moi, KHONG ghi de ban dang dung
    r = client.post(f"/api/jobs/{job_id}/pages/6/reprocess")
    assert r.status_code == 200
    deadline = time.time() + 60
    while time.time() < deadline:
        st = client.get(f"/api/jobs/{job_id}/pages/6").json()["reprocess_state"]
        if st == "done":
            break
        time.sleep(0.1)
    assert st == "done"
    revs = client.get(f"/api/jobs/{job_id}/pages/6/revisions").json()["items"]
    assert len(revs) == 3
    active = [x for x in revs if x["active"]]
    assert active[0]["revision_id"] == rev1  # van la ban sua
    # so sanh roi moi thay ban dang dung
    ocr_revs = [x for x in revs if x["kind"] == "ocr_reprocess"]
    r = client.post(f"/api/jobs/{job_id}/pages/6/use_revision?revision_id={ocr_revs[0]['revision_id']}")
    assert r.status_code == 200
    assert r.json()["revision_id"] == ocr_revs[0]["revision_id"]


def test_p12_image_without_text(client, tmp_path):
    tpl = tmp_path / "tpl.json"
    tpl.write_text(json.dumps({"6": []}), encoding="utf-8")
    # tao app moi voi template trang 6 rong
    from fastapi.testclient import TestClient
    dlog = tmp_path / "e.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog),
                                        "--block-template", str(tpl)])
    with TestClient(app) as c:
        tok = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": tok})
        c.dispatch_log_path = dlog
        c.settings = settings
        doc = upload(c)
        job_id = start_job(c, doc["document_id"], [6])
        j = wait_status(c, job_id, ("COMPLETED",))
        assert j["failed_pages"] == 0
        page = c.get(f"/api/jobs/{job_id}/pages/6").json()
        # anh khong co chu: tra rong hop le, KHONG that bai, KHONG bia text;
        # trang thai /ghi chu phu hop (NEEDS_REVIEW de nguoi kiem tra, theo muc 5.2)
        assert page["status"] == "NEEDS_REVIEW"
        assert page["blocks"] == []
        assert any(i["type"] == "NO_CONTENT_DETECTED" for i in page["issues"])
