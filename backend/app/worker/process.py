from __future__ import annotations

"""Worker OCR tien trinh rieng (Windows spawn-safe).

Khong nap model luc import. Chi nap trong main() sau khi doc arg.
Protocol: JSON-lines tren stdin/stdout.
"""

import argparse
import dataclasses
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from ..ocr.base import OcrPageResult
from ..settings import OcrSettings
from . import protocol


def _read_pinned_identity(path_arg: Optional[str]):
    """Doc identity model da full-hash boi JobManager. -> (pinned | None, err | None).

    File pin hong/khong doc duoc KHONG lam chet worker: engine se tu full-hash (worker
    bao `pin_file_error` + identity self); JobManager la ben BAT BUOC doi chieu tag
    truoc khi ghi cache (F2 — `model_identity.cache_tag_for_write`).
    """
    if not path_arg:
        return None, None
    p = Path(path_arg)
    if not p.exists():
        return None, "pinned_identity_file_missing"
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"pinned_identity_file_invalid:{type(e).__name__}"


def build_engine(args) -> object:
    if args.engine == "fake":
        from ..ocr.fake_engine import RecordingFakeEngine
        fail_pages = [int(p) for p in (args.fail_pages.split(",") if args.fail_pages else [])]
        template = None
        if args.block_template and Path(args.block_template).exists():
            with open(args.block_template, "r", encoding="utf-8") as f:
                raw = json.load(f)
            template = {int(k): v for k, v in raw.items()}
        # F2: fake engine cung nhan identity pin + ten model de kiem cung hop dong
        # danh tinh nhu PaddleVLAdapter (test tich hop phu dung duong that).
        pinned, pin_err = _read_pinned_identity(args.pinned_identity_file)
        override = None
        if getattr(args, "fake_identity_override_file", None):
            try:
                with open(args.fake_identity_override_file, "r", encoding="utf-8") as f:
                    override = json.load(f)
            except Exception as e:
                override = {"model_rev_error": f"override_invalid:{type(e).__name__}"}
        return RecordingFakeEngine(dispatch_log_path=Path(args.dispatch_log) if args.dispatch_log else None,
                                   block_template=template, fail_pages=fail_pages,
                                   page_delay_s=args.page_delay,
                                   pinned_identity=pinned,
                                   model_names=[args.layout_model, args.vl_model],
                                   pin_file_error=pin_err,
                                   identity_override=override)
    if args.engine == "paddle":
        from ..ocr.paddle_adapter import PaddleVLAdapter
        pinned, pin_err = _read_pinned_identity(args.pinned_identity_file)
        adapter = PaddleVLAdapter(OcrSettings(
            pipeline_version=args.pipeline_version,
            layout_model_name=args.layout_model,
            vl_rec_model_name=args.vl_model,
            device=args.device,
            render_dpi=args.dpi,
        ), pinned_identity=pinned)
        adapter.pin_file_error = pin_err  # ghi vao meta de JobManager log ro
        return adapter
    raise SystemExit(f"engine khong ho tro: {args.engine}")


def heartbeat_loop(stop: threading.Event) -> None:
    while not stop.wait(10.0):
        _emit({"evt": "heartbeat", "t": time.time()})


def _emit(obj: dict) -> None:
    sys.stdout.write(protocol.encode(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--dispatch-log", default=None)
    parser.add_argument("--fail-pages", default=None)
    parser.add_argument("--block-template", default=None)
    parser.add_argument("--pipeline-version", default="v1.6")
    parser.add_argument("--layout-model", default="PP-DocLayoutV3")
    parser.add_argument("--vl-model", default="PaddleOCR-VL-1.6")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--page-delay", type=float, default=0.0)
    parser.add_argument("--pinned-identity-file", default=None,
                        help="JSON identity model da full-hash DUNG 1 lan/job boi JobManager")
    parser.add_argument("--fake-identity-override-file", default=None,
                        help="CHI DUNG CHO TEST: JSON ghi de meta danh tinh cua engine fake")
    args = parser.parse_args(argv)

    _emit({"evt": "hello", "pid": __import__("os").getpid(),
           "protocol": protocol.PROTOCOL_VERSION})
    _emit({"evt": "model_loading"})
    t0 = time.time()
    try:
        engine = build_engine(args)
        meta = engine.load()
    except Exception:
        _emit({"evt": "model_failed", "error": traceback.format_exc(limit=8)})
        return 2
    _emit({"evt": "model_ready", "load_s": round(time.time() - t0, 2), "meta": meta})

    stop_hb = threading.Event()
    hb = threading.Thread(target=heartbeat_loop, args=(stop_hb,), daemon=True)
    hb.start()

    for line in sys.stdin:
        msg = protocol.decode(line)
        if not msg:
            continue
        cmd = msg.get("cmd")
        if cmd == "shutdown":
            break
        if cmd != "page":
            continue
        job_id, page_no = msg.get("job_id"), msg.get("page_no")
        attempt_id, config_hash = msg.get("attempt_id"), msg.get("config_hash")
        image_path = Path(msg.get("image_path", ""))
        _emit({"evt": "page_started", "job_id": job_id, "page_no": page_no,
               "attempt_id": attempt_id})
        try:
            result: OcrPageResult = engine.recognize_page(image_path, int(page_no))
            payload = dataclasses.asdict(result)
            _emit({"evt": "page_result", "job_id": job_id, "page_no": page_no,
                   "attempt_id": attempt_id, "config_hash": config_hash,
                   "result": payload})
        except Exception:
            _emit({"evt": "page_failed", "job_id": job_id, "page_no": page_no,
                   "attempt_id": attempt_id,
                   "error": f"{type(sys.exc_info()[0]).__name__}: OCR that bai",
                   "traceback_tail": traceback.format_exc(limit=6)[-2000:]})
    stop_hb.set()
    try:
        engine.unload()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
