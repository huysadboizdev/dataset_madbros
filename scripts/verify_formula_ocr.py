from __future__ import annotations

"""Nghiem thu CONG THUC THAT (khong phai mock).

Sinh cac trang fixture chua CONG THUC DUOC SET THAT (matplotlib mathtext -> PNG
that, gom phan so duong ke, can, so mu, dau so sanh) + chu TIENG VIET, co GROUND
TRUTH, roi chay PaddleOCR-VL THAT va doi chieu:

  - LaTeX co xuat hien khong (block formula va/hoac inline trong van ban)
  - JSON escaping: latex qua json.dumps -> loads phai nguyen ven
  - Phan biet KIEM CU PHAP (latex BasicCheck / render duoc) voi DOI CHIEU Y NGHIA
    (ky vong khop ground truth) — y nghia can nguoi duyet.

  python scripts/verify_formula_ocr.py --pages "1-3" --report docs/FORMULA_CHECK.md
"""

import argparse
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DPI_IMG = 220  # do net cua anh cong thuc (huyen thi ~72dpi -> ~200dpi)

# Moi trang = mot "trang sach" that: van ban Tieng Viet (render qua matplotlib)
# + 1..n phan toan SET THAT + inline math trong cau.
PAGES = [
    {
        "name": "page1",
        "viet": "Giá trị nhỏ nhất của biểu thức là 3.",
        "display": r"$\dfrac{2x-1}{x+3} \geq 5$",
        "inline": r"Căn thức $\sqrt{x}$ xác định khi $x \geq 0$.",
        "expect": {"display": ["frac", "2x", "1", "x", "3", "ge", "5"],
                   "inline": ["sqrt", "x", "ge", "0"]},
        "note": r"Engine chuẩn hoá \dfrac→\frac (cùng phân số, không mất nội dung).",
    },
    {
        "name": "page2",
        "viet": "Độ dài cạnh huyền bằng căn hai của 5.",
        "display": r"$\sqrt{a^{2}+b^{2}} = \sqrt{5}$",
        "inline": r"Nếu $a^{2}+b^{2}=c^{2}$ thì tam giác vuông tại C.",
        "expect": {"display": ["sqrt", "a", "2", "b", "5"],
                   "inline": ["a", "2", "b", "c", "="]},
    },
    {
        "name": "page3",
        "viet": "Nghiệm của bất phương trình:",
        "display": r"$\frac{3x-1}{2} < x + 4$",
        "inline": r"Tập nghiệm $S = (-\infty;\, 9)$.",
        "expect": {"display": ["frac", "3x", "1", "2", "x", "4"],
                   "inline": ["infty", "9", "S"]},
    },
]


def _render_page_png(pg: dict, out_path: Path) -> None:
    """Render MOT trang that: chu Viet (mathtext) + phan toan set that + inline."""
    fig = plt.figure(figsize=(8.5, 11), dpi=DPI_IMG)
    fig.text(0.06, 0.93, pg["viet"], fontsize=20)
    fig.text(0.5, 0.72, pg["display"], fontsize=34, ha="center")
    fig.text(0.06, 0.55, pg["inline"], fontsize=20)
    fig.canvas.draw()
    fig.savefig(out_path, dpi=DPI_IMG, facecolor="white")
    plt.close(fig)


# ------------------ dong goi PNG -> PDF ------------------
def _write_pdf_with_images(pdf_path: Path, png_dir: Path) -> None:
    objects = []

    def add(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    from PIL import Image

    def img_obj(png: Path) -> int:
        im = Image.open(png).convert("RGB")
        w, h = im.size
        raw = b"".join(b"\x00" + im.crop((0, y, w, y + 1)).tobytes() for y in range(h))
        comp = zlib.compress(raw)
        return add(b"<< /Type /XObject /Subtype /Image /Width " + str(w).encode() + b" /Height "
                   + str(h).encode() + b" /ColorSpace /DeviceRGB /BitsPerComponent 8"
                   b" /Filter /FlateDecode /Length " + str(len(comp)).encode() + b" >>\nstream\n"
                   + comp + b"\nendstream")

    catalog = add(b"")
    pages = add(b"")
    page_nums = []
    for pg in PAGES:
        png = png_dir / (pg["name"] + ".png")
        im = Image.open(png)
        w_pt, h_pt = im.size[0] * 72.0 / DPI_IMG, im.size[1] * 72.0 / DPI_IMG
        img_num = img_obj(png)
        content = f"q {w_pt:.1f} 0 0 {h_pt:.1f} 0 0 cm /Im{img_num} Do Q".encode("latin-1")
        cnum = add(f"<< /Length {len(content)} >>\nstream\n".encode("latin-1")
                   + content + b"\nendstream")
        pnum = add(f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 {w_pt:.1f} {h_pt:.1f}] "
                   f"/Resources << /ProcSet [/PDF /ImageC] /XObject << /Im{img_num} {img_num} 0 R >> >> "
                   f"/Contents {cnum} 0 R >>".encode("latin-1"))
        page_nums.append(pnum)
    kids = " ".join(f"{x} 0 R" for x in page_nums)
    objects[pages - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>".encode("latin-1")
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages} 0 R >>".encode("latin-1")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, obj in enumerate(objects, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"
    xr = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode("latin-1") + b"0000000000 65535 f \n"
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {len(objects)+1} /Root {catalog} 0 R >>\nstartxref\n{xr}\n%%EOF\n").encode("latin-1")
    pdf_path.write_bytes(bytes(out))


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "", (s or "").lower())


