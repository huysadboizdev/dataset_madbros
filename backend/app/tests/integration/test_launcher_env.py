from __future__ import annotations

"""S6: kiem check_interpreter.py chan loai 'chi file ton tai' va kiem /api/health
bao ocr_ready theo model tren dia (thieu model -> UI van mo, chi OCR bi chan)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from backend.app.settings import OcrSettings, Settings

ROOT = Path(__file__).resolve().parents[4]
CHECK = ROOT / "scripts" / "check_interpreter.py"


def _run_checker(py: str, *extra):
    return subprocess.run([sys.executable, str(CHECK), py, *extra],
                          capture_output=True, text=True, timeout=90)


def test_real_interpreter_accepts_self():
    r = _run_checker(sys.executable, "--no-paddle")
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and data["ok"] is True, r.stdout
    assert data["checks"]["version"] == "3.13"
    assert data["checks"]["bits64"] is True


def test_non_interpreter_file_rejected(tmp_path):
    bogus = tmp_path / "not_python.exe"
    bogus.write_bytes(b"MZ\x00\x00 random not an executable")
    r = _run_checker(str(bogus), "--no-paddle")
    assert r.returncode != 0
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert data["ok"] is False
    assert any("interpreter" in x or "chay" in x for x in data["reasons"]), data


def test_empty_path_rejected():
    r = _run_checker(str(Path("Z:\\definitely\\missing\\py.exe")), "--no-paddle")
    assert r.returncode != 0
    assert json.loads(r.stdout.strip().splitlines()[-1])["ok"] is False


def _health_for_model_root(tmp_path, monkeypatch, models_present: bool):
    root = tmp_path / "models"
    if models_present:
        # F1: 'ocr_ready' = ALL model can cho inference phai xac minh duoc -> fixture
        # phai co DU CA HAI (layout + VL); thieu mot model la KHONG san sang OCR.
        for name, blob in (("PP-DocLayoutV3", b"\x00" * 16),
                           ("PaddleOCR-VL-1.6", b"\x01" * 16)):
            d = root / name
            d.mkdir(parents=True)
            (d / "config.json").write_text("{}", encoding="utf-8")
            (d / "model.safetensors").write_bytes(blob)
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root if models_present else tmp_path / "empty"))
    settings = Settings(project_root=tmp_path, ocr=OcrSettings(render_dpi=72))
    settings.ensure_dirs()
    app = main_mod.create_app(settings, engine="fake")
    with TestClient(app) as c:
        return c.get("/api/health").json()


def test_health_reports_model_readiness(tmp_path, monkeypatch):
    ready = _health_for_model_root(tmp_path / "r", monkeypatch, True)
    assert ready["app"] == "ok" and ready["ocr_ready"] is True
    # thieu model: APP VAN MO (health ok), CHI bao OCR chua san sang
    missing = _health_for_model_root(tmp_path / "m", monkeypatch, False)
    assert missing["app"] == "ok" and missing["ocr_ready"] is False
    assert missing["engine_mode"] == "fake"
