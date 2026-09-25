from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..settings import OcrSettings
from ..storage.artifacts import sha256_file
from . import model_identity as mi
from .base import OcrBlock, OcrPageResult

VISUAL_TYPES = {"image", "chart", "seal", "figure", "diagram"}
FORMULA_TYPES = {"formula", "display_formula", "inline_formula", "equation"}
TABLE_TYPES = {"table"}
TEXT_TYPES = {"text", "paragraph", "title", "heading", "abstract", "content",
              "list", "figure_caption", "table_caption", "reference",
              "header", "footer", "aside_text", "doc_title", "figure_title",
              "formula_text", "table_title", "number", "footnote"}


def _first_key(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def _iter_block_dicts(node: Any):
    """Duyệt tree kết quả PaddleX, lấy mọi dict có bbox + nội dung dạng block."""
    if isinstance(node, dict):
        bbox = _first_key(node, ["bbox", "block_bbox", "poly", "box"])
        content = _first_key(node, ["text", "text_content", "block_content", "content",
                                    "latex", "latex_content", "html", "table_content"])
        btype = _first_key(node, ["type", "block_label", "label"])
        if isinstance(bbox, list) and len(bbox) >= 4 and (content is not None or btype is not None):
            yield node
        else:
            for v in node.values():
                yield from _iter_block_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_block_dicts(v)


def _simple_html_table_to_md(html: str) -> Optional[str]:
    import re
    if any(t in html for t in ("rowspan", "colspan")):
        return None
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    if not rows:
        return None
    parsed = []
    for r in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S | re.I)
        cells = [re.sub(r"<[^>]+>", "", c).replace("\n", " ").strip() for c in cells]
        parsed.append(cells)
    width = max(len(r) for r in parsed)
    parsed = [r + [""] * (width - len(r)) for r in parsed]
    lines = ["| " + " | ".join(parsed[0]) + " |",
             "|" + "---|" * width]
    for r in parsed[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def map_blocks(raw_result: Dict[str, Any]) -> tuple[List[OcrBlock], List[str]]:
    blocks: List[OcrBlock] = []
    warnings: List[str] = []
    seen_ids: set[str] = set()
    order = 0
    for d in _iter_block_dicts(raw_result):
        bbox = _first_key(d, ["bbox", "block_bbox", "poly", "box"])
        bbox = [float(x) for x in bbox[:4]] if isinstance(bbox, list) else None
        btype = str(_first_key(d, ["type", "block_label", "label"]) or "text").lower()
        content = _first_key(d, ["text", "text_content", "block_content", "content"])
        latex = _first_key(d, ["latex", "latex_content"])
        html = _first_key(d, ["html", "table_content"])
        score = _first_key(d, ["score", "rec_score", "confidence"])
        confidence = float(score) if isinstance(score, (int, float)) else None
        key = f"{btype}:{(bbox or [0]*4)}:{str(content or latex or html)[:64]}"
        if key in seen_ids:
            continue
        seen_ids.add(key)

        if btype in VISUAL_TYPES:
            # Ranh gioi P14: KHONG bia mo ta noi dung hinh, nhung neu engine thuc su
            # tra text tren vung hinh thi GIU LAI (khong mat du lieu OCR that).
            vtext = str(content).strip() if content is not None else ""
            blocks.append(OcrBlock(type="skipped_visual", text=vtext or None, bbox=bbox,
                                   confidence=confidence, order=order))
        elif btype in FORMULA_TYPES:
            tex = str(latex or content or "").strip()
            if not tex:
                warnings.append("formula_block_empty")
            blocks.append(OcrBlock(type="formula", latex=tex or None, bbox=bbox,
                                   confidence=confidence, order=order))
        elif btype in TABLE_TYPES:
            raw_html = str(html or content or "")
            md = _simple_html_table_to_md(raw_html) if raw_html else None
            if md is not None:
                blocks.append(OcrBlock(type="table", text=md, bbox=bbox,
                                       confidence=confidence, order=order))
            else:
                blocks.append(OcrBlock(type="table", text=raw_html or None, bbox=bbox,
                                       confidence=confidence, order=order))
                warnings.append("table_not_simple")
        else:
            text = str(content if content is not None else (latex or html or "")).strip()
            btype_out = "heading" if "title" in btype or btype == "heading" else (
                "list" if btype == "list" else "paragraph")
            blocks.append(OcrBlock(type=btype_out, text=text or None, bbox=bbox,
                                   confidence=confidence, order=order))
        order += 1
    return blocks, warnings


# F2: `ModelChangedSincePin` duoc dinh nghia trong model_identity (dung chung voi
# fake engine/test) — alias o day de giu API cu `from .paddle_adapter import ...`.
ModelChangedSincePin = mi.ModelChangedSincePin


def _recheck_problem(fp_pinned: Dict[str, Any], root: Path, name: str,
                     full: bool = True) -> Optional[str]:
    """Alias giu tuong thich: xem `mi.recheck_problem` (mac dinh FULL SHA-256)."""
    return mi.recheck_problem(fp_pinned, root, name, full=full)


def _model_identity(pipeline: Any, pinned: Optional[Dict[str, Any]] = None,
                    root: Optional[Path] = None) -> Dict[str, Any]:
    """Ten + HASH THAT cua model da resolve trong pipeline.

    TRA VE KHONG chua duong dan tuyet doi (dir/home/username) — chi ten, SHA-256
    config va SHA-256 weights (day du, tinh MOT lan luc engine load). An toan de xuat.

    F2: neu co identity pin cua job thi model THUC DUNG phai trung identity do —
    re-check bang FULL SHA-256 (`mi.verify_pinned`). Lech -> `ModelChangedSincePin`
    (worker bao model_failed), TUYET DOI khong tu full-hash roi van dung tag cu.
    """
    ident: Dict[str, Any] = {}
    try:
        cfg = getattr(pipeline, "_merged_paddlex_config", {}) or {}
        subs = cfg.get("SubModules", {}) or {}
        layout = (subs.get("LayoutDetection") or {}).get("model_name")
        vl = (subs.get("VLRecognition") or {}).get("model_name")
        ident["resolved_pipeline"] = cfg.get("pipeline_name")
        ident["resolved_layout_model"] = layout
        ident["resolved_vl_model"] = vl
        ident["resolved_layout_threshold"] = (subs.get("LayoutDetection") or {}).get("threshold")
        ident["merge_layout_blocks"] = cfg.get("merge_layout_blocks")
        names = [str(x) for x in filter(None, [layout, vl])]
        root = root or mi.official_root()
        if pinned:
            fps, tag, note = mi.verify_pinned(pinned, root, names, full_recheck=True)
            ident["model_fp"] = fps
            ident["model_rev"] = tag
            ident["identity_source"] = "pinned_job"
            ident["recheck"] = note
            return ident
        ident["model_fp"] = {n: mi.model_fingerprint(n, root, full=True) for n in names}
        # identity tu CHINH ket qua vua tinh (lan doc duy nhat) — khong hash lai model.
        ident["model_rev"] = mi.identity_from_fps(list(ident["model_fp"].values()))
        ident["identity_source"] = "engine_load_self"
        ident["recheck"] = "full_sha256_all_artifacts"
    except mi.ModelChangedSincePin:
        raise  # model khac identity da pin: KHONG nuot (xem ModelChangedSincePin)
    except Exception as e:  # never fail load over metadata thuan (khong bao gom pin)
        ident["model_rev_error"] = str(e)
    return ident


class PaddleVLAdapter:
    """Adapter ứng viên: PaddleOCR-VL chạy CPU, một trang mỗi lần gọi.

    Chỉ trả structured blocks; không save_all, không xuất Word, không cloud.
    """

    name = "paddleocr_vl"

    def __init__(self, settings: OcrSettings, pinned_identity: Optional[Dict[str, Any]] = None):
        self.settings = settings
        self._pipeline = None
        self.meta: Dict[str, Any] = {}
        # Identity job DA full-hash DUNG 1 lan (tu JobManager); load() re-check DAY DU
        # lai lan nua (F2: correctness truoc muc tieu "hash dung mot lan").
        self._pinned_identity = pinned_identity
        # Ghi ro neu file pin thieu/hong (worker tu full-hash) de JobManager log + doi chieu.
        self.pin_file_error: Optional[str] = None

    def load(self) -> Dict[str, Any]:
        import paddleocr
        import paddlex
        from paddleocr import PaddleOCRVL

        # Khong truyen ten model: gia tri mac dinh cua pipeline_version='v1.6'
        # da tro dung PaddleOCR-VL-1.6 + PP-DocLayout trong cache may nguoi dung.
        # Truyen ten explicit bung duong dan 'engine bindings' loi tren paddleocr 3.7.0.
        self._pipeline = PaddleOCRVL(
            device=self.settings.device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
        )
        # meta luu CAI ENGINE DANG THUC SU DUNG (resolve tu _merged_paddlex_config),
        # khong ten do nguoi dung khai trong config.json.
        self.meta = {
            "engine": self.name,
            "paddleocr_version": getattr(paddleocr, "__version__", "unknown"),
            "paddlex_version": getattr(paddlex, "__version__", "unknown"),
            "device": self.settings.device,
            "render_dpi": self.settings.render_dpi,
            "declared": {"pipeline_version": self.settings.pipeline_version,
                         "layout_model_name": self.settings.layout_model_name,
                         "vl_rec_model_name": self.settings.vl_rec_model_name},
        }
        if self.pin_file_error:
            self.meta["pin_file_error"] = self.pin_file_error
        self.meta.update(_model_identity(self._pipeline, pinned=self._pinned_identity))
        return self.meta

    def recognize_page(self, image_path: Path, page_no: int) -> OcrPageResult:
        if self._pipeline is None:
            raise RuntimeError("Engine chưa được load")
        from PIL import Image

        results = list(self._pipeline.predict(
            str(image_path),
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
        ))
        if not results:
            return OcrPageResult(page_no=page_no, engine_name=self.name,
                                 engine_version=str(self.meta.get("paddleocr_version")),
                                 warnings=["empty_predict_output"])
        res = results[0]
        raw: Dict[str, Any] = {}
        try:
            raw = dict(res.json)
        except Exception:
            raw = {}
        markdown_hint: Optional[str] = None
        try:
            md = res.markdown
            markdown_hint = md.get("markdown", {}).get("text") if isinstance(md, dict) else str(md)
        except Exception:
            markdown_hint = None

        blocks, warnings = map_blocks(raw)
        with Image.open(image_path) as im:
            w, h = im.size
        return OcrPageResult(
            page_no=page_no,
            blocks=blocks,
            coordinate_space={"unit": "pixel", "width": w, "height": h,
                              "origin": "top_left"},
            engine_name=self.name,
            engine_version=str(self.meta.get("paddleocr_version", "")),
            markdown_hint=markdown_hint,
            warnings=warnings,
        )

    def unload(self) -> None:
        self._pipeline = None