def _json_escape_roundtrip(latex: str) -> bool:
    """Kiểm JSON escaping: LaTeX đi qua bộ serial hoá rồi về đúng chuỗi gốc."""
    try:
        return json.loads(json.dumps({"latex": latex}))["latex"] == latex
    except Exception:
        return False


def _evaluate(p: int, pg: dict, blocks):
    """blocks: danh sach OcrBlock (that hoac tai tu raw JSON). Tra kq danh gia."""
    from backend.app.cleaning.validators import latex_basic_check
    from backend.app.cleaning.math_verify import verify_all
    formula_latex = " ".join((b.latex or b.text or "") for b in blocks if b.type == "formula")
    text_all = " ".join((b.text or "") for b in blocks if b.type != "formula")
    has_formula = any(b.type == "formula" and (b.latex or b.text) for b in blocks)
    verdict = verify_all([pg["display"]], [pg["inline"]], formula_latex, text_all)
    disp_ok = all(r["ok"] for r in verdict["results"] if r["kind"] == "display")
    inl_ok = all(r["ok"] for r in verdict["results"] if r["kind"] == "inline")
    syntax_ok = not any(latex_basic_check(x) for x in
                        [b.latex or b.text for b in blocks if b.type == "formula"])
    ok = verdict["ok"] and syntax_ok
    missing = sorted({m for r in verdict["failed"] for m in r["missing"]})
    return {"ok": ok, "disp_ok": disp_ok, "inl_ok": inl_ok, "has_formula": has_formula,
            "missing": missing, "verdict": verdict}


