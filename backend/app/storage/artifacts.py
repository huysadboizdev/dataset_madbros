from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Viết file tạm cùng thư mục -> fsync -> đổi tên nguyên tử."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def read_json(path: Path) -> Optional[dict]:
    import json
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def canonical_hash(obj: object) -> str:
    import json
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def sanitize_display_name(name: str) -> str:
    """Chỉ dùng cho nhãn hiển thị/manifest; KHÔNG dùng làm đường dẫn vật lý."""
    base = os.path.basename(name or "document.pdf")
    cleaned = "".join(c for c in base if c.isprintable() and c not in '<>:"/\\|?*').strip()
    return (cleaned or "document.pdf")[:180]
