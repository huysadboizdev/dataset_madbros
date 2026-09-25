from __future__ import annotations

"""Benchmark OCR that trang: TAI SU DUNG page_selection va adapter cua ung dung.

Khong co pipeline phu -> khong the OCR ngoai pham vi.
Vi du:
  python scripts/benchmark_pages.py --input "input/test.pdf" --pages "5-7" --device cpu
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.cleaning.normalize import normalize_blocks  # noqa: E402
from backend.app.ocr.paddle_adapter import PaddleVLAdapter  # noqa: E402
from backend.app.services import pdf_service  # noqa: E402
from backend.app.services.page_selection import parse_page_expression  # noqa: E402
from backend.app.settings import OcrSettings  # noqa: E402


def peak_ram_mb_windows() -> float:
    import ctypes
    from ctypes import wintypes

    class Counter(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    cnt = Counter()
    cnt.cb = ctypes.sizeof(cnt)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    handle = k32.GetCurrentProcess()
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counter), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo(handle, ctypes.byref(cnt), cnt.cb)
    return cnt.PeakWorkingSetSize / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--pages", required=True, help="Bieu thuc trang 1-based: '5-7,10'")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--dump", default=None, help="Thu muc luu ket qua raw de doi chieu")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"Khong tim thay {src}")
        return 1
    with pdf_service.PdfDoc(src) as pdf:
        page_count = pdf.page_count
    pages = parse_page_expression(args.pages, page_count, allow_all=True)
    print(f"PDF {src.name}: {page_count} trang. Benchmark DUNG {len(pages)} trang: {pages}")
    if len(pages) > 8:
        print("! De nghich benchmark <= 8 trang. Huy.")
        return 1

    dump_dir = Path(args.dump) if args.dump else ROOT / "docs" / "benchmark_dump"
    dump_dir.mkdir(parents=True, exist_ok=True)

    adapter = PaddleVLAdapter(OcrSettings(device=args.device, render_dpi=args.dpi))
    t0 = time.time()
    meta = adapter.load()
    load_s = round(time.time() - t0, 1)
    print(f"Nap model: {load_s}s | {json.dumps(meta, ensure_ascii=False)}")

    rows = []
    with pdf_service.PdfDoc(src) as pdf:
        for p in pages:
            png_path = dump_dir / f"page_{p:04d}.png"
            png_path.write_bytes(pdf.render_page_png(p, args.dpi))
            text_layer = pdf.extract_page_text(p)
            t1 = time.time()
            res = adapter.recognize_page(png_path, p)
            dt = round(time.time() - t1, 1)
            nb = normalize_blocks(res.blocks)
            chars = sum(len(b.text or "") + len(b.latex or "") for b in nb)
            visuals = sum(1 for b in nb if b.type == "skipped_visual")
            empty = sum(1 for b in nb if b.type != "skipped_visual" and not (b.text or b.latex))
            rows.append({"page": p, "s": dt, "blocks": len(nb), "chars": chars,
                         "visual_skipped": visuals, "empty_blocks": empty,
                         "text_layer_chars": len(text_layer),
                         "warnings": res.warnings,
                         "peak_ram_mb": round(peak_ram_mb_windows())})
            (dump_dir / f"page_{p:04d}_blocks.json").write_text(
                json.dumps([b.__dict__ for b in nb], ensure_ascii=False, indent=1),
                encoding="utf-8")
            if res.markdown_hint:
                (dump_dir / f"page_{p:04d}_md.txt").write_text(res.markdown_hint,
                                                               encoding="utf-8")
            png_path.unlink()
            print(f"  trang {p}: {dt}s | blocks={len(nb)} chars={chars} "
                  f"hinh_bo_qua={visuals} | RAM {rows[-1]['peak_ram_mb']}MB")
    (dump_dir / "summary.json").write_text(
        json.dumps({"model_load_s": load_s, "meta": meta, "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTom tat: {dump_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
