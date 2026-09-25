from __future__ import annotations

"""F1 (dot 5) — kiem o muc TICH HOP: model thieu artifact BAT BUOC (shard duoc
`*.safetensors.index.json` tham chieu) thi:

- `JobManager._current_model_fp()` KHONG duoc tra tag thuc (phai la 'unresolved' ->
  cam moi cache READ/WRITE bang identity khong xac minh duoc);
- `/api/health.ocr_ready` KHONG duoc coi la ready;
- khi mo hinh day du tro lai thi tag lai resolved (khong giu 'unresolved' cu).
"""

import json
from pathlib import Path

from ..conftest import make_app


def _sharded_model_root(root: Path, *, shards: int) -> Path:
    """Model 'PP-DocLayoutV3' co index tham chieu 2 shard; chi tao `shards` shard that."""
    d = root / "PP-DocLayoutV3"
    d.mkdir(parents=True)
    (d / "config.json").write_text('{"m": "layout"}', encoding="utf-8")
    names = [f"model-{i:05d}-of-00002.safetensors" for i in (1, 2)]
    for i, name in enumerate(names[:shards], start=1):
        (d / name).write_bytes(bytes([i]) * 1024)
    (d / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"l1": names[0], "l2": names[1]}}), encoding="utf-8")
    # model thu hai (VL) day du de tach bach loi cua shard
    vl = root / "PaddleOCR-VL-1.6"
    vl.mkdir(parents=True)
    (vl / "config.json").write_text('{"m": "vl"}', encoding="utf-8")
    (vl / "model.safetensors").write_bytes(b"\x07" * 2048)
    return root


def test_manager_tag_unresolved_when_referenced_shard_missing(tmp_path, monkeypatch):
    root = _sharded_model_root(tmp_path / "models", shards=1)
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))
    app, _settings = make_app(tmp_path)
    fp = app.state.jobs._current_model_fp()
    assert fp["tag"] == "unresolved", "thieu shard bat buoc -> KHONG duoc tra tag thuc"
    detail = fp["full"]["PP-DocLayoutV3"]
    assert detail["status"] == "incomplete"
    assert detail["referenced"]["missing"] == [
        "model.safetensors.index.json->model-00002-of-00002.safetensors"]
    assert detail["status_reason"]


def test_health_not_ready_when_referenced_shard_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    root = _sharded_model_root(tmp_path / "models", shards=1)
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))
    app, _settings = make_app(tmp_path)
    with TestClient(app) as c:
        health = c.get("/api/health").json()
    assert health.get("ocr_ready") is False, "model khong day du -> health KHONG duoc ready"


def test_manager_tag_resolved_when_shards_present(tmp_path, monkeypatch):
    """Doi chieu: du shard -> tag resolved (chung minh ket qua tren la do shard thieu)."""
    root = _sharded_model_root(tmp_path / "models", shards=2)
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))
    app, _settings = make_app(tmp_path)
    fp = app.state.jobs._current_model_fp()
    assert fp["tag"] != "unresolved"
    assert fp["full"]["PP-DocLayoutV3"]["status"] == "ok"