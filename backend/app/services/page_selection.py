from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional


class SelectionError(ValueError):
    def __init__(self, code: str, message: str, token: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.token = token


def _strict_pos_int(token: str) -> int:
    t = token.strip()
    if not t:
        raise SelectionError("EMPTY_ITEM", "Có mục rỗng trong danh sách trang.", token)
    try:
        value = int(t)
    except ValueError:
        raise SelectionError("NOT_INT", f"Không phải số nguyên hợp lệ: '{token}'.", token)
    if value < 1:
        raise SelectionError("NON_POSITIVE", f"Trang phải >= 1, gặp: '{token}'.", token)
    return value


def parse_page_expression(expression: str, page_count: int, *, allow_all: bool = False) -> List[int]:
    """Dịch biểu thức dạng '5-10,15,20-22' thành danh sách trang 1-based duy nhất, tăng dần.

    page_count: tổng số trang PDF để kiểm biên. allow_all: chấp nhận '*' (= toàn bộ).
    """
    if expression is None:
        raise SelectionError("MISSING", "Chưa chọn trang nào.")
    text = expression.strip()
    if not text:
        raise SelectionError("MISSING", "Chưa chọn trang nào.")
    if text == "*":
        if not allow_all:
            raise SelectionError("ALL_NOT_ALLOWED", "Phải chọn chủ động mới được dùng toàn bộ tài liệu.")
        return list(range(1, page_count + 1))
    pages: set[int] = set()
    for raw_item in text.split(","):
        item = raw_item.strip().replace("–", "-").replace("—", "-").replace(" đến ", "-")
        if not item:
            raise SelectionError("EMPTY_ITEM", "Có mục rỗng trong danh sách trang.", raw_item)
        if "-" in item[1:] or item.startswith("-"):
            parts = item.split("-")
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise SelectionError("BAD_RANGE", f"Khoảng không hợp lệ: '{raw_item}'.", raw_item)
            start = _strict_pos_int(parts[0])
            end = _strict_pos_int(parts[1])
            if start > end:
                raise SelectionError("REVERSED_RANGE", f"Khoảng đảo ngược: '{raw_item}'.", raw_item)
            pages.update(range(start, end + 1))
        else:
            pages.add(_strict_pos_int(item))
    invalid = sorted(p for p in pages if p > page_count)
    if invalid:
        raise SelectionError(
            "OUT_OF_RANGE",
            f"Trang vượt giới hạn 1–{page_count}: {invalid}. Không tự động cắt về phạm vi hợp lệ.",
            str(invalid),
        )
    return sorted(pages)


def parse_from_to(from_page: Optional[int], to_page: Optional[int], page_count: int) -> List[int]:
    for label, value in (("Từ trang", from_page), ("Đến trang", to_page)):
        if isinstance(value, bool) or value is None:
            raise SelectionError("MISSING", f"Thiếu giá trị: {label}.")
        if not isinstance(value, int):
            raise SelectionError("NOT_INT", f"{label} phải là số nguyên.")
        if value < 1:
            raise SelectionError("NON_POSITIVE", f"{label} phải >= 1.")
    if from_page > to_page:
        raise SelectionError("REVERSED_RANGE", f"Từ trang ({from_page}) lớn hơn đến trang ({to_page}).")
    if to_page > page_count:
        raise SelectionError("OUT_OF_RANGE", f"Đến trang vượt tổng {page_count} trang.")
    return list(range(from_page, to_page + 1))


def pages_fingerprint(pages: List[int]) -> str:
    return ",".join(str(p) for p in pages)
