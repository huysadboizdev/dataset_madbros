from __future__ import annotations

"""F2 (dot 5) — kiem o muc TICH HOP tren DUNG DUONG THAT:
`JobManager (pin identity) -> WorkerSupervisor -> worker process -> engine.load -> cache tag`.

Noi dung kiem:
- cache OCR chi duoc GHI duoi tag = identity do WORKER THUC DUNG full-verify, va tag do
  phai TRUNG tag manager da pin (khong con chuyen "worker self-hash roi van ghi duoi tag
  pin" nhu B4 dot 4);
- job da cache hit KHONG khoi tao/khong goi engine lan nua;
- worker bao identity KHAC pin -> trang FAIL ro rang (MODEL_IDENTITY_MISMATCH) va KHONG
  co file cache nao duoc ghi duoi tag cu;
- worker khong xac minh duoc identity -> giu ket qua OCR nhung KHONG ghi cache;
- pin file thieu/hong -> worker tu full-hash, manager doi chieu roi moi ghi cache.

Engine fake o day TINH DANH TINH THAT tren model root gia lap (xem `fake_engine.py`),
nen day khong phai test mock logic danh tinh.
"""

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from ..conftest import (build_fake_model_root, engine_dispatched, job_ops, make_app,
                        start_job, upload, wait_status)

_NAMES = ["PP-DocLayoutV3", "PaddleOCR-VL-1.6"]


def _new_client(tmp_path, extra):
    dlog = tmp_path / "engine_dispatch.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), *extra])
    c = TestClient(app)
    c.__enter__()
    c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
    c.dispatch_log_path = dlog
    c.settings = settings
    return c


def _model_root() -> Path:
    return Path(os.environ["PDFCLEANER_MODEL_ROOT"])


def _ops(client, job_id):
    return [o["op"] for o in job_ops(client, job_id)]


def _cache_files(client, doc, page=6):
    cache_dir = client.settings.data_dir / "cache" / "ocr" / doc["sha256"]
    return sorted(cache_dir.glob(f"p{page:04d}_*.json"))


def test_cache_written_under_worker_verified_identity(tmp_path):
    """Tag cache == identity do worker full-verify == tag manager da pin (F2)."""
    from backend.app.ocr import model_identity as mi
    c = _new_client(tmp_path, [])
    doc = upload(c)
    job = start_job(c, doc["document_id"], [6])
    wait_status(c, job, ("COMPLETED",))
    expect_tag = mi.identity_hash(_NAMES, _model_root(), full=True)
    files = _cache_files(c, doc)
    assert len(files) == 1, f"phai co dung 1 cache OCR, thay {[f.name for f in files]}"
    assert expect_tag in files[0].name, (
        f"cache phai nam duoi tag pin {expect_tag}, ten file = {files[0].name}")
    em = json.loads(files[0].read_text(encoding="utf-8"))["engine_meta"]
    assert em["disk_identity"] == expect_tag
    assert em["model_rev"] == expect_tag, "worker phai bao DUNG identity da pin"
    assert em["identity_source"] == "pinned_job"
    assert em["recheck"] == "inventory+size+full_sha256_all_artifacts"
    assert mi.worker_verified_tag(em) == expect_tag


def test_cache_hit_does_not_call_engine_again(tmp_path):
    """Cache hit khong duoc khoi tao/goi engine lan nua (khong hash/khong load lai)."""
    c = _new_client(tmp_path, [])
    doc = upload(c)
    j1 = start_job(c, doc["document_id"], [6])
    wait_status(c, j1, ("COMPLETED",))
    n1 = len(engine_dispatched(c.dispatch_log_path))
    assert n1 == 1
    j2 = start_job(c, doc["document_id"], [6])
    wait_status(c, j2, ("COMPLETED",))
    assert len(engine_dispatched(c.dispatch_log_path)) == n1, \
        "job thu hai phai dung cache, KHONG goi engine"
    by = {p["page_no"]: p for p in c.get(f"/api/jobs/{j2}").json()["pages"]}
    assert by[6]["method"] == "cached"
    assert "cache_hit" in _ops(c, j2)
    assert "identity_mismatch" not in _ops(c, j2)


