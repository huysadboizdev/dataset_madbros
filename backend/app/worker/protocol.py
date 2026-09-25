from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

PROTOCOL_VERSION = "1"


@dataclass
class PageRequest:
    job_id: str
    page_no: int
    attempt_id: str
    config_hash: str
    image_path: str

    def to_cmd(self) -> dict:
        return {"cmd": "page", "job_id": self.job_id, "page_no": self.page_no,
                "attempt_id": self.attempt_id, "config_hash": self.config_hash,
                "image_path": self.image_path}


def encode(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def decode(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def matches_identity(evt: Dict[str, Any], req: PageRequest) -> bool:
    return (evt.get("job_id") == req.job_id and evt.get("page_no") == req.page_no
            and evt.get("attempt_id") == req.attempt_id)
