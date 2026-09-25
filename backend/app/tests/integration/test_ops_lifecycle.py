from __future__ import annotations

"""S5: fault injection cho upload + temp + reconcile. Duong dan kiem bang that
(ENOSPC, upload gian doan, rename loi, DB commit loi sau rename, hard-kill giua render).
Chung to khong co raw orphan / .part / tmp con sot va khong bao 'thanh cong' khi loi.
Du dung fake engine + data dir tach rieng; KHONG phai bang chung OCR that."""

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from backend.app.api import documents as documents_api
from backend.app.services.job_service import JobManager
from backend.app.settings import OcrSettings, Settings

from ..conftest import build_fake_model_root, make_pdf, start_job, wait_status


def _fresh_app(tmp_path, model_root):
    import os
    os.environ.setdefault("PDFCLEANER_MODEL_ROOT", str(model_root))
    settings = Settings(project_root=tmp_path,
                        ocr=OcrSettings(render_dpi=72, page_timeout_s=90))
    settings.ensure_dirs()
    dlog = tmp_path / "d.log"
    app = main_mod.create_app(settings, engine="fake",
                              engine_extra_args=["--dispatch-log", str(dlog), "--page-delay", "0.05"])
    c = TestClient(app); c.__enter__()
    c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
    c.settings = settings; c.dispatch_log_path = dlog
    return c


def test_413_capacity_error_not_reported_success(tmp_path):
    """File vuoi gioi han -> 413 THAT, khong 'thanh cong' khong phan trang thieu."""
    root = tmp_path / "models"; build_fake_model_root(root)
    settings = Settings(project_root=tmp_path, input_max_mb=1,
                        ocr=OcrSettings(render_dpi=72))
    settings.ensure_dirs()
    app = main_mod.create_app(settings, engine="fake")
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        big = b"%PDF-1.4\n" + (b"x" * (2 * 1024 * 1024))  # 2MB > 1MB
        r = c.post("/api/documents", files={"file": ("big.pdf", big, "application/pdf")})
        assert r.status_code == 413
        assert r.json()["detail"]["code"] == "TOO_LARGE"
        # khong de lai file trong raw_dir khi vuoi gioi han
        assert list(settings.raw_dir.glob("*.pdf")) == []
        assert list(settings.raw_dir.glob("*.part")) == []


def test_rename_failure_cleans_part_no_raw(tmp_path, monkeypatch):
    root = tmp_path / "models"; build_fake_model_root(root)
    c = _fresh_app(tmp_path, root)
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(documents_api.os, "replace", boom)
    data = make_pdf(c.settings.project_root, pages=12)
    r = c.post("/api/documents", files={"file": ("a.pdf", data, "application/pdf")})
    assert r.status_code == 507 and r.json()["detail"]["code"] == "STORAGE_ERROR"
    assert list(c.settings.raw_dir.glob("*.part")) == []  # part da don
    assert list(c.settings.raw_dir.glob("*.pdf")) == []  # khong co raw
    c.__exit__(None, None, None)


def test_db_commit_failure_after_rename_rolls_back_raw(tmp_path, monkeypatch):
    root = tmp_path / "models"; build_fake_model_root(root)
    c = _fresh_app(tmp_path, root)
    db = c.app.state.db
    real_exec = db.execute
    def flaky(sql, params=()):
        if "INSERT INTO documents" in sql:
            raise sqlite3.OperationalError("simulated commit failure")
        return real_exec(sql, params)
    monkeypatch.setattr(db, "execute", flaky)
    data = make_pdf(c.settings.project_root, pages=12)
    with pytest.raises(Exception):
        c.post("/api/documents", files={"file": ("b.pdf", data, "application/pdf")})
    # raw vua rename PHAI bi rollback -> khong orphan
    assert list(c.settings.raw_dir.glob("*.pdf")) == []
    assert list(c.settings.raw_dir.glob("*.part")) == []
    assert db.query("SELECT 1 FROM documents") == []
    c.__exit__(None, None, None)