def _write_report(out_dir: Path, raw_dir: Path, pages: list, results: list, meta: dict,
                  mode: str) -> tuple[str, bool]:
    from dataclasses import asdict
    lines = ["# Nghiệm thu công thức THẬT (fixture set bằng matplotlib mathtext)\n",
             f"Engine thật: `{meta.get('resolved_layout_model')}` + `{meta.get('resolved_vl_model')}`"
             f" (paddleocr {meta.get('paddleocr_version')}) · DPI render {meta.get('render_dpi')}"
             f" · mode=`{mode}` · Model config: `docs/formula_fixture/model_meta.json` ·"
             f" raw per-page: `docs/formula_fixture/ocr_raw/`\n",
             "Đối chiếu bằng `backend/app/cleaning/math_verify.verify_all`: **GIỮ** toán tử "
             "(=,<,>,≥,≤,+,−,^) và cấu trúc (\\frac, √, ^); chỉ chuẩn hoá \\dfrac→\\frac… đã định "
             "nghĩa; bắt buộc đủ CẢ display VÀ inline; substring rời rạc không phải bằng chứng duy nhất.\n",
             "| Trang | Block formula | Display OK | Inline OK | Ký hiệu thiếu | Kết luận |",
             "|---|---|---|---|---|---|"]
    all_ok = True
    for p, pg, blocks, ev in results:
        concl = "ĐẠT (cú pháp+hiện diện)" if ev["ok"] else "KHÔNG ĐẠT"
        all_ok = all_ok and ev["ok"]
        lines.append(f"| {p} | {ev['has_formula']} | {ev['disp_ok']} | {ev['inl_ok']} "
                     f"| {ev['missing'] or '—'} | {concl} |")
        (raw_dir / f"page_{p:03d}_blocks.json").write_text(
            json.dumps([asdict(b) for b in blocks], ensure_ascii=False, indent=1), encoding="utf-8")
        (raw_dir / f"page_{p:03d}_verify.json").write_text(
            json.dumps(ev["verdict"], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for p, pg, blocks, ev in results:
        lines.append(f"\n## Trang {p}: `{pg['display']}` + inline `{pg['inline']}`\n")
        lines.append("- Block formula bắt được: "
                     f"**{ev['has_formula']}** (thiếu block KHÔNG phải bằng chứng duy nhất).")
        for r in ev["verdict"]["results"]:
            mark = "✅" if r["ok"] else "❌"
            lines.append(f"- {mark} {r['kind']}: `{r['expected']}` → {r['reason']}"
                         + (f" (thiếu `{r['missing']}`)" if r.get("missing") else ""))
        lines.append("- OCR trả về THẬT (đã gộp block):")
        for b in blocks:
            val = b.latex or b.text or ""
            lines.append(f"  - `{b.type}`: `{val[:200]}`" if val else f"  - `{b.type}`")
    verdict_txt = ("ĐẠT: mọi biểu thức (display VÀ inline) khớp về ký hiệu + toán tử + cấu trúc; "
                   "LaTeX round-trip JSON nguyên ven (xem test_formula_pipeline); cú pháp basic-check sạch. "
                   "Engine chuẩn hoá \\dfrac→\\frac (cùng phân số, không mất nội dung)."
                   if all_ok else
                   "CHƯA ĐẠT HOÀN TOÀN — ghi nhận hạn chế của engine; KHÔNG coi là đạt chỉ vì có "
                   "pipeline. Cần người đối chiếu Ý NGHĨA.")
    lines.append(f"\n## Kết luận\n\n{verdict_txt}\n")
    if mode.startswith("reverify"):
        lines.append("_Lần này KIỂM LẠI raw của lần OCR thật trước bằng comparator hiện hành — "
                     "KHÔNG phải một lần gọi engine mới. Raw blocks + model metadata nằm cạnh file này._")
    else:
        lines.append("_Đây là LẦN GỌI ENGINE THẬT (không mock, không lấy log FAIL cũ làm bằng chứng "
                     "PASS). Raw per-page + model_meta đã lưu kèm. ĐỐI CHIẾU Ý NGHĨA toán học CẦN "
                     "NGƯỜI duyệt._")
    text = "\n".join(lines)
    if meta.get("model_fp"):
        (out_dir / "model_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return text, all_ok


def _load_saved_blocks(raw_dir: Path, p: int):
    """Tai block OCR THAT da luu o lan chay truoc (mode reverify) -> OcrBlock."""
    from backend.app.ocr.base import OcrBlock
    data = json.loads((raw_dir / f"page_{p:03d}_blocks.json").read_text(encoding="utf-8"))
    return [OcrBlock(**{k: b.get(k) for k in ("type", "text", "latex", "bbox", "confidence", "order")})
            for b in data]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1-3")
    ap.add_argument("--report", default=None)
    ap.add_argument("--dpi", type=int, default=DPI_IMG)
    ap.add_argument("--reverify", action="store_true",
                    help="Doi chieu lai tu raw OCR blocks DA LUU (khong mo engine), "
                         "dung comparator hien tai.")
    args = ap.parse_args()

    out_dir = ROOT / "docs" / "formula_fixture"
    raw_dir = out_dir / "ocr_raw"
    png_dir = out_dir / "png"
    raw_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    from backend.app.services import pdf_service
    from backend.app.services.page_selection import parse_page_expression
    pdf_path = out_dir / "formula_fixture.pdf"

    meta = {}
    meta_file = out_dir / "model_meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    results = []
    if args.reverify:
        with pdf_service.PdfDoc(pdf_path) as d:
            total = d.page_count
        pages = parse_page_expression(args.pages, total, allow_all=True)
        print(f"REVERIFY tu byte OCR that da luu: {raw_dir} (KHONG mo engine)")
        for p in pages:
            blocks = _load_saved_blocks(raw_dir, p)
            results.append((p, PAGES[p - 1], blocks, _evaluate(p, PAGES[p - 1], blocks)))
        mode = "reverify (tu raw OCR that, comparator moi)"
    else:
        for pg in PAGES:
            _render_page_png(pg, png_dir / (pg["name"] + ".png"))
        _write_pdf_with_images(pdf_path, png_dir)
        print(f"fixture set that: {pdf_path}")
        from backend.app.ocr.paddle_adapter import PaddleVLAdapter
        from backend.app.settings import OcrSettings
        with pdf_service.PdfDoc(pdf_path) as d:
            total = d.page_count
        pages = parse_page_expression(args.pages, total, allow_all=True)
        eng = PaddleVLAdapter(OcrSettings(device="cpu", render_dpi=args.dpi))
        meta = eng.load()
        meta["render_dpi"] = args.dpi
        print(f"model that: layout={meta.get('resolved_layout_model')} "
              f"vl={meta.get('resolved_vl_model')} (paddleocr {meta.get('paddleocr_version')})")
        with pdf_service.PdfDoc(pdf_path) as d:
            for p in pages:
                pg = PAGES[p - 1]
                png = png_dir / f"_ocr_render_p{p}.png"
                png.write_bytes(d.render_page_png(p, args.dpi))
                res = eng.recognize_page(png, p)
                png.unlink(missing_ok=True)
                ev = _evaluate(p, pg, res.blocks)
                results.append((p, pg, res.blocks, ev))
                print(f"p{p}: formula_block={ev['has_formula']} display_ok={ev['disp_ok']} "
                      f"inline_ok={ev['inl_ok']} ok={ev['ok']} thieu={ev['missing']}")
        eng.unload()
        mode = "live OCR"

    text, all_ok = _write_report(out_dir, raw_dir, pages, results, meta, mode)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"\nbao cao: {args.report}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
