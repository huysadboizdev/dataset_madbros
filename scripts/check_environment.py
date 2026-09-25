from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("== Kiem tra moi truong PDF Cleaner Tool ==")
    print(f"Python: {sys.version} ({sys.executable})")
    if sys.version_info[:2] != (3, 13):
        print("! Khuyen nghi dung D:\\OCR_Local\\.venv313 (Python 3.13)")
    ok = True
    for mod in ("fastapi", "uvicorn", "pydantic", "pypdfium2", "PIL", "paddleocr",
                "paddle", "paddlex", "pytest"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            print(f"  [OK] {mod} {v}")
        except Exception as e:
            ok = False
            print(f"  [THIU] {mod}: {e}")
    if ok:
        try:
            from paddleocr import PaddleOCRVL  # noqa: F401
            print("  [OK] class PaddleOCRVL nap duoc")
        except Exception as e:
            print(f"  [LOI] PaddleOCRVL: {e}")
            ok = False
    models = Path.home() / ".paddlex" / "official_models"
    for name in ("PaddleOCR-VL-1.6", "PP-DocLayoutV3"):
        p = models / name
        print(f"  [{'OK' if p.exists() else 'THIU'}] model cache: {p}")
        ok = ok and p.exists()
    _total, used, free = shutil.disk_usage(ROOT)
    print(f"  Đĩa còn trống ổ dự án: {free / 1e9:.1f} GB (cần >= 5 GB cho artifact/ảnh)")
    if free < 5e9:
        ok = False
    try:
        import os
        r = os.cpu_count()
        print(f"  CPU lo: {r}")
    except Exception:
        pass
    print("KET QUA:", "du dieu kien" if ok else "CON THIEU - xem [THIU]/[LOI] o tren")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
