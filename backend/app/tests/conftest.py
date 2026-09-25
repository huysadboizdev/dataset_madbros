from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402
from backend.app.settings import OcrSettings, Settings  # noqa: E402
from backend.app.tests.fixtures.make_pdf import make_simple_pdf  # noqa: E402

FINAL = ("COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "PAUSED", "INTERRUPTED", "FAILED")


def build_fake_model_root(root: Path, *, tag_seed: str = "A") -> Path:
    """Tao thu muc model GIA LAP (PP-DocLayoutV3 + PaddleOCR-VL-1.6) voi artifact that
    de danh tinh cache tinh duoc ma can model that. Thay noi dung -> doi fingerprint."""
    for name in ("PP-DocLayoutV3", "PaddleOCR-VL-1.6"):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps({"m": name, "seed": tag_seed}), encoding="utf-8")
        (d / "inference.yml").write_text(f"seed: {tag_seed}\nmodel: {name}\n", encoding="utf-8")
        # 'weights' nho de head-read bao toan bo file (moi noi dung doi -> fp doi)
        (d / "model.safetensors").write_bytes((tag_seed * 1024).encode("ascii"))
    return root


@pytest.fixture(autouse=True, scope="session")
def _isolate_model_root(tmp_path_factory):
    """Test dung fake engine nen danh tinh model phai LA HIEN + on dinh, doc lap
    may. Tro PDFCLEANER_MODEL_ROOT toi thu muc gia lap cho ca phien test."""
    root = tmp_path_factory.mktemp("models")
    build_fake_model_root(root)
    old = os.environ.get("PDFCLEANER_MODEL_ROOT")
    os.environ["PDFCLEANER_MODEL_ROOT"] = str(root)
    try:
        yield root
    finally:
        if old is None:
            os.environ.pop("PDFCLEANER_MODEL_ROOT", None)
        else:
            os.environ["PDFCLEANER_MODEL_ROOT"] = old


def make_settings(tmp_path: Path) -> Settings:
    s = Settings(project_root=tmp_path,
                 ocr=OcrSettings(render_dpi=72, page_timeout_s=90))
    s.ensure_dirs()
    return s


def make_pdf(tmp_path: Path, pages: int = 140) -> bytes:
    p = tmp_path / "fixture_book.pdf"
    make_simple_pdf(p, page_count=pages, text_pages={1, 20, 21, 8},
                    formula_pages={138}, image_pages={8}, small_image_pages={21})
    return p.read_bytes()


def make_app(tmp_path: Path, engine_extra: list[str] | None = None):
    settings = make_settings(tmp_path)
    extra = list(engine_extra or [])
    app = create_app(settings, engine="fake", engine_extra_args=extra)
    return app, settings


@pytest.fixture()
def client(tmp_path):
    dlog = tmp_path / "engine_dispatch.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--page-delay", "0.1"])
    with TestClient(app) as c:
        token = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": token})
        c.dispatch_log_path = dlog
        c.settings = settings
        yield c


def engine_dispatched(dlog: Path) -> list[int]:
    import json
    if not dlog.exists():
        return []
    return [json.loads(line)["page_no"] for line in dlog.read_text(encoding="utf-8").splitlines()]


def job_ops(client, job_id: str) -> list[dict]:
    import json
    log = client.settings.jobs_dir / job_id / "dispatch_log.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def upload(client, pages: int = 140, name: str = "fixture_book.pdf") -> dict:
    data = make_pdf(client.settings.project_root, pages)
    r = client.post("/api/documents", files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def wait_status(client, job_id: str, statuses, timeout: float = 90.0) -> dict:
    if isinstance(statuses, str):
        statuses = (statuses,)
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in statuses:
            return j
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} khong dat {statuses}; cuoi cung={j['status']}")


def start_job(client, doc_id: str, pages: list[int], ocr_again: bool = False) -> str:
    r = client.post("/api/jobs", json={"document_id": doc_id, "selected_pages": pages,
                                       "mode": "auto_text_formula", "ocr_again": ocr_again})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    r2 = client.post(f"/api/jobs/{job_id}/start")
    assert r2.status_code == 200, r2.text
    return job_id
