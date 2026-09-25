from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from ..ocr.base import OcrBlock

CLEANING_VERSION = "clean-v1"

_INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.S)
_DISPLAY_MATH = re.compile(r"\\\[(.+?)\\\]", re.S)
_WS = re.compile(r"[ \t\u00a0]+")
_MULTI_NL = re.compile(r"\n{3,}")


def normalize_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = "".join(ch for ch in t if ch == "\n" or ch == "\t" or unicodedata.category(ch)[0] != "C")
    t = _WS.sub(" ", t)
    t = _MULTI_NL.sub("\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    t = t.strip()
    t = _INLINE_MATH.sub(r"$\1$", t)
    t = _DISPLAY_MATH.sub(lambda m: "$$\n" + m.group(1).strip() + "\n$$", t)
    return t or None


def normalize_latex(latex: Optional[str]) -> Optional[str]:
    if latex is None:
        return None
    t = unicodedata.normalize("NFKC", latex).strip()
    # block formula luu LaTeX khong ke delimiter; loai delimiter tha
    if t.startswith("$$") and t.endswith("$$"):
        t = t[2:-2].strip()
    elif t.startswith("$") and t.endswith("$") and not t.startswith("$$"):
        t = t[1:-1].strip()
    t = t.replace("\r\n", "\n").replace("\\\n", "\n")
    return t or None


def normalize_blocks(blocks: List[OcrBlock]) -> List[OcrBlock]:
    out: List[OcrBlock] = []
    order = 0
    for b in blocks:
        nb = OcrBlock(
            type=b.type,
            text=normalize_text(b.text),
            latex=normalize_latex(b.latex),
            bbox=b.bbox,
            confidence=b.confidence,
            order=order,
        )
        order += 1
        if nb.type == "skipped_visual":
            # Ranh gioi P14: KHONG tao mo ta noi dung hinh (khong bia), NHUNG neu
            # OCR thuc su tra ve text tren vung hinh thi GIU NGUYEN (khong mat du lieu);
            # text rong/chi khoang trang -> None de khong tao text gia.
            if nb.text is not None and not nb.text.strip():
                nb.text = None
        elif not nb.text and not nb.latex:
            continue  # block rong khong co nghia -> loai, trang rong that su bat o validators
        out.append(nb)
    return out


def block_plain_text(b: OcrBlock) -> str:
    if b.type == "formula":
        return b.latex or ""
    return b.text or ""


def evaluate_text_layer(text: str) -> dict:
    """Đánh giá chất lượng lớp chữ có sẵn của MỘT trang (mục 5.2).

    Không dùng 'có 1 ký tự' làm bằng chứng PDF text tốt.
    """
    if not text or not text.strip():
        return {"usable": False, "reason": "no_text_layer", "length": 0}
    useful = re.sub(r"[\s\d\W]+", "", text, flags=re.UNICODE)
    length = len(text)
    bad_chars = sum(1 for ch in text if unicodedata.category(ch) == "Co" or ch == "\ufffd")
    ratio_bad = bad_chars / max(length, 1)
    if length < 40 or len(useful) < 30:
        return {"usable": False, "reason": "too_short", "length": length}
    if ratio_bad > 0.02:
        return {"usable": False, "reason": "corrupt_chars", "length": length}
    return {"usable": True, "reason": "ok", "length": length}


def blocks_from_direct_text(text: str, page_no: int,
                            page_size_pt: tuple, dpi: int) -> List[OcrBlock]:
    """Trích trực tiếp lớp chữ: tách đoạn theo dòng trống, KHÔNG tự ghép ngữ nghĩa."""
    blocks: List[OcrBlock] = []
    order = 0
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        blocks.append(OcrBlock(type="paragraph", text=normalize_text(chunk),
                               bbox=None, confidence=None, order=order))
        order += 1
    return blocks
