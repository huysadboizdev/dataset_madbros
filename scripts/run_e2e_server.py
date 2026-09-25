from __future__ import annotations

"""Chay backend phuc vu UI da build, voi FAKE engine va data tam rieng.

Chi dung cho Playwright E2E (duoc danh dan qua PDFCLEANER_E2E=1). Khong cham data that.
Dong vai tro test backend + frontend tinh ghep qua HTTP that.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402
from backend.app.settings import OcrSettings, Settings  # noqa: E402


def main() -> int:
    if os.environ.get("PDFCLEANER_E2E") != "1":
        print("! Scripts nay chi danh cho E2E (dat PDFCLEANER_E2E=1).")
        return 2
    # data dir on dinh (test hard-kill/reopen) neu duoc truyen; mac dinh: tam dung 1 lan
    data_dir = Path(os.environ.get("PDFCLEANER_E2E_DATA")
                    or tempfile.mkdtemp(prefix="pdfcleaner_e2e_"))
    dlog = data_dir / "engine_dispatch.log"
    if os.environ.get("PDFCLEANER_E2E_FRESH") == "1" and dlog.exists():
        dlog.unlink()
    port = int(os.environ.get("PDFCLEANER_PORT", "8899"))
    delay = os.environ.get("PDFCLEANER_E2E_DELAY", "0.02")
    fixture = ROOT / "frontend" / "tests" / "fixtures" / "book.pdf"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    if not fixture.exists():
        from backend.app.tests.fixtures.make_pdf import make_simple_pdf
        make_simple_pdf(fixture, page_count=140, text_pages={1, 20, 21, 8},
                        formula_pages={138}, image_pages={8}, small_image_pages={21})

    settings = Settings(host="127.0.0.1", port=port, project_root=ROOT,
                        ocr=OcrSettings(render_dpi=72, page_timeout_s=60),
                        data_root_override=data_dir / "appdata")
    settings.ensure_dirs()
    extra = ["--dispatch-log", str(dlog), "--page-delay", delay]
    tpl = ROOT / "frontend" / "tests" / "fixtures" / "formula_blocks.json"
    if tpl.exists():
        extra += ["--block-template", str(tpl)]
    os.environ.setdefault("PDFCLEANER_FIXTURE", str(fixture))
    app = create_app(settings, engine="fake", engine_extra_args=extra)
    print(json.dumps({"port": port, "data_dir": str(data_dir), "dispatch_log": str(dlog),
                      "fixture": str(fixture)}))
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
