from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium


class PdfOpenError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PdfDoc:
    """Lớp che pypdfium2. Chuyển 1-based -> 0-based DUY NHẤT tại đây."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self._doc: Optional[pdfium.PdfDocument] = pdfium.PdfDocument(str(path))
        except pdfium.PdfError as e:  # type: ignore[attr-defined]
            code = "PASSWORD_PROTECTED" if getattr(e, "err_code", None) == 2 else "BROKEN_PDF"
            raise PdfOpenError(code, f"Không mở được PDF: {e}") from e
        self.page_count = len(self._doc)

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def __enter__(self) -> "PdfDoc":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _check_page(self, page_no: int) -> int:
        if not isinstance(page_no, int) or isinstance(page_no, bool):
            raise ValueError("page_no phải là số nguyên 1-based")
        if page_no < 1 or page_no > self.page_count:
            raise ValueError(f"Trang {page_no} ngoài phạm vi 1..{self.page_count}")
        return page_no - 1

    def extract_page_text(self, page_no: int) -> str:
        idx = self._check_page(page_no)
        page = self._doc[idx]
        try:
            textpage = page.get_textpage()
            return textpage.get_text_bounded()
        finally:
            page.close()

    def render_page_png(self, page_no: int, dpi: int = 200) -> bytes:
        idx = self._check_page(page_no)
        page = self._doc[idx]
        try:
            bitmap = page.render(scale=dpi / 72.0)
            pil = bitmap.to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            return buf.getvalue()
        finally:
            page.close()

    def page_size_points(self, page_no: int) -> tuple[float, float]:
        idx = self._check_page(page_no)
        page = self._doc[idx]
        try:
            return page.get_size()
        finally:
            page.close()


    def page_content_profile(self, page_no: int) -> dict:
        """Mo ta bo phuc trang bang pypdfium2 page objects (khong OCR).

        Dung quyet dinh truc tiep vs OCR theo muc 5.2: lop chu 'tot' van co the
        mat cong thuc nam trong anh tren cung trang.
        Tra ve 1-based page; toa do PDF point, goc tren-trai sau dao.
        """
        idx = self._check_page(page_no)
        page = self._doc[idx]
        try:
            w_pt, h_pt = page.get_size()
            text_boxes = []
            image_boxes = []
            path_count = 0
            for obj in page.get_objects():
                cls = type(obj).__name__
                try:
                    x0, y0, x1, y1 = obj.get_bounds()
                except Exception:
                    continue
                # pypdfium2 bounds: goc duoi-trai; chuyen sang dien tich chi can |dx*dy|
                area = abs(x1 - x0) * abs(y1 - y0)
                box = {"x0": min(x0, x1), "y0": min(y0, y1),
                       "x1": max(x0, x1), "y1": max(y0, y1), "area": area}
                if "Image" in cls:
                    image_boxes.append(box)
                elif "Text" in cls:
                    text_boxes.append(box)
                elif "Path" in cls:
                    path_count += 1
            page_area = max(w_pt * h_pt, 1.0)
            text_cov = sum(b["area"] for b in text_boxes) / page_area
            img_cov = sum(b["area"] for b in image_boxes) / page_area
            max_img_frac = (max((b["area"] for b in image_boxes), default=0.0) / page_area)
            return {"page_no": page_no, "width_pt": w_pt, "height_pt": h_pt,
                    "text_objects": len(text_boxes), "image_objects": len(image_boxes),
                    "path_objects": path_count,
                    "text_coverage": round(text_cov, 4),
                    "image_coverage": round(img_cov, 4),
                    "max_image_page_frac": round(max_img_frac, 4)}
        finally:
            page.close()

    def looks_scanned(self, page_no: int) -> bool:
        prof = self.page_content_profile(page_no)
        return prof["text_objects"] == 0 and prof["image_objects"] > 0


def looks_like_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF-")


def decide_direct_or_ocr(quality: dict, profile: dict) -> tuple[bool, list, list]:
    """Quyet dinh phuong phap cho MOT trang da chon (muc 5.2).

    Return (use_direct, info_flags, force_ocr_reasons).
    - 'co 1 ky tu text layer' KHONG du la tot: quality.usable da chan do.
    - Trang co lop chu tot NHUNG co anh / dang ve lon -> khong du can cu cho rang
      noi dung duoc trich xuat day du: neu anh lon thi OCR trang; neu vector
      dang nghi ngo thi direct + flag can kiem tra.
    """
    flags: list = []
    reasons: list = []
    if not quality.get("usable"):
        return False, flags, [quality.get("reason", "text_layer_unusable")]
    if profile["image_objects"] > 0 and profile["max_image_page_frac"] > 0.015:
        reasons.append("IMAGE_REGIONS_ON_PAGE: cong thuc/co the nam trong anh")
        return False, flags, reasons
    if profile["path_objects"] > 25 and profile["text_coverage"] < 0.08:
        reasons.append("VECTOR_CONTENT_MAYBE_LOST")
        return False, flags, reasons
    if profile["text_coverage"] < 0.01 and quality.get("length", 0) < 120:
        flags.append("DIRECT_CONTENT_THIN")
    if profile["image_objects"] > 0:
        flags.append("SMALL_IMAGES_PRESENT_VISUAL_MIGHT_CARRY_INFO")
    if profile["path_objects"] > 60:
        flags.append("DENSE_VECTOR_CONTENT_CHECK_TABLES")
    return True, flags, reasons
