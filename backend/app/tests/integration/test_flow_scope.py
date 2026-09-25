from __future__ import annotations

"""P01, P05, P11, P18: phạm vi xử lý là yêu cầu cao nhất —
chỉ đúng trang đã chọn đi vào extraction/render/OCR, job dừng ở trang cuối."""

from ..conftest import engine_dispatched, job_ops, make_pdf, start_job, upload, wait_status


def test_p01_only_selected_pages(client, tmp_path):
    doc = upload(client, pages=138)
    assert doc["page_count"] == 138
    job_id = start_job(client, doc["document_id"], [5, 6, 7])
    j = wait_status(client, job_id, ("COMPLETED",))
    assert j["status"] == "COMPLETED"
    assert j["succeeded_pages"] == 3

    engine_calls = engine_dispatched(client.dispatch_log_path)
    assert sorted(set(engine_calls)) == [5, 6, 7]  # worker chi nhan dung 3 trang
    ops = job_ops(client, job_id)
    touched = {o["page_no"] for o in ops}
    assert touched == {5, 6, 7}
    for forbidden in (4, 8, 9, 10, 137):
        assert forbidden not in touched  # khong doc ngoi trang 8 de OCR
    # moi trang phai co duong: dispatched -> render -> ocr_done -> committed
    for p in (5, 6, 7):
        seq = [o["op"] for o in ops if o["page_no"] == p]
        assert seq == ["dispatched", "render", "ocr_done", "committed"]


def test_p05_upload_does_not_start_ocr(client):
    doc = upload(client)
    doc2 = upload(client, name="khac.pdf", pages=139)  # noi dung khac -> tai lieu moi
    assert doc["document_id"] != doc2["document_id"]
    dup = client.post("/api/documents",
                      files={"file": ("trung.pdf", make_pdf(client.settings.project_root),
                                      "application/pdf")})
    assert dup.json()["duplicate"] is True
    assert dup.json()["document_id"] == doc["document_id"]  # mo lai file cu, khong nhan ban
    assert engine_dispatched(client.dispatch_log_path) == []  # khong co OCR tu dong


def test_p11_direct_text_layer(client):
    """P11 (trong that): trich TRUC TIEP tu lop chu PDF — KHONG render/OCR."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [20])
    j = wait_status(client, job_id, ("COMPLETED",))
    assert j["pages"][0]["method"] == "direct"
    page = client.get(f"/api/jobs/{job_id}/pages/20").json()
    text = " ".join(b["text"] or "" for b in page["blocks"])
    assert "mo ta dai" in text  # noi dung that, khong phai chi anh
    ops = [o["op"] for o in job_ops(client, job_id) if o["page_no"] == 20]
    assert "render" not in ops  # khong render/OCR khi lop chu tot va khong co anh
    assert engine_dispatched(client.dispatch_log_path) == []


def test_p11b_good_text_but_formula_in_image_forces_ocr(client):
    """P11 (trong that, lan 2): trang co lop chu NHUNG vung anh lon (cong thuc trong anh)
    -> khong duoc im lang trich text roi mat cong thuc: bat OCR dung trang nay."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [8])  # trang 8: text + anh 500x300pt
    j = wait_status(client, job_id, ("COMPLETED",))
    assert j["pages"][0]["method"] == "ocr"
    assert engine_dispatched(client.dispatch_log_path) == [8]  # chi dung trang 8
    seq = [o["op"] for o in job_ops(client, job_id) if o["page_no"] == 8]
    assert "render" in seq and "direct_extract" not in seq


def test_p11c_small_image_keeps_direct_but_flags(client):
    """Anh nho (logo/nep thu) khong ban thanh OCR bat buoc — giu direct + can kiem tra."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [21])  # text + anh 0.2% trang
    j = wait_status(client, job_id, ("COMPLETED", "COMPLETED_WITH_ERRORS"))
    assert j["pages"][0]["method"] == "direct"
    page = client.get(f"/api/jobs/{job_id}/pages/21").json()
    assert page["status"] == "NEEDS_REVIEW"
    assert any("SMALL_IMAGES" in i["description"] for i in page["issues"])
    assert engine_dispatched(client.dispatch_log_path) == []


def test_p18_non_contiguous_pages_kept_separate(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [5, 9])
    wait_status(client, job_id, ("COMPLETED",))
    exp = client.post(f"/api/jobs/{job_id}/exports?format=md")
    assert exp.status_code == 200
    eid = exp.json()["export_id"]
    r = client.get(f"/api/exports/{eid}/download")
    md = r.content.decode("utf-8")
    assert "## Trang PDF 5" in md and "## Trang PDF 9" in md
    assert "Ranh giới trang" in md  # khong tu noi doan qua trang chua chon
    assert "Bản trích xuất nháp" in md
