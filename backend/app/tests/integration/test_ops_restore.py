from __future__ import annotations

"""Phat hien 7 (van hanh Windows): backup = copy nguyen thu muc `data`, restore
mo lai tren ban copy — document/job/revision/xuat van nguyen, khong mat trang
da luu, khong tu OCR them.

Dung fake engine; day la test duong dan luu tru, khong phai bang chung OCR that."""

import shutil
import time

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.settings import OcrSettings, Settings

from ..conftest import make_settings, start_job, upload, wait_status


def _client_for(settings: Settings, dlog):
    extra = ["--dispatch-log", str(dlog), "--page-delay", "0.05"]
    app = create_app(settings, engine="fake", engine_extra_args=extra)
    c = TestClient(app)
    c.__enter__()
    tok = c.get("/api/session").json()["token"]
    c.headers.update({"x-pdfcleaner-token": tok})
    c.settings = settings
    c.dispatch_log_path = dlog
    return c


def test_backup_restore_copy_data_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    settings_a = make_settings(src)
    dlog_a = tmp_path / "a.log"
    c = _client_for(settings_a, dlog_a)
    try:
        doc = upload(c)
        did = doc["document_id"]
        job_id = start_job(c, did, [5, 6])
        wait_status(c, job_id, ("COMPLETED",))
        # sua tay mot trang -> revision + artifact nam trong data/
        page = c.get(f"/api/jobs/{job_id}/pages/6").json()
        page["blocks"][0]["text"] = "BAN SUA TRUOC KHI BACKUP"
        r = c.patch(f"/api/jobs/{job_id}/pages/6",
                    json={"base_revision_id": page["revision_id"],
                          "blocks": page["blocks"]})
        assert r.status_code == 200
        exp = c.post(f"/api/jobs/{job_id}/exports?format=zip").json()
        original_export = exp["export_id"]
    finally:
        c.__exit__(None, None, None)  # dong clean -> WAL checkpoint

    # BACKUP: copy nguyen thu muc data/ sang cho moi
    restored = tmp_path / "restored"
    shutil.copytree(src / "data", restored / "data")

    # RESTORE: mo app khac tro toi data_root ban copy, KHONG OCR lai
    settings_b = Settings(project_root=tmp_path,
                          ocr=OcrSettings(render_dpi=72, page_timeout_s=90),
                          data_root_override=restored / "data")
    settings_b.ensure_dirs()
    dlog_b = tmp_path / "b.log"
    c2 = _client_for(settings_b, dlog_b)
    try:
        docs = c2.get("/api/documents").json()["items"]
        assert any(d["document_id"] == did for d in docs)
        j = c2.get(f"/api/jobs/{job_id}").json()
        assert j["status"] == "COMPLETED"
        assert j["succeeded_pages"] == 2
        p6 = c2.get(f"/api/jobs/{job_id}/pages/6").json()
        assert p6["review_status"] == "edited"
        assert "BAN SUA TRUOC KHI BACKUP" in p6["blocks"][0]["text"]
        # export cu van tai duoc (artifact duoc copy theo)
        dl = c2.get(f"/api/exports/{original_export}/download")
        assert dl.status_code == 200
        # tai du lieu khong tu sinh OCR (fake dispatch log trong)
        time.sleep(0.2)
        assert not dlog_b.exists() or dlog_b.read_text(encoding="utf-8").strip() == ""
    finally:
        c2.__exit__(None, None, None)
