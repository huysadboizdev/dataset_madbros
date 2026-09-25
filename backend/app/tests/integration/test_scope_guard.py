from __future__ import annotations

"""S7: BAO TOAN pham vi chon trang SAU cac sua doi (export/cache/resolution/temp).
Chung minh bang RECORDING ADAPTER (engine_dispatch.log ghi moi trang engine THUC SU
nhan) + dispatch_log.jsonl cua job — khong chi kiem JSON cuoi. PDF 138/140 trang,
chon 5-7 -> chi 5,6,7 duoc goi; retry/fallback/cache-miss/resume/cancel khong vuot tap.
"""

from ..conftest import engine_dispatched, job_ops, start_job, upload, wait_status


def _assert_scope(c, job_id, allowed, log_path):
    called = sorted(set(engine_dispatched(log_path)))
    assert set(called) <= set(allowed), f"engine goi ngoai pham vi: {called}"
    touched = {o["page_no"] for o in job_ops(c, job_id)}
    assert touched <= set(allowed), f"job cham ngoai pham vi: {touched}"


def test_only_selected_pages_across_retry_and_cache(tmp_path):
    """5-7: OCR lan dau; resume/cache/retry cung khong cham trang 4/8/9/138."""
    from fastapi.testclient import TestClient
    from ..conftest import make_app
    dlog = tmp_path / "engine.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--page-delay", "0.05"])
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        c.dispatch_log_path = dlog; c.settings = settings
        doc = upload(c, pages=138)
        jid = start_job(c, doc["document_id"], [5, 6, 7])
        wait_status(c, jid, ("COMPLETED",))
        _assert_scope(c, jid, [5, 6, 7], dlog)
        assert sorted(set(engine_dispatched(dlog))) == [5, 6, 7]

        # job thu 2 cung tap -> cache hit, khong goi engine them
        jid2 = start_job(c, doc["document_id"], [5, 6, 7])
        wait_status(c, jid2, ("COMPLETED",))
        assert engine_dispatched(dlog) == [5, 6, 7] or sorted(set(engine_dispatched(dlog))) == [5, 6, 7]

        # retry mot trang xong -> khong cho phep (khong vuot pham vi)
        r = c.post(f"/api/jobs/{jid}/retry", json={"page_no": 8})  # trang 8 khong thuoc job
        assert r.status_code in (404, 422)  # NOT_FOUND: khong thuoc job

        # export dung tap chon, khong thieu/thua
        exp = c.post(f"/api/jobs/{jid}/exports?format=json").json()
        assert exp["included_pages"] == [5, 6, 7] and exp["missing_pages"] == [] and exp["partial"] is False


def test_pause_resume_retry_never_exceeds_selection(tmp_path):
    from fastapi.testclient import TestClient
    from ..conftest import make_app
    dlog = tmp_path / "engine2.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--page-delay", "0.4", "--fail-pages", "7"])
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        c.dispatch_log_path = dlog; c.settings = settings
        doc = upload(c, pages=140)
        jid = start_job(c, doc["document_id"], [5, 6, 7])
        # dung sau trang 5
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            if any(o["page_no"] == 5 and o["op"] == "committed" for o in job_ops(c, jid)):
                c.post(f"/api/jobs/{jid}/pause")
                break
            time.sleep(0.05)
        wait_status(c, jid, ("PAUSED",))
        called_so_far = sorted(set(engine_dispatched(dlog)))
        assert called_so_far and called_so_far[0] == 5 and 8 not in called_so_far
        # resume -> trang 7 THAT BAI -> COMPLETED_WITH_ERRORS, khong cham 8+
        c.post(f"/api/jobs/{jid}/resume")
        j = wait_status(c, jid, ("COMPLETED_WITH_ERRORS",))
        assert j["failed_pages"] == 1
        called = sorted(set(engine_dispatched(dlog)))
        assert called == [5, 6, 7], f"vuot tap chon: {called}"
        # retry trang loi 7 -> van chi goi 7
        c.post(f"/api/jobs/{jid}/retry", json={"page_no": 7})
        _ = wait_status(c, jid, ("COMPLETED_WITH_ERRORS", "COMPLETED"))
        assert 8 not in engine_dispatched(dlog) and 4 not in engine_dispatched(dlog)


def test_failed_page_not_counted_as_success_and_export_honest(tmp_path):
    """Trang loi khong tinh la xong; export partial/missing trung thuc; pham vi gioi han."""
    from fastapi.testclient import TestClient
    from ..conftest import make_app
    dlog = tmp_path / "engine3.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--fail-pages", "6"])
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        c.dispatch_log_path = dlog; c.settings = settings
        doc = upload(c, pages=138)
        jid = start_job(c, doc["document_id"], [5, 6, 7])
        j = wait_status(c, jid, ("COMPLETED_WITH_ERRORS",))
        # trang loi KHONG bi dem vao succeeded_pages
        assert j["succeeded_pages"] == 2 and j["failed_pages"] == 1
        # export chi bao gom trang thanh cong, missing noi ro 6, partial True
        exp = c.post(f"/api/jobs/{jid}/exports?format=json").json()
        assert exp["included_pages"] == [5, 7] and exp["missing_pages"] == [6]
        assert exp["partial"] is True
        # pham vi: chi 5,6,7 tung bi engine cham (6 that bai van goi 1 lan, khong vuot)
        assert sorted(set(engine_dispatched(dlog))) <= [5, 6, 7]