def test_worker_identity_mismatch_fails_page_and_writes_no_cache(tmp_path):
    """F2 finding 3.2: worker bao identity KHAC pin (vi du resolve sang model khac) ->
    trang FAIL ro rang, KHONG duoc ghi cache duoi tag cu (va cung khong ghi duoi tag moi)."""
    from backend.app.ocr import model_identity as mi
    other_root = tmp_path / "other_models"
    build_fake_model_root(other_root, tag_seed="Z")
    other_fps = {n: mi.model_fingerprint(n, other_root, full=True) for n in _NAMES}
    other_tag = mi.identity_from_fps(list(other_fps.values()))
    ov = tmp_path / "override_mismatch.json"
    ov.write_text(json.dumps({"model_fp": other_fps, "model_rev": other_tag,
                              "identity_source": "override_mismatch"}), encoding="utf-8")
    c = _new_client(tmp_path, ["--fake-identity-override-file", str(ov)])
    doc = upload(c)
    job = start_job(c, doc["document_id"], [6])
    wait_status(c, job, ("COMPLETED_WITH_ERRORS",))
    page = c.get(f"/api/jobs/{job}/pages/6").json()
    assert page["status"] == "FAILED"
    assert "MODEL_IDENTITY_MISMATCH" in (page["error"] or "")
    assert _cache_files(c, doc) == [], "KHONG duoc ghi cache duoi tag cu"
    ops = _ops(c, job)
    assert "identity_mismatch" in ops
    assert "cache_write" not in ops


def test_worker_identity_unverified_keeps_result_without_cache(tmp_path):
    """Worker khong bao duoc identity full-verify -> giu ket qua nhung KHONG ghi cache
    (va job sau KHONG duoc coi la cache hit)."""
    ov = tmp_path / "override_unverified.json"
    ov.write_text(json.dumps({"model_rev_error": "override_boom"}), encoding="utf-8")
    c = _new_client(tmp_path, ["--fake-identity-override-file", str(ov)])
    doc = upload(c)
    job = start_job(c, doc["document_id"], [6])
    wait_status(c, job, ("COMPLETED",))
    page = c.get(f"/api/jobs/{job}/pages/6").json()
    assert page["status"] in ("SUCCEEDED", "NEEDS_REVIEW")
    assert _cache_files(c, doc) == [], "khong xac minh duoc identity -> khong ghi cache"
    assert "identity_unverified" in _ops(c, job)
    # job thu hai phai OCR lai (khong co cache de dung)
    j2 = start_job(c, doc["document_id"], [6])
    wait_status(c, j2, ("COMPLETED",))
    by = {p["page_no"]: p for p in c.get(f"/api/jobs/{j2}").json()["pages"]}
    assert by[6]["method"] == "ocr"


def test_broken_pin_file_worker_self_verifies_and_manager_matches(tmp_path):
    """Pin file thieu/hong: worker tu full-hash, manager DOI CHIEU tag truoc khi ghi
    cache — truong hop model khong doi thi tag van trung, khong bao mismatch gia."""
    from backend.app.ocr import model_identity as mi
    c = _new_client(tmp_path, [])
    doc = upload(c)
    r = c.post("/api/jobs", json={"document_id": doc["document_id"],
                                  "selected_pages": [6],
                                  "mode": "auto_text_formula", "ocr_again": False})
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    # Lam hong duong dan pin TRUOC khi start: dat mot THU MUC tai dung ten file pin
    pin_path = c.settings.jobs_dir / f"{job}.pinned_identity.json"
    pin_path.mkdir(parents=True, exist_ok=True)
    r2 = c.post(f"/api/jobs/{job}/start")
    assert r2.status_code == 200, r2.text
    wait_status(c, job, ("COMPLETED",))
    ops = _ops(c, job)
    assert "pinned_identity_write_failed" in ops, "ghi pin loi phai duoc ghi log ro"
    assert "pin_file_error" in ops, "worker phai bao file pin hong"
    assert "identity_mismatch" not in ops
    assert "identity_unverified" not in ops
    expect_tag = mi.identity_hash(_NAMES, _model_root(), full=True)
    files = _cache_files(c, doc)
    assert len(files) == 1 and expect_tag in files[0].name