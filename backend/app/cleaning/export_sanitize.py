from __future__ import annotations

"""Sanitize cau truc metadata DAU RA truoc khi xuat (phat hien S3).

Quet TOAN BO metadata theo cau truc (dict/list/str), khong chi user_metadata:
- LOAI bo khoa chua duong dan (dir, *path, root, home...) va gia tri la duong dan
  tuyet doi Windows/Unix hoac chua ten nguoi dung (`\\Users\\`, `/home/`).
- REDACT email/dien thoai trong CHUOI van ban thuong.
- GIU NGUYEN: SHA-256/checksum (chuoi hex dai), so nguyen (kich thuoc, page number),
  ten model, phien ban — nhung thu can cho tai lap/duyet ma KHONG phai thong tin rieng.
Khong cham vao NOI DUNG toan hoc (ham nay chi dung cho metadata/goi dieu khong).
"""

import re
from typing import Any, Dict, List

from .pii import scan_pii

# Khoa/ten truong tuyet doi khong duoc xuat ra ngoai.
# KHOP CHINH XAC (anchored): `model_root_present` (bool) hay `some_path` (gia tri
# duong dan -> chi bi PATH_REDACTED o phia duoi) KHONG bi xoan khoa nham lan;
# khoa-loai-duong-dan that (dir/path/raw_path/...) van bi loai hoan toan.
_BLOCKED_KEYS = re.compile(
    r"^(dir|path|root|home|file|artifact|content_path|raw_path|image_path|tmpdir|abspath)$",
    re.I,
)
# Duong dan tuyet doi Windows (C:\...) hoac UNC (\\srv\share), hoac Unix co sep
_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")
_UNC = re.compile(r"^\\\\")
_UNIX_ABS = re.compile(r"^/[^\s]+/")
_USER_DIR = re.compile(r"(?i)(\\users\\|/home/|[A-Za-z]:\\users)")
_HEX = re.compile(r"^[0-9a-fA-F]{8,}$")   # sha/commit/tag -> GIU
# Gia tri thuan so/ty-le/percent (so lieu toan hoc, kich thuoc, page) -> KHONG PII-scan
# (tranh chan nham mot con so 10 chu so thanh 'dien thoai').
_BARE_NUMBER = re.compile(r"^-?[\d][\d.,_\s:%xXa-fA-F]*$")


def _looks_like_path(v: str) -> bool:
    return bool(_WIN_ABS.match(v) or _UNC.match(v) or _USER_DIR.search(v) or _UNIX_ABS.match(v))


def sanitize_public(obj: Any, _key: str = "") -> Any:
    """Tra ve ban sao metadata da loai bo thong tin duong dan/rieng tu.

    Quy tac an toan nhung KHONG chan nham:
    - Chuoi la DUONG DAN tuyet doi (Win/UNC/Unix co sep) -> PATH_REDACTED; neu khoa
      cua no la khoa-loai-duong-dan (dir/path/root/file...) thi LOAI BOT khoa.
    - Gia tri bool/số/hex/ten model (khong phai duong dan) -> GIU, KE CA khi ten khoa
      co chua 'root'/'dir' (vi du `model_root_present`: bool, phai giu).
    - Email/phone trong chuoi van ban thuong (khong thuan so) -> redact.
    """
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            kv = str(k)
            is_path_key = bool(_BLOCKED_KEYS.search(kv))
            if isinstance(v, str) and _looks_like_path(v):
                if is_path_key:
                    continue                       # khoa path + gia tri path -> bo khoa
                out[k] = "[PATH_REDACTED]"         # gia tri path trong khoa lanh mạnh -> redact
                continue
            out[k] = sanitize_public(v, kv)
        return out
    if isinstance(obj, list):
        return [sanitize_public(x, _key) for x in obj]
    if isinstance(obj, str):
        if _HEX.match(obj):          # checksum/sha/tag -> giu nguyen
            return obj
        if _looks_like_path(obj):    # duong dan -> loai
            return "[PATH_REDACTED]"
        # chi doi phat hien PII voi chuoi khong thuan so (tranh chan nham so lieu toan hoc)
        if not _BARE_NUMBER.match(obj):
            red = obj
            for hit in scan_pii(obj):
                red = red.replace(_match_snippet(obj, hit["type"]), f"[{hit['type']}_REDACTED]")
            if red != obj:
                return red
        return obj
    return obj


def _match_snippet(text: str, label: str) -> str:
    """Tra ve doan khop dau tien cua mau PII (email/phone...) trong text."""
    from .pii import PATTERNS
    pat = PATTERNS.get(label)
    if not pat:
        return ""
    m = pat.search(text)
    return m.group(0) if m else ""


def has_private_leak(obj: Any) -> List[str]:
    """Quet sau cung: tra ve danh sach goi y con sot duong dan/PII (cho test)."""
    leaks: List[str] = []

    def walk(o: Any, key: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if _BLOCKED_KEYS.search(str(k)) and isinstance(v, str) and _looks_like_path(v):
                    leaks.append(f"{key}.{k}:path")
                walk(v, f"{key}.{k}")
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{key}[{i}]")
        elif isinstance(o, str):
            if _looks_like_path(o):
                leaks.append(f"{key}:path")
            elif not _HEX.match(o) and not _BARE_NUMBER.match(o):
                for h in scan_pii(o):
                    leaks.append(f"{key}:{h['type']}")

    walk(obj, "$")
    return leaks
