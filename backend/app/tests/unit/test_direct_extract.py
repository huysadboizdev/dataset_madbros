from __future__ import annotations

"""Phat hien 2 / P11: quyet dinh direct-vs-OCR phai dua tren BO CUUC TRANG
(coverage/layout), khong chi do dai text hay mot danh sach ky hieu toan ngan.

Cac profile duoc thiet ke utung fixture make_pdf (image_pages 500x300pt tren
612x792pt = ~0.30; small_image 40x24 ~0.002)."""

from backend.app.services.pdf_service import decide_direct_or_ocr

GOOD = {"usable": True, "reason": "ok", "length": 400}
BAD_EMPTY = {"usable": False, "reason": "no_text_layer", "length": 0}
BAD_SHORT = {"usable": False, "reason": "too_short", "length": 12}


def _prof(text_objects=20, image_objects=0, path_objects=3,
          text_cov=0.25, img_cov=0.0, max_img_frac=0.0):
    return {"page_no": 1, "width_pt": 612, "height_pt": 792,
            "text_objects": text_objects, "image_objects": image_objects,
            "path_objects": path_objects, "text_coverage": text_cov,
            "image_coverage": img_cov, "max_image_page_frac": max_img_frac}


def test_good_text_no_image_direct():
    use_direct, flags, reasons = decide_direct_or_ocr(GOOD, _prof())
    assert use_direct is True and reasons == []


def test_one_char_never_enough():
    # quality khong 'usable' -> khong duoc coi la lop chu tot du chi 1 ky tu
    use_direct, _f, reasons = decide_direct_or_ocr(BAD_SHORT, _prof())
    assert use_direct is False and reasons


def test_good_text_but_large_image_region_forces_ocr():
    """Lop chu tot NHUNG co vung anh lon -> khong du can cu: bat OCR dung trang."""
    prof = _prof(image_objects=1, img_cov=0.30, max_img_frac=0.30)
    use_direct, _f, reasons = decide_direct_or_ocr(GOOD, prof)
    assert use_direct is False
    assert any("IMAGE_REGIONS_ON_PAGE" in r for r in reasons)


def test_vector_heavy_low_coverage_forces_ocr():
    prof = _prof(path_objects=40, text_cov=0.05)
    use_direct, _f, reasons = decide_direct_or_ocr(GOOD, prof)
    assert use_direct is False
    assert any("VECTOR_CONTENT_MAYBE_LOST" in r for r in reasons)


def test_small_image_keeps_direct_but_flags():
    """Anh nho (nep thu) khong ban OCR bat buoc khi co the trich tin cay."""
    prof = _prof(image_objects=1, img_cov=0.002, max_img_frac=0.002)
    use_direct, flags, reasons = decide_direct_or_ocr(GOOD, prof)
    assert use_direct is True and reasons == []
    assert any("SMALL_IMAGES" in f for f in flags)


def test_thin_direct_content_flagged_not_blocked():
    prof = _prof(text_objects=1, text_cov=0.005)
    q = {"usable": True, "reason": "ok", "length": 60}
    use_direct, flags, reasons = decide_direct_or_ocr(q, prof)
    assert use_direct is True and reasons == []
    assert "DIRECT_CONTENT_THIN" in flags
