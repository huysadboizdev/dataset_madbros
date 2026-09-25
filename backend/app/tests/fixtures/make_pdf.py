from __future__ import annotations

"""Sinh PDF don gian khong dung thu vien ngoai (chi phuc vu TEST).

text_pages:    trang co lop chu thuong (khong dau hieu cong thuc trong text).
formula_pages: trang co lop chu chua ky tu '^' (kiem tra phuong thuc OCR-lai).
image_pages:   trang co ANH ra-star nhung (cong thuc/noidung nam trong anh,
               KHONG nam trong text layer) -> kiem tra phat hiem coverage muc 5.2.
Cac trang khac: khong co lop chu (buoc OCR).
"""

import zlib
from typing import Optional, Set


def _page_text(n: int, formula: bool) -> str:
    if formula:
        return f"Bai {n}: phuong trinh x^2 - 4 = 0. Tim nghiem cua phuong trinh."
    return (f"Bai {n}: mo ta dai khong chua ky hieu cong thuc. "
            f"Dong thu hai cua trang {n} nay du dai cho danh gia chat luong lop chu text.")


def _tiny_png_object() -> bytes:
    """Một XObject Image 8x8 DeviceRGB nén FlateDecode (byte nội dung không quan trọng)."""
    # 8x8 RGB = 192 byte, mỗi scanline không predictor.
    raw = bytes(range(192))
    stream = zlib.compress(raw)
    return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            b"/Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")


def make_simple_pdf(path, page_count: int = 140,
                    text_pages: Optional[Set[int]] = None,
                    formula_pages: Optional[Set[int]] = None,
                    image_pages: Optional[Set[int]] = None,
                    small_image_pages: Optional[Set[int]] = None) -> None:
    text_pages = text_pages or {1, 20}
    formula_pages = formula_pages or set()
    image_pages = image_pages or set()
    small_image_pages = small_image_pages or set()
    objects = []

    def add(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    catalog_num = add(b"")
    pages_num = add(b"")
    font_num = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    image_num = add(_tiny_png_object()) if (image_pages or small_image_pages) else None
    page_nums = []
    for i in range(page_count):
        n = i + 1
        has_image = n in image_pages or n in small_image_pages
        parts = []
        if n in text_pages:
            parts.append(f"BT /F1 12 Tf 72 720 Td ({_page_text(n, False)}) Tj ET")
        if n in formula_pages:
            parts.append(f"BT /F1 12 Tf 72 720 Td ({_page_text(n, True)}) Tj ET")
        if n in image_pages:
            # ve anh lon (cong thuc dang anh), khong co text cho phan nay
            parts.append("q 500 0 0 300 60 420 cm /Im0 Do Q")
        elif n in small_image_pages:
            # anh nho 40x24pt (~0.2% trang) — logo/nep thu
            parts.append("q 40 0 0 24 540 750 cm /Im0 Do Q")
        content = "\n".join(parts)
        body = content.encode("latin-1")
        content_num = add(f"<< /Length {len(body)} >>\nstream\n".encode("latin-1")
                          + body + b"\nendstream")
        resources = (f"<< /ProcSet [/PDF /Text /ImageC] /Font << /F1 {font_num} 0 R >>"
                     + (f" /XObject << /Im0 {image_num} 0 R >>" if has_image else "")
                     + " >>")
        page_num = add(
            (f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 612 792] "
             f"/Resources {resources} /Contents {content_num} 0 R >>")
            .encode("latin-1"))
        page_nums.append(page_num)
    kids = " ".join(f"{x} 0 R" for x in page_nums)
    objects[pages_num - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>").encode("latin-1")
    objects[catalog_num - 1] = (
        f"<< /Type /Catalog /Pages {pages_num} 0 R >>").encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_num} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode("latin-1")
    with open(path, "wb") as f:
        f.write(bytes(out))