def test_cleanup_removes_raw_orphan_but_keeps_referenced(tmp_path):
    root = tmp_path / "models"; build_fake_model_root(root)
    c = _fresh_app(tmp_path, root)
    # upload that -> file raw duoc document tham chieu
    data = make_pdf(c.settings.project_root, pages=12)
    r = c.post("/api/documents", files={"file": ("ok.pdf", data, "application/pdf")})
    assert r.status_code == 200
    referenced = Path(r.json()["sha256"])  # not used
    raw_pdfs = list(c.settings.raw_dir.glob("*.pdf"))
    assert raw_pdfs
    # dat mot raw orphan (khong co DB row tro toi) + mot .part + mot tmp cua job cu
    orphan = c.settings.raw_dir / "doc_orphan.pdf"; orphan.write_bytes(b"%PDF-1.4\nx")
    (c.settings.raw_dir / "doc_x.part").write_bytes(b"junk")
    oldjob = c.settings.jobs_dir / "job_deadbeef" / "tmp"
    oldjob.mkdir(parents=True, exist_ok=True)
    (oldjob / "p0005_a3.png").write_bytes(b"stale-render")
    kept = list(c.settings.raw_dir.glob("*.pdf"))
    ref_names = {Path(row["raw_path"]).name for row in c.app.state.db.query("SELECT raw_path FROM documents")}
    removed = JobManager.cleanup_orphan_artifacts(c.app.state.db, c.settings)
    assert removed["raw_orphan"] >= 1 and removed["part"] >= 1 and removed["tmp"] >= 1
    # file cua document THAT van con (khong bao gio xoa du lieu duoc tham chieu)
    for f in kept:
        if f.name in ref_names:
            assert f.exists()
    assert not orphan.exists()
    assert not (oldjob / "p0005_a3.png").exists()
    c.__exit__(None, None, None)


def test_cleanup_keeps_tmp_of_running_job(tmp_path):
    root = tmp_path / "models"; build_fake_model_root(root)
    c = _fresh_app(tmp_path, root)
    # mo phong job dang RUNNING co file tmp cua attempt dang chay
    c.app.state.db.execute(
        "INSERT INTO documents(document_id,hash,raw_path,original_name,size_bytes,page_count,"
        "metadata_json,ingested_at) VALUES('d1','h1','p','n',1,10,'{}','now')")
    c.app.state.db.execute(
        "INSERT INTO jobs(job_id,document_id,selected_pages_json,pages_fingerprint,mode,ocr_again,"
        "config_hash,status,notes_json,created_at) VALUES('j_live','d1','[5]','5',"
        "'auto_text_formula',0,'cfg','RUNNING','{}','now')")
    tmp = c.settings.jobs_dir / "j_live" / "tmp"; tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "p0005_a1.png").write_bytes(b"in-progress")
    JobManager.cleanup_orphan_artifacts(c.app.state.db, c.settings)
    # job RUNNING -> tmp KHONG bi don (an toan cho attempt dang chay)
    assert (tmp / "p0005_a1.png").exists()
    c.__exit__(None, None, None)


def test_startup_reconcile_sweeps_stale_tmp(tmp_path):
    """Hard-kill lai: mo lai app -> reconcile -> tmp job INTERRUPTED bi don, khong mat revisions."""
    root = tmp_path / "models"; build_fake_model_root(root)
    settings = Settings(project_root=tmp_path, ocr=OcrSettings(render_dpi=72))
    settings.ensure_dirs()
    # tao DB gia voi job INTERRUPTED + 1 revision da commit + 1 tmp con sot
    app = main_mod.create_app(settings, engine="fake")
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        db = c.app.state.db
        db.execute("INSERT INTO documents VALUES('d1','h1',?,'n',1,10,'{}','now')",
                   (str(settings.raw_dir / "d1.pdf"),))
        (settings.raw_dir / "d1.pdf").write_bytes(b"%PDF-1.4\nx")
        db.execute("INSERT INTO jobs(job_id,document_id,selected_pages_json,pages_fingerprint,"
                   "mode,ocr_again,config_hash,status,notes_json,created_at) VALUES('j1','d1','[5]',"
                   "'5','auto_text_formula',0,'cfg','RUNNING','{}','now')")
        jtmp = settings.jobs_dir / "j1" / "tmp"; jtmp.mkdir(parents=True, exist_ok=True)
        (jtmp / "p0005_a1.png").write_bytes(b"stale")
        revdir = settings.jobs_dir / "j1" / "pages" / "0005" / "revisions"; revdir.mkdir(parents=True, exist_ok=True)
        rev = revdir / "rev_keep.json"; rev.write_text('{"ok":true}', encoding="utf-8")
        # dong app -> mo lai: reconcile danh dau INTERRUPTED, cleanup don tmp job do
    app2 = main_mod.create_app(settings, engine="fake")
    with TestClient(app2) as c2:
        assert c2.get(f"/api/jobs/j1").status_code in (200, 404)
        assert not (jtmp / "p0005_a1.png").exists(), "tmp sau hard-kill khong bi don"
        assert rev.exists(), "revision da commit KHONG duoc phep bi don"
        assert (settings.raw_dir / "d1.pdf").exists(), "raw duoc document tham chieu van con"
