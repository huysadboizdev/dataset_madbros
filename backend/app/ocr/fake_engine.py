from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import OcrBlock, OcrPageResult


class RecordingFakeEngine:
    """Engine FAKE chỉ dùng trong TEST có nhãn.

    Ghi lại mọi trang được yêu cầu nhận dạng vào dispatch_log để chứng minh
    dispatcher không gọi OCR ngoài phạm vi. KHÔNG bật trong launcher production.

    F2: engine fake cũng tuân THỦ HỢP ĐỒNG DANH TÍNH MODEL như `PaddleVLAdapter` —
    tự full-hash model (thư mục giả lập do `PDFCLEANER_MODEL_ROOT` trỏ tới) rồi đối
    chiếu với identity pin của job (`model_names` = tên khai báo trong settings). Nhờ
    vậy test tích hợp phủ được đúng đường `JobManager → WorkerSupervisor → process →
    engine.load → cache tag`, thay vì chỉ test hàm đơn lẻ.
    """

    name = "fake_recording"

    def __init__(self, dispatch_log_path: Optional[Path] = None,
                 block_template: Optional[Dict[int, List[dict]]] = None,
                 fail_pages: Optional[List[int]] = None,
                 page_delay_s: float = 0.0,
                 pinned_identity: Optional[Dict[str, Any]] = None,
                 model_names: Optional[List[str]] = None,
                 model_root: Optional[Path] = None,
                 verify_identity: bool = True,
                 pin_file_error: Optional[str] = None,
                 identity_override: Optional[Dict[str, Any]] = None):
        self.dispatch_log_path = Path(dispatch_log_path) if dispatch_log_path else None
        self.block_template = block_template or {}
        self.fail_pages = set(fail_pages or [])
        self.page_delay_s = page_delay_s
        self.loaded = False
        self.pinned_identity = pinned_identity
        self.model_names = list(model_names or [])
        self.model_root = Path(model_root) if model_root else None
        self.verify_identity = verify_identity
        self.pin_file_error = pin_file_error
        # CHI DUNG CHO TEST: gia lap worker bao identity khac (hoac khong xac minh duoc)
        # de kiem phia JobManager tu choi ghi cache duoi tag cu (F2 — finding 3.2).
        self.identity_override = identity_override

    def load(self) -> Dict[str, Any]:
        self.loaded = True
        meta: Dict[str, Any] = {"engine": self.name, "version": "test", "fake": True}
        if self.pin_file_error:
            meta["pin_file_error"] = str(self.pin_file_error)[:200]
        if not self.verify_identity:
            return meta
        from . import model_identity as mi
        try:
            root = self.model_root or mi.official_root()
            names = self.model_names or ["PP-DocLayoutV3", "PaddleOCR-VL-1.6"]
            if self.pinned_identity:
                fps, tag, note = mi.verify_pinned(self.pinned_identity, root, names,
                                                  full_recheck=True)
                meta.update({"model_fp": fps, "model_rev": tag,
                             "identity_source": "pinned_job", "recheck": note})
            else:
                fps = {n: mi.model_fingerprint(n, root, full=True) for n in names}
                meta.update({"model_fp": fps,
                             "model_rev": mi.identity_from_fps(list(fps.values())),
                             "identity_source": "engine_load_self",
                             "recheck": "full_sha256_all_artifacts"})
        except mi.ModelChangedSincePin:
            raise  # model khac identity da pin -> worker bao model_failed, khong giam nhe
        except Exception as e:
            meta["model_rev_error"] = str(e)
        if self.identity_override:
            meta.update(self.identity_override)
        return meta

    def _log(self, page_no: int) -> None:
        if self.dispatch_log_path is None:
            return
        with open(self.dispatch_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page_no": page_no, "op": "recognize"}) + "\n")

    def recognize_page(self, image_path: Path, page_no: int) -> OcrPageResult:
        self._log(page_no)
        if self.page_delay_s:
            import time
            time.sleep(self.page_delay_s)
        if page_no in self.fail_pages:
            raise RuntimeError(f"fake OCR error for page {page_no}")
        if page_no in self.block_template:
            specs = self.block_template[page_no]
        else:
            specs = [{"type": "paragraph", "text": f"Noi dung gia dinh trang {page_no}."}]
        blocks = [OcrBlock(type=s.get("type", "paragraph"), text=s.get("text"),
                           latex=s.get("latex"), bbox=s.get("bbox", [0, 0, 100, 20]),
                           order=i) for i, s in enumerate(specs)]
        return OcrPageResult(page_no=page_no, blocks=blocks,
                             engine_name=self.name, engine_version="test")

    def unload(self) -> None:
        self.loaded = False
