from __future__ import annotations

"""S4-dot-sau (finding 4 / P14): khong mat du lieu OCR that tren vung hinh.

Ranh gioi van GIU: khong bia mo ta noi dung hinh; nhung text OCR thuc su ghi nhan
tren vung hinh phai duoc bao toan (khong bi mat, khong bi nhan doi).
"""

from backend.app.cleaning.normalize import normalize_blocks
from backend.app.ocr.base import OcrBlock
from backend.app.ocr.paddle_adapter import map_blocks
from backend.app.services.export_service import _block_markdown


def test_map_blocks_keeps_real_visual_text():
    raw = {"blocks": [{"type": "image", "bbox": [10, 20, 110, 120],
                       "text": "Hinh 1: so do khoi"}]}
    blocks, warnings = map_blocks(raw)
    assert len(blocks) == 1 and blocks[0].type == "skipped_visual"
    assert blocks[0].text == "Hinh 1: so do khoi", (
        "text OCR that tren vung hinh phai duoc giu (ban cu mat vi gan None)")


def test_map_blocks_visual_without_content_stays_none():
    raw = {"blocks": [{"type": "chart", "bbox": [0, 0, 50, 50]}]}
    blocks, _ = map_blocks(raw)
    assert blocks[0].type == "skipped_visual" and blocks[0].text is None


def test_map_blocks_no_fabricated_visual_text():
    raw = {"blocks": [{"type": "seal", "bbox": [0, 0, 50, 50]}]}
    blocks, _ = map_blocks(raw)
    assert blocks[0].text is None, "khong duoc bia text cho vung hinh khong co OCR text"


def test_normalize_keeps_visual_text_and_empties_none():
    keep = OcrBlock(type="skipped_visual", text="  Chu that tren hinh  ",
                    bbox=[1, 2, 3, 4], confidence=None, order=0)
    empty = OcrBlock(type="skipped_visual", text="   ", bbox=[1, 2, 3, 4],
                     confidence=None, order=1)
    out = normalize_blocks([keep, empty])
    assert out[0].text == "Chu that tren hinh"
    assert out[1].text is None


def test_markdown_visual_note_not_duplicated():
    b = {"type": "skipped_visual", "text": "caption that",
         "bbox": [10.0, 20.0, 110.0, 120.0]}
    md = _block_markdown(b, 3)
    assert md.count("caption that") == 1, "text phai xuat hien DUY NHAT mot lan"
    assert "chưa được xử lý" in md and "chưa xác thực" in md


def test_markdown_visual_without_text_note_only():
    b = {"type": "skipped_visual", "text": None, "bbox": None}
    md = _block_markdown(b, 2)
    assert "chưa được xử lý" in md
    assert "Text OCR ghi nhận" not in md