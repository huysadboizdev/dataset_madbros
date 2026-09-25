from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class OcrSettings:
    engine: str = "paddleocr_vl"
    device: str = "cpu"
    pipeline_version: str = "v1.6"
    layout_model_name: str = "PP-DocLayoutV3"
    vl_rec_model_name: str = "PaddleOCR-VL-1.6"
    render_dpi: int = 200
    page_timeout_s: int = 600
    worker_idle_unload_s: int = 300


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    input_max_mb: int = 200
    preview_dpi: int = 96
    ocr: OcrSettings = field(default_factory=OcrSettings)
    project_root: Path = PROJECT_ROOT
    data_root_override: Path | None = None

    @property
    def data_dir(self) -> Path:
        if self.data_root_override is not None:
            return self.data_root_override
        return self.project_root / self._data_rel

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def preview_dir(self) -> Path:
        return self.data_dir / "preview"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    _data_rel: str = "data"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.raw_dir, self.jobs_dir, self.tmp_dir,
                  self.exports_dir, self.preview_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or (PROJECT_ROOT / "config.json")
    raw: dict = {}
    if path.exists():
        # utf-8-sig: nguoi dung Windows hay luu .json bang Notepad/PowerShell -> co BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    ocr_raw = raw.get("ocr", {})
    ocr = OcrSettings(
        engine=ocr_raw.get("engine", OcrSettings.engine),
        device=ocr_raw.get("device", OcrSettings.device),
        pipeline_version=ocr_raw.get("pipeline_version", OcrSettings.pipeline_version),
        layout_model_name=ocr_raw.get("layout_model_name", OcrSettings.layout_model_name),
        vl_rec_model_name=ocr_raw.get("vl_rec_model_name", OcrSettings.vl_rec_model_name),
        render_dpi=int(ocr_raw.get("render_dpi", OcrSettings.render_dpi)),
        page_timeout_s=int(ocr_raw.get("page_timeout_s", OcrSettings.page_timeout_s)),
        worker_idle_unload_s=int(ocr_raw.get("worker_idle_unload_s", OcrSettings.worker_idle_unload_s)),
    )
    env_prefix = "PDFCLEANER_"
    port = int(os.environ.get(env_prefix + "PORT", raw.get("port", Settings.port)))
    host = os.environ.get(env_prefix + "HOST", raw.get("host", Settings.host))
    s = Settings(
        host=host,
        port=port,
        input_max_mb=int(raw.get("input_max_mb", Settings.input_max_mb)),
        preview_dpi=int(raw.get("preview_dpi", Settings.preview_dpi)),
        ocr=ocr,
        project_root=PROJECT_ROOT,
        _data_rel=os.environ.get(env_prefix + "DATA", raw.get("data_dir", "data")),
    )
    s.ensure_dirs()
    return s
