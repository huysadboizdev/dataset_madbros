from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..schemas import BlockModel

VALID_BLOCK_TYPES = {"paragraph", "heading", "formula", "table", "list",
                     "skipped_visual", "other"}


def validate_page_payload(page: Dict[str, Any]) -> List[str]:
    """Kiểm tra kỹ thuật trước khi commit artifact một trang."""
    errors: List[str] = []
    if page.get("pdf_page") != page.get("_expected_page"):
        errors.append("PAGE_MISMATCH: ket qua gan voi khac trang yeu cau")
    block_ids = [b["block_id"] for b in page.get("blocks", [])]
    if len(block_ids) != len(set(block_ids)):
        errors.append("DUPLICATE_BLOCK_ID")
    for b in page.get("blocks", []):
        if b.get("type") not in VALID_BLOCK_TYPES:
            errors.append(f"BAD_BLOCK_TYPE: {b.get('type')}")
        if b.get("type") == "formula" and not b.get("text"):
            errors.append(f"EMPTY_FORMULA: {b.get('block_id')}")
        if b.get("type") in ("paragraph", "heading", "list") and not b.get("text"):
            errors.append(f"EMPTY_TEXT: {b.get('block_id')}")
    cs = page.get("coordinate_space") or {}
    if cs and cs.get("unit") not in ("pixel", "point"):
        errors.append("BAD_COORD_UNIT")
    return errors


def detect_empty_with_context(blocks: List[BlockModel], text_layer_len: int) -> Optional[str]:
    """Trang khong co noi dung hoc tapped -> issue de nguoi dung kiem tra, khong bia chu."""
    content = [b for b in blocks if b.type != "skipped_visual"]
    if not content and text_layer_len == 0:
        return "NO_CONTENT_DETECTED"
    return None


_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")
_LATEX_PAIRS = [("{", "}"), ("[", "]"), ("(", ")")]


def latex_basic_check(latex: str) -> Optional[str]:
    """Khong chung minh cong thuc dung; chi bat hong ro ret."""
    for a, b in _LATEX_PAIRS:
        if latex.count(a) != latex.count(b):
            return "LATEX_UNBALANCED"
    if "\\" in latex and not _LATEX_CMD.search(latex) and re.search(r"[a-z]{6,}", latex):
        return "LATEX_SUSPECT_PLAINTEXT"
    return None
