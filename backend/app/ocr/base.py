from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class OcrBlock:
    type: str  # paragraph|heading|formula|table|list|skipped_visual|other
    text: Optional[str] = None
    latex: Optional[str] = None
    bbox: Optional[List[float]] = None  # pixel, origin top-left
    confidence: Optional[float] = None
    order: int = 0


@dataclass
class OcrPageResult:
    page_no: int
    blocks: List[OcrBlock] = field(default_factory=list)
    coordinate_space: Dict[str, Any] = field(default_factory=lambda: {
        "unit": "pixel", "width": 0, "height": 0, "origin": "top_left"
    })
    engine_name: str = ""
    engine_version: str = ""
    markdown_hint: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class OcrEngine(Protocol):
    name: str

    def load(self) -> Dict[str, Any]:
        """Nạp model một lần. Trả metadata (version, model dirs...)."""
        ...

    def recognize_page(self, image_path: Path, page_no: int) -> OcrPageResult:
        """CHỈ nhận ảnh của đúng một trang đã chọn."""
        ...

    def unload(self) -> None:
        ...
