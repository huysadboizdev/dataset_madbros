from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cleaning.normalize import (CLEANING_VERSION, blocks_from_direct_text,
                                  evaluate_text_layer, normalize_blocks)
from ..cleaning.pii import scan_pii
from ..cleaning.validators import detect_empty_with_context, latex_basic_check, validate_page_payload
from ..db import Database, _now
from ..ocr import model_identity as mi
from ..ocr.base import OcrBlock, OcrPageResult
from ..settings import Settings
from ..storage.artifacts import (atomic_write_bytes, atomic_write_text, canonical_hash,
                                 new_id, sha256_bytes, sha256_file)
from ..worker.supervisor import WorkerDead, WorkerSupervisor
from . import pdf_service, revision_service


class JobError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


import re

FORMULA_RE = re.compile(
    "[∑∏∫√±×÷≤≥≠≈∞∂∈∉⊂⊃∪∩→⇒"      # toan unicode
    "\u00b2\u00b3\u00b9"
    "\u2074-\u209f"                      # upper/subscripts
    "]|\\frac|\\sqrt|\\dfrac|[_^]\\{|\\^\\d|\\^="
)


def _formula_suspect(text: str) -> bool:
    """Nghi van ban co cong thuc ma lop chu khong giu duoc y nghia."""
    return bool(FORMULA_RE.search(text or ""))


def compute_config_hash(settings: Settings, engine: str, mode: str, ocr_again: bool) -> str:
    o = settings.ocr
    return canonical_hash({
        "engine": engine, "device": o.device,
        "pipeline_version": o.pipeline_version,
        "layout_model": o.layout_model_name, "vl_model": o.vl_rec_model_name,
        "render_dpi": o.render_dpi, "cleaning": CLEANING_VERSION,
        "mode": mode, "ocr_again": ocr_again,
    })[:16]


class JobManager:
    def __init__(self, settings: Settings, db: Database, engine: str = "paddle",
                 engine_extra_args: Optional[List[str]] = None,
                 model_ready_timeout_s: int = 1200):
        self.settings = settings
        self.db = db
        self.engine = engine
        self.engine_extra_args = list(engine_extra_args or [])
        self.model_ready_timeout_s = model_ready_timeout_s
        self._mu = threading.RLock()
        self._supervisors: Dict[str, WorkerSupervisor] = {}
        self._flags: Dict[str, Dict[str, threading.Event]] = {}
        self._current: Dict[str, Optional[int]] = {}
        self._model_phase: Dict[str, Optional[str]] = {}
        self._durations: Dict[str, deque] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._reprocess: Dict[str, str] = {}
        self._phase: Dict[str, Optional[str]] = {}
        self._pinned_tag: Dict[str, str] = {}
        self._pinned_fp: Dict[str, Dict[str, Any]] = {}
        # F2: job da tung phat hien lech identity -> KHONG duoc tin tag pin nua (cam cache READ).
        self._identity_bad: Dict[str, bool] = {}

    # ---------- tao job ----------

    def create_job(self, document_id: str, selected_pages: List[int], mode: str,
                   ocr_again: bool, notes: Optional[Dict[str, str]] = None) -> str:
        doc = self.db.get_document(document_id)
        if doc is None:
            raise JobError("NOT_FOUND", "Tài liệu không tồn tại")
        page_count = doc["page_count"]
        if not selected_pages:
            raise JobError("NO_PAGES", "Phải chọn ít nhất 1 trang")
        if any(isinstance(p, bool) or not isinstance(p, int) for p in selected_pages):
            raise JobError("BAD_TYPE", "Số trang phải là số nguyên")
        bad = sorted({p for p in selected_pages if p < 1 or p > page_count})
        if bad:
            raise JobError("OUT_OF_RANGE", f"Trang ngoài phạm vi 1..{page_count}: {bad}")
        pages = sorted(set(selected_pages))
        config_hash = compute_config_hash(self.settings, self.engine, mode, ocr_again)
        job_id = new_id("job")
        stmts = [(
            "INSERT INTO jobs(job_id, document_id, selected_pages_json, pages_fingerprint,"
            " mode, ocr_again, config_hash, status, notes_json, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (job_id, document_id, json.dumps(pages), ",".join(map(str, pages)),
             mode, 1 if ocr_again else 0, config_hash, "CREATED",
             json.dumps(notes or {}, ensure_ascii=False), _now()),
        )]
        for p in pages:
            stmts.append(("INSERT INTO page_runs(job_id, page_no, status) VALUES(?,?, 'PENDING')",
                          (job_id, p)))
        self.db.executemany_commit(stmts)
        return job_id

    # ---------- dieu khien ----------

    def start(self, job_id: str) -> None:
        with self._mu:
            job = self._must_job(job_id)
            if job["status"] not in ("CREATED", "PAUSED", "INTERRUPTED", "CANCELLED",
                                     "COMPLETED_WITH_ERRORS"):
                raise JobError("BAD_STATE", f"Không thể chạy job ở trạng thái {job['status']}")
            running = self.db.running_job()
            if running is not None and running["job_id"] != job_id:
                raise JobError("BUSY", f"Đang có job khác chạy: {running['job_id']}")
            if job["status"] == "CREATED":
                pending = self.db.query(
                    "SELECT 1 FROM page_runs WHERE job_id=? AND status='PENDING'", (job_id,))
                if not pending:
                    raise JobError("NO_PAGES", "Không còn trang chờ để xử lý")
            self.db.set_job_status(job_id, "RUNNING")
            self._flags[job_id] = {"pause": threading.Event(), "cancel": threading.Event()}
            # Danh tinh model duoc XAC MINH DAY DU (SHA-256) MOT LAN trong runner thread
            # (khong hash 1.9GB tren request HTTP, khong hash moi trang) roi PIN cho ca job.
            self._durations.setdefault(job_id, deque(maxlen=8))
            self._current[job_id] = None
            t = threading.Thread(target=self._run_job, args=(job_id,), daemon=True,
                                 name=f"jobrunner-{job_id}")
            self._threads[job_id] = t
            t.start()

    def pause(self, job_id: str) -> None:
        with self._mu:
            job = self._must_job(job_id)
            if job["status"] != "RUNNING":
                raise JobError("BAD_STATE", "Chỉ tạm dừng được job đang chạy")
            self.db.set_job_status(job_id, "PAUSE_REQUESTED")
            self._flags.get(job_id, {}).get("pause", threading.Event()).set()

    def cancel(self, job_id: str) -> None:
        with self._mu:
            job = self._must_job(job_id)
            if job["status"] not in ("RUNNING", "PAUSE_REQUESTED", "PAUSED", "CREATED"):
                raise JobError("BAD_STATE", f"Không hủy được job {job['status']}")
            flags = self._flags.get(job_id)
            if flags:
                flags["cancel"].set()
            else:
                self.db.set_job_status(job_id, "CANCELLED", finished=True)

    def retry_page(self, job_id: str, page_no: int) -> None:
        with self._mu:
            job = self._must_job(job_id)
            if job["status"] in ("RUNNING", "PAUSE_REQUESTED"):
                raise JobError("BAD_STATE", "Job đang chạy; chờ job kết thúc rồi thử lại")
            run = self.db.query_one("SELECT * FROM page_runs WHERE job_id=? AND page_no=?",
                                    (job_id, page_no))
            if run is None:
                raise JobError("NOT_FOUND", "Trang không thuộc job")
            if run["status"] not in ("FAILED", "INTERRUPTED"):
                raise JobError("BAD_STATE", "Chỉ thử lại được trang lỗi hoặc bị gián đoạn")
            self.db.execute("UPDATE page_runs SET status='PENDING', error=NULL WHERE job_id=? AND page_no=?",
                            (job_id, page_no))
        self.start(job_id)

    # ---------- OCR lai mot trang: revision moi, khong ghi de ban dang dung ----------

    def reprocess_page(self, job_id: str, page_no: int) -> str:
        with self._mu:
            job = self._must_job(job_id)
            if job["status"] in ("RUNNING", "PAUSE_REQUESTED"):
                raise JobError("BAD_STATE", "Job đang chạy; không OCR lại song song")
            run = self.db.query_one("SELECT * FROM page_runs WHERE job_id=? AND page_no=?",
                                    (job_id, page_no))
            if run is None:
                raise JobError("NOT_FOUND", "Trang không thuộc job")
            if run["status"] == "RUNNING":
                raise JobError("BAD_STATE", "Trang đang được xử lý")
            key = f"{job_id}:{page_no}"
            if self._reprocess.get(key) == "running":
                raise JobError("BUSY", "Đang OCR lại trang này")
            self._reprocess[key] = "running"
            flags = {"pause": threading.Event(), "cancel": threading.Event()}
            self._flags[f"rp::{key}"] = flags
            t = threading.Thread(target=self._reprocess_worker, args=(job_id, page_no, flags, key),
                                 daemon=True, name=f"reprocess-{key}")
            t.start()
        return "running"

    def _reprocess_worker(self, job_id: str, page_no: int,
                          flags: Dict[str, threading.Event], key: str) -> None:
        try:
            fp = self._current_model_fp()
            with self._mu:
                self._pinned_tag[job_id] = fp["tag"]
                self._pinned_fp[job_id] = fp
            self._write_pinned_identity(job_id)
            ok = self._process_page(job_id, page_no, flags, force_ocr=True, set_active=False)
            self._reprocess[key] = "done" if ok else "error"
        except Exception:
            self._reprocess[key] = "error"
        finally:
            sup = self._supervisors.pop(f"rp::{key}", None) or self._supervisors.pop(job_id, None)
            if sup:
                sup.terminate()

    def reprocess_state(self, job_id: str, page_no: int) -> str:
        return self._reprocess.get(f"{job_id}:{page_no}", "idle")

    def shutdown(self) -> None:
        """Đóng app: job đang chạy -> INTERRUPTED, trang đang dở -> INTERRUPTED."""
        with self._mu:
            for job_id, sup in list(self._supervisors.items()):
                try:
                    sup.terminate(grace_s=1.0)
                except Exception:
                    pass
            for job in self.db.query("SELECT job_id FROM jobs WHERE status IN ('RUNNING','PAUSE_REQUESTED')"):
                self.db.set_job_status(job["job_id"], "INTERRUPTED", finished=True)
                self.db.execute("UPDATE page_runs SET status='INTERRUPTED' WHERE job_id=? AND status='RUNNING'",
                                (job["job_id"],))

    @staticmethod
    def reconcile_on_boot(db: Database) -> List[str]:
        """Mở lại sau khi tắt đột ngột: không tự chạy lại; đánh dấu gián đoạn."""
        rows = db.query("SELECT job_id FROM jobs WHERE status IN ('RUNNING','PAUSE_REQUESTED')")
        ids = [r["job_id"] for r in rows]
        for jid in ids:
            db.set_job_status(jid, "INTERRUPTED", finished=True)
            db.execute("UPDATE page_runs SET status='INTERRUPTED' WHERE job_id=? AND status='RUNNING'",
                       (jid,))
        return ids

    @staticmethod
    def cleanup_orphan_artifacts(db: Database, settings: Settings) -> Dict[str, int]:
        """Doi sang sau khi reconcile: khong con job RUNNING -> don dep san pham tam.

        - PNG/anh render trong <job>/tmp/ cua moi job (moi lan chay luu vao
          <job>/tmp/ <page>_<attempt> ; sau hard-kill con sot -> don toan bo tmp cua job
          KHONG chay). KHONG cham vao revisions/artifact da commit.
        - `*.part` trong raw_dir: upload gian doan truoc khi rename.
        - file raw *.pdf trong raw_dir KHONG duoc bat ky document/job nao tham chieu
          -> orphan sau khi replace thanh cong nhung DB insert that bai -> xoa, nhung chi
          khi chac chan khong co bang nao tro toi (an toan du lieu).
        Khong gia dinh FS va SQLite co mot transaction atomic chung; day la buoc phuc hoi.
        """
        removed = {"tmp": 0, "part": 0, "raw_orphan": 0}
        # job dang RUNNING van duoc phep ton tai file tmp (khong phai boot). Kiem tra DB.
        active_jobs = {r["job_id"] for r in
                       db.query("SELECT job_id FROM jobs WHERE status IN ('RUNNING','PAUSE_REQUESTED')")}
        jobs_root = settings.jobs_dir
        if jobs_root.exists():
            for jd in jobs_root.iterdir():
                if not jd.is_dir() or jd.name in active_jobs:
                    continue
                tmp = jd / "tmp"
                if not tmp.exists():
                    continue
                for f in tmp.rglob("*"):  # bao toan MOI loai file, khong chi theo duoi .tmp/.part
                    if f.is_file():
                        try:
                            f.unlink()
                            removed["tmp"] += 1
                        except OSError:
                            pass
        # *.part con sot
        raw_dir = settings.raw_dir
        if raw_dir.exists():
            for f in raw_dir.glob("*.part"):
                try:
                    f.unlink()
                    removed["part"] += 1
                except OSError:
                    pass
            # raw orphan: file khong duoc document nao tro toi
            referenced = {Path(r["raw_path"]).name for r in db.query("SELECT raw_path FROM documents")}
            for f in raw_dir.glob("*.pdf"):
                if f.name not in referenced:
                    try:
                        f.unlink()
                        removed["raw_orphan"] += 1
                    except OSError:
                        pass
        # thu muc tmp dung cua app
        if settings.tmp_dir.exists():
            for f in settings.tmp_dir.rglob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                        removed["tmp"] += 1
                    except OSError:
                        pass
        return removed

    def _must_job(self, job_id: str):
        job = self.db.get_job(job_id)
        if job is None:
            raise JobError("NOT_FOUND", "Job không tồn tại")
        return job

    # ---------- runner ----------

    def _run_job(self, job_id: str) -> None:
        flags = self._flags[job_id]
        # Xac minh day du model TREN DIA MOT LAN cho ca job (SHA-256 weights/config),
        # pin tag + provenance. Moi trang dung LAI gia tri nay -> khong hash moi trang.
        # Job dang chay giu nguyen danh tinh pin -> khong tron hai model trong cung job.
        fp = self._current_model_fp()
        with self._mu:
            self._pinned_tag[job_id] = fp["tag"]
            self._pinned_fp[job_id] = fp
        self._write_pinned_identity(job_id)
        failed_seen = False
        try:
            while True:
                todo = self.db.query(
                    "SELECT page_no FROM page_runs WHERE job_id=? AND status IN ('PENDING','INTERRUPTED')"
                    " ORDER BY page_no", (job_id,))
                if not todo:
                    break
                page_no = todo[0]["page_no"]
                if flags["cancel"].is_set():
                    break
                if flags["pause"].is_set():
                    self.db.set_job_status(job_id, "PAUSED")
                    self._current[job_id] = None
                    return
                try:
                    ok = self._process_page(job_id, page_no, flags)
                    failed_seen = failed_seen or not ok
                except Exception:
                    failed_seen = True
                    self._mark_page_failed(job_id, page_no, "INTERNAL", _tail_exception())
                if flags["pause"].is_set():
                    self.db.set_job_status(job_id, "PAUSED")
                    self._current[job_id] = None
                    return
            with self._mu:
                job = self._must_job(job_id)
                if flags["cancel"].is_set():
                    self.db.set_job_status(job_id, "CANCELLED", finished=True)
                    self.db.execute(
                        "UPDATE page_runs SET status='INTERRUPTED' WHERE job_id=? AND status='RUNNING'",
                        (job_id,))
                else:
                    final_rows = self.db.query(
                        "SELECT status FROM page_runs WHERE job_id=?", (job_id,))
                    statuses = [r["status"] for r in final_rows]
                    has_bad = any(s in ("FAILED", "INTERRUPTED") for s in statuses)
                    self.db.set_job_status(
                        job_id, "COMPLETED_WITH_ERRORS" if (has_bad or failed_seen) else "COMPLETED",
                        finished=True)
        finally:
            self._current[job_id] = None
            sup = self._supervisors.pop(job_id, None)
            if sup:
                sup.terminate()
            t = self._threads.pop(job_id, None)
            if t is threading.current_thread():
                pass

    def _log_op(self, job_id: str, op: str, page_no: int, extra: Optional[dict] = None) -> None:
        """Instrumentation: trang nào THỰC SỰ đi vào render/extraction/OCR."""
        rec = {"t": _now(), "job_id": job_id, "page_no": page_no, "op": op}
        if extra:
            rec.update(extra)
        d = self.settings.jobs_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "dispatch_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- danh tinh model + cache ----------

    def _model_names(self) -> List[str]:
        o = self.settings.ocr
        return [x for x in (o.layout_model_name, o.vl_rec_model_name) if x]

    def _current_model_fp(self) -> Dict[str, Any]:
        """Xac minh model TREN DIA 1 LAN (SHA-256 DAY DU weights + config) va tra ve
        {tag, full_ok}. Duoc goi DUC NHAT tai dau _run_job roi PIN cho ca job —
        KHONG goi moi trang (khong hash 1.9GB moi trang).

        tag='unresolved' khi root/model khong ton tai -> cache READ bi cam, va provenance
        ghi nhan day du (khong the vo tinh dung cache cua model khong kiem duoc).
        """
        try:
            root = mi.official_root()
            if not root.exists():
                return {"tag": "unresolved", "full": {"root": "missing"}}
            names = sorted(filter(None, self._model_names()))
            # SHA-256 DAY DU weights+config chi doc DUNG MOT LAN; tag tinh tu ket qua
            # da verify do (identity_from_fps) -> KHONG hash lai model lan thu hai.
            # F2: khoa fingerprint = TEN THU MUC THAT tren dia (`mi.model_key`) de tag
            # nay TRUNG tag worker tinh khi pipeline tu resolve ten model khac di
            # ('PaddleOCR-VL-1.6' khai bao vs 'PaddleOCR-VL-1.6-0.9B' pipeline tra ve).
            fps: Dict[str, Any] = {}
            for n in names:
                fps[mi.model_key(root, n)] = mi.model_fingerprint(n, root, full=True)
            # CAI DAT "all": chi khi MOI model deu kiem xac duoc (du weight + du
            # artifact) moi tinh tag; thieu/mot model loi -> unresolved -> cam cache
            # (dung identity mot phan tra cache la sai — finding "inventory thieu").
            if len(names) == 0 or not all(f.get("status") == "ok" for f in fps.values()):
                return {"tag": "unresolved", "full": fps}
            return {"tag": mi.identity_from_fps(list(fps.values())), "full": fps}
        except Exception:
            return {"tag": "unresolved", "full": {"error": True}}

    def _pinned_identity_path(self, job_id: str) -> Path:
        # ten file an toan tren Windows (job key reprocess chua ':')
        return self.settings.jobs_dir / f"{job_id.replace(':', '_')}.pinned_identity.json"

    def _write_pinned_identity(self, job_id: str) -> None:
        """Ghi identity DA FULL-HASH DUNG 1 lan/job ra file cho worker.

        Worker (paddle) re-check NHANH (inventory + size + sha file nho + sample_fp
        weight) thay vi full-hash lai weights — khong ton them lan doc GB moi load
        (S4 — finding 2). Chi ghi khi tag resolved; tag 'unresolved' -> khong ghi:
        worker tu full-hash, va cache READ van bi cam o phia job manager.
        """
        with self._mu:
            fp = self._pinned_fp.get(job_id)
        if not fp or fp.get("tag") == "unresolved":
            return
        payload = {"tag": fp.get("tag"), "fps": fp.get("full") or {}}
        try:
            atomic_write_text(self._pinned_identity_path(job_id),
                              json.dumps(payload, ensure_ascii=False))
        except OSError as e:
            # KHONG nuot im lang (finding 3.2): worker se tu full-hash va bao
            # `pin_file_error`; manager BAT BUOC doi chieu tag truoc khi ghi cache.
            self._log_op(job_id, "pinned_identity_write_failed", 0,
                         {"err": type(e).__name__})

    def _cache_path(self, doc_hash: str, page_no: int, config_hash: str, tag: str) -> Path:
        return (self.settings.data_dir / "cache" / "ocr" / doc_hash /
                f"p{page_no:04d}_{config_hash}_{tag}.json")

    def _process_page(self, job_id: str, page_no: int, flags: Dict[str, threading.Event],
                      force_ocr: bool = False, set_active: bool = True) -> bool:
        job = self._must_job(job_id)
        doc = self.db.get_document(job["document_id"])
        config_hash = job["config_hash"]
        ocr_again = bool(job["ocr_again"]) or force_ocr
        attempt = self.db.query_one(
            "SELECT attempt FROM page_runs WHERE job_id=? AND page_no=?", (job_id, page_no))["attempt"] + 1
        self.db.execute(
            "UPDATE page_runs SET status='RUNNING', attempt=?, method='unknown', error=NULL"
            " WHERE job_id=? AND page_no=?", (attempt, job_id, page_no))
        self._current[job_id] = page_no
        self._phase[job_id] = "reading"
        self._log_op(job_id, "dispatched", page_no, {"attempt": attempt})
        t0 = time.time()
        pdf = pdf_service.PdfDoc(Path(doc["raw_path"]))
        try:
            # 1) lop chu truc tiep (chi doc dung trang nay) + profile bo cuc trang
            text = pdf.extract_page_text(page_no)
            quality = evaluate_text_layer(text)
            profile = pdf.page_content_profile(page_no)
            use_direct, cov_flags, _reasons = pdf_service.decide_direct_or_ocr(quality, profile)
            if use_direct and not ocr_again and not _formula_suspect(text):
                self._log_op(job_id, "direct_extract", page_no,
                             {"chars": quality["length"], "flags": cov_flags})
                blocks = blocks_from_direct_text(text, page_no, (0, 0), self.settings.ocr.render_dpi)
                self._phase[job_id] = "saving"
                self._commit_page(job_id, page_no, doc, config_hash, blocks,
                                  method="direct", attempt=attempt, t0=t0,
                                  engine_meta={"engine": "pdf_text_layer",
                                               "page_profile": profile},
                                  warnings=list(cov_flags))
                return True

            # 2) cache OCR theo (doc hash, page, config, danh tinh model THAT tren dia).
            #    Tag duoc XAC MINH DAY DU (SHA-256) va PIN MOT LAN dau _run_job -> moi trang
            #    dung LAI gia tri do, KHONG hash model 1.9GB moi trang. Vi dung full hash nen
            #    bat ca noi dung weight ngoai vung sample (head/mid/tail) ma van cung kich thuoc.
            #    Cam cache READ khi 'unresolved' (model khong kiem xac duoc tren may).
            with self._mu:
                pinned = self._pinned_fp.get(job_id)
                identity_bad = bool(self._identity_bad.get(job_id))
            if not pinned:
                pinned = self._current_model_fp()
                with self._mu:
                    self._pinned_tag[job_id] = pinned["tag"]
                    self._pinned_fp[job_id] = pinned
                self._write_pinned_identity(job_id)
            tag = pinned["tag"]
            # Cache READ chi khi tag pin la identity DA FULL-VERIFY tren dia
            # (`unresolved` = khong kiem duoc -> cam doc) VA job nay chua phat hien lech
            # identity (F2: sau khi lech thi tag pin khong con dang tin).
            read_ok = tag != "unresolved" and not identity_bad
            cache_path = (self._cache_path(doc["hash"], page_no, config_hash, tag)
                          if read_ok else None)
            if cache_path is not None and cache_path.exists() and not ocr_again:
                self._log_op(job_id, "cache_hit", page_no, {"tag": tag})
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                blocks = [OcrBlock(**b) for b in payload["blocks"]]
                meta = dict(payload.get("engine_meta", {}))
                meta["coordinate_space"] = payload.get("coordinate_space")
                self._phase[job_id] = "saving"
                self._commit_page(job_id, page_no, doc, config_hash, blocks,
                                  method="cached", attempt=attempt, t0=t0,
                                  engine_meta=meta,
                                  warnings=payload.get("warnings", []))
                return True

            # 3) OCR qua worker: render DUNG trang nay thanh anh mot trang
            self._phase[job_id] = "ocr"
            img_path = self._render_page_png(pdf, job_id, page_no, attempt, doc["document_id"])
            result = self._request_ocr(job_id, page_no, attempt, config_hash, img_path, flags,
                                       mark_failure=set_active)
            if result is None:
                return False
            self._log_op(job_id, "ocr_done", page_no,
                         {"blocks": len(result.blocks), "engine": result.engine_name})
            blocks = result.blocks
            engine_meta = dict(self._supervisors[job_id].engine_meta)
            if engine_meta.get("pin_file_error"):
                self._log_op(job_id, "pin_file_error", page_no,
                             {"err": str(engine_meta["pin_file_error"])[:200]})
            # F2 (finding 3.2): TAG GHI CACHE bat buoc = identity do WORKER THUC DUNG
            # tu full-verify, va phai TRUNG tag manager da pin (neu pin resolved).
            # Lech/khong xac minh duoc -> KHONG ghi cache duoi tag cu.
            write_tag, id_err = mi.cache_tag_for_write(tag, engine_meta)
            engine_meta["disk_identity"] = write_tag or tag
            engine_meta["model_root_present"] = tag != "unresolved"
            if id_err == "pinned_worker_identity_mismatch":
                # Model worker dung KHAC identity da pin -> job nay khong con dung mot
                # danh tinh duy nhat: FAIL ro rang, cam doc cache tiep, khong ghi cache.
                with self._mu:
                    self._identity_bad[job_id] = True
                self._log_op(job_id, "identity_mismatch", page_no,
                             {"code": id_err, "pinned_tag": tag,
                              "worker_tag": str(engine_meta.get("model_rev"))[:32]})
                sup = self._supervisors.pop(job_id, None)
                if sup:
                    sup.terminate(grace_s=0.5)
                if set_active:
                    self._mark_page_failed(
                        job_id, page_no, "MODEL_IDENTITY_MISMATCH",
                        "Danh tinh model worker tra ve khong khop identity da pin cho job "
                        f"({id_err}); KHONG ghi cache duoi tag cu, khong coi trang la da "
                        "xac thuc. Chi tiet: " + str(engine_meta.get("model_rev"))[:64])
                return False
            if id_err:
                # Worker khong bao identity full-verify duoc (vi du metadata pipeline
                # khong doc duoc): KHONG ghi cache, GIU ket qua OCR nhung danh dau ro.
                self._log_op(job_id, "identity_unverified", page_no, {"code": id_err})
                engine_meta["identity_unverified"] = id_err
                write_tag = None
            if write_tag and write_tag != tag:
                # Pin 'unresolved' / pin khong doc duoc, nhung worker TU full-verify duoc:
                # dung tag worker tra ve lam tag cache cua job (khong dung tag cu).
                self._log_op(job_id, "identity_retagged", page_no,
                             {"from": tag, "to": write_tag})
                with self._mu:
                    self._pinned_tag[job_id] = write_tag
            meta = dict(engine_meta)
            meta["coordinate_space"] = result.coordinate_space
            if write_tag:
                # Ghi cache duoi tag DA XAC MINH; xoa cache model khac cua trang nay.
                write_path = self._cache_path(doc["hash"], page_no, config_hash, write_tag)
                raw_payload = asdict(result)
                raw_payload["engine_meta"] = engine_meta
                atomic_write_text(write_path, json.dumps(raw_payload, ensure_ascii=False))
                cache_dir = self.settings.data_dir / "cache" / "ocr" / doc["hash"]
                for old in cache_dir.glob(f"p{page_no:04d}_{config_hash}_*.json"):
                    if old != write_path:
                        try:
                            old.unlink()
                        except OSError:
                            pass
            self._phase[job_id] = "saving"
            self._commit_page(job_id, page_no, doc, config_hash, blocks,
                              method="ocr", attempt=attempt, t0=t0,
                              engine_meta=meta,
                              warnings=result.warnings,
                              set_active=set_active)
            return True
        except WorkerDead:
            if set_active:
                self._mark_page_failed(job_id, page_no, "WORKER_DEAD",
                                       "Worker OCR đã thoát giữa chừng")
            sup = self._supervisors.pop(job_id, None)
            if sup:
                sup.terminate(grace_s=0.5)
            return False
        except pdf_service.PdfOpenError as e:
            if set_active:
                self._mark_page_failed(job_id, page_no, e.code, e.message)
            return False
        except Exception as e:
            if set_active:
                self._mark_page_failed(job_id, page_no, "PAGE_ERROR", _tail_exception())
            return False
        finally:
            self._phase[job_id] = None
            pdf.close()
            tmp = self.settings.jobs_dir / job_id / "tmp" / f"p{page_no:04d}_a{attempt}.png"
            tmp.unlink(missing_ok=True)

    def _render_page_png(self, pdf, job_id: str, page_no: int, attempt: int, doc_id: str) -> Path:
        self._log_op(job_id, "render", page_no)
        png = pdf.render_page_png(page_no, self.settings.ocr.render_dpi)
        p = self.settings.jobs_dir / job_id / "tmp"
        p.mkdir(parents=True, exist_ok=True)
        out = p / f"p{page_no:04d}_a{attempt}.png"
        atomic_write_bytes(out, png)
        return out

    def _ensure_worker(self, job_id: str) -> WorkerSupervisor:
        with self._mu:
            sup = self._supervisors.get(job_id)
            if sup and sup.alive():
                return sup
            sup = WorkerSupervisor(self.settings)
            sup.start(engine=self.engine, extra_args=self.engine_extra_args,
                      identity_file=self._pinned_identity_path(job_id))
            self._supervisors[job_id] = sup
            return sup

    def _request_ocr(self, job_id: str, page_no: int, attempt: int,
                     config_hash: str, img_path: Path,
                     flags: Dict[str, threading.Event],
                     mark_failure: bool = True) -> Optional[OcrPageResult]:
        from ..worker.protocol import PageRequest
        mark = self._mark_page_failed if mark_failure else (lambda *a: None)
        mark_i = self._mark_page_interrupted if mark_failure else (lambda *a: None)
        req = PageRequest(job_id=job_id, page_no=page_no,
                          attempt_id=f"a{attempt}", config_hash=config_hash,
                          image_path=str(img_path))
        sup = self._ensure_worker(job_id)
        try:
            sup.send(req.to_cmd())
        except WorkerDead:
            self._supervisors.pop(job_id, None)
            raise

        def match(evt):
            if evt.get("evt") == "model_loading":
                self._model_phase[job_id] = "loading_model"
            elif evt.get("evt") == "model_ready":
                self._model_phase[job_id] = None
            return evt.get("evt") in ("model_failed", "page_result", "page_failed", "worker_exit")

        deadline = time.time() + self.settings.ocr.page_timeout_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                mark(job_id, page_no, "TIMEOUT",
                     f"Quá {self.settings.ocr.page_timeout_s}s không có kết quả"
                     f" cho trang {page_no}")
                sup2 = self._supervisors.pop(job_id, None)
                if sup2:
                    sup2.terminate(grace_s=0.5)
                return None
            try:
                evt = sup.wait_event(match, timeout=min(1.0, remaining))
            except WorkerDead:
                self._supervisors.pop(job_id, None)
                raise
            if evt is None:
                if not sup.alive():
                    self._supervisors.pop(job_id, None)
                    raise WorkerDead("worker died")
                if flags["cancel"].is_set():
                    sup.terminate(grace_s=2.0)
                    self._supervisors.pop(job_id, None)
                    mark_i(job_id, page_no)
                    return None
                continue
            if evt.get("evt") == "model_failed":
                mark(job_id, page_no, "MODEL_FAILED", str(evt.get("error", ""))[-500:])
                sup.terminate(grace_s=1.0)
                self._supervisors.pop(job_id, None)
                return None
            if evt.get("evt") == "worker_exit":
                self._supervisors.pop(job_id, None)
                raise WorkerDead(f"worker exit {evt.get('returncode')}")
            if not (evt.get("job_id") == job_id and evt.get("page_no") == page_no
                    and evt.get("attempt_id") == req.attempt_id):
                continue  # ket qua den muon tu attempt khac -> bo qua
            if evt.get("evt") == "page_failed":
                mark(job_id, page_no, "OCR_FAILED",
                     str(evt.get("error", "")) + "\n" + str(evt.get("traceback_tail", "")))
                return None
            payload = evt["result"]
            if payload.get("page_no") != page_no:
                mark(job_id, page_no, "PAGE_MISMATCH",
                     "Kết quả OCR mang số trang khác yêu cầu")
                return None
            blocks = [OcrBlock(**b) for b in payload.get("blocks", [])]
            return OcrPageResult(page_no=page_no, blocks=blocks,
                                 coordinate_space=payload.get("coordinate_space"),
                                 engine_name=payload.get("engine_name", ""),
                                 engine_version=payload.get("engine_version", ""),
                                 markdown_hint=payload.get("markdown_hint"),
                                 warnings=payload.get("warnings", []))

    # ---------- commit mot trang (transaction) ----------

    def _commit_page(self, job_id: str, page_no: int, doc, config_hash: str,
                     blocks: List[OcrBlock], method: str, attempt: int, t0: float,
                     engine_meta: dict, warnings: List[str],
                     set_active: bool = True) -> None:
        nb = normalize_blocks(blocks)
        block_models = []
        issues: List[Dict[str, Any]] = []
        text_blob: List[str] = []
        for i, b in enumerate(nb):
            block_id = f"p{page_no:04d}_b{i + 1:03d}"
            content = b.latex if b.type == "formula" else b.text
            block_models.append({
                "block_id": block_id, "type": b.type, "text": content,
                "order": b.order, "bbox": b.bbox, "confidence": b.confidence,
            })
            bfp = revision_service.block_content_fp(
                {"type": b.type, "text": content, "bbox": b.bbox})
            if content:
                text_blob.append(content)
                if b.type == "formula":
                    bad = latex_basic_check(content)
                    if bad:
                        issues.append({"issue_id": new_id("iss"), "block_id": block_id,
                                       "type": "FORMULA_REVIEW", "content_fp": bfp,
                                       "description": bad})
            if b.type == "skipped_visual":
                issues.append({"issue_id": new_id("iss"), "block_id": block_id,
                               "type": "VISUAL_SKIPPED", "content_fp": bfp,
                               "description": f"Hình minh họa tại trang PDF {page_no} chưa được xử lý"})
        all_text = "\n".join(text_blob)
        page_fp = revision_service.page_content_fp(block_models)
        has_content = any(b["text"] for b in block_models if b["type"] != "skipped_visual")
        if not has_content:
            issues.append({"issue_id": new_id("iss"), "block_id": None,
                           "type": "NO_CONTENT_DETECTED", "content_fp": page_fp,
                           "description": "Trang không phát hiện nội dung chữ; có thể là ảnh không có chữ — cần người kiểm tra, không coi là lỗi cài đặt"})
        for pii in scan_pii(all_text):
            issues.append({"issue_id": new_id("iss"), "block_id": None,
                           "type": f"PII_SUSPECT_{pii['type']}", "content_fp": page_fp,
                           "description": f"Có thể chứa thông tin cá nhân ({pii['type']}); cân nhắc thay bằng {pii['suggestion']}"})
        for w in warnings:
            issues.append({"issue_id": new_id("iss"), "block_id": None,
                           "type": "ENGINE_WARNING", "content_fp": page_fp, "description": w})

        revision_id = new_id("rev")
        kind = "ocr_raw" if set_active else "ocr_reprocess"
        content = {
            "schema_version": "1.0.0",
            "job_id": job_id, "document_id": doc["document_id"], "pdf_page": page_no,
            "printed_page": None, "revision_id": revision_id, "parent_revision": None,
            "kind": kind, "origin": method, "method": method,
            "review_status": "unreviewed",
            "config_hash": config_hash, "engine_meta": engine_meta,
            "coordinate_space": {"unit": "pixel", "width": 0, "height": 0, "origin": "top_left"},
            "blocks": block_models,
            "issues": issues,
            "created_at": _now(),
        }
        if engine_meta.get("coordinate_space"):
            content["coordinate_space"] = engine_meta["coordinate_space"]
        pdir = self.settings.jobs_dir / job_id / "pages" / f"{page_no:04d}"
        rpath = pdir / "revisions" / f"{revision_id}.json"
        content["hash"] = canonical_hash({k: v for k, v in content.items() if k != "hash"})
        errors = validate_page_payload({**content, "_expected_page": page_no})
        if errors:
            self._mark_page_failed(job_id, page_no, "VALIDATION_FAILED", "; ".join(errors))
            return
        atomic_write_text(rpath, json.dumps(content, ensure_ascii=False, indent=1))
        duration = round(time.time() - t0, 2)
        review_status = "unreviewed"
        page_status = "SUCCEEDED" if not any(
            i["type"] in ("VISUAL_SKIPPED", "FORMULA_REVIEW", "NO_CONTENT_DETECTED", "ENGINE_WARNING")
            for i in issues) else "NEEDS_REVIEW"
        stmts = [
            ("INSERT INTO revisions(revision_id, job_id, page_no, parent_revision, kind, origin,"
             " content_path, hash, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
             (revision_id, job_id, page_no, None, kind, method, str(rpath),
              content["hash"], _now())),
        ]
        if set_active:
            stmts.append(
                ("UPDATE page_runs SET status=?, method=?, duration_s=?, active_revision_id=?,"
                 " review_status=?, error=NULL WHERE job_id=? AND page_no=?",
                 (page_status, method, duration, revision_id, review_status, job_id, page_no)))
        else:
            stmts.append(
                ("UPDATE page_runs SET method=?, duration_s=? WHERE job_id=? AND page_no=?",
                 (method, duration, job_id, page_no)))
        self.db.executemany_commit(stmts)
        if set_active:
            from .revision_service import (apply_resolution, recalc_page_status,
                                           sync_issue_rows)
            apply_resolution(self.db, job_id, page_no, issues)
            sync_issue_rows(self.db, job_id, page_no, issues)
            recalc_page_status(self.db, job_id, page_no)
        self._durations.setdefault(job_id, deque(maxlen=8)).append(duration)
        self._log_op(job_id, "committed", page_no, {"method": method, "s": duration})

    def _mark_page_failed(self, job_id: str, page_no: int, code: str, detail: str) -> None:
        self.db.execute("UPDATE page_runs SET status='FAILED', error=? WHERE job_id=? AND page_no=?",
                        (f"{code}: {detail}"[:1500], job_id, page_no))
        self._log_op(job_id, "failed", page_no, {"code": code})

    def _mark_page_interrupted(self, job_id: str, page_no: int) -> None:
        self.db.execute("UPDATE page_runs SET status='INTERRUPTED' WHERE job_id=? AND page_no=?",
                        (job_id, page_no))
        self._log_op(job_id, "interrupted", page_no)

    # ---------- hieu thi ----------

    def ui_state(self, job_id: str) -> Dict[str, Any]:
        job = self._must_job(job_id)
        runs = self.db.list_page_runs(job_id)
        by = {r["page_no"]: r for r in runs}
        with self._mu:
            current = self._current.get(job_id)
            phase = self._model_phase.get(job_id)
            proc_phase = self._phase.get(job_id)
        durations = list(self._durations.get(job_id, []))
        eta = None
        remaining = sum(1 for r in runs if r["status"] in ("PENDING", "INTERRUPTED"))
        if job["status"] == "RUNNING" and remaining and len(durations) >= 2:
            eta = round(sum(durations) / len(durations) * remaining)
        return {"current_page": current, "model_phase": phase, "process_phase": proc_phase,
                "eta_s": eta,
                "counts": {s: sum(1 for r in runs if r["status"] == s)
                           for s in ("PENDING", "RUNNING", "SUCCEEDED", "NEEDS_REVIEW",
                                     "FAILED", "INTERRUPTED")},
                "worker_alive": job_id in self._supervisors and self._supervisors[job_id].alive()}


def _tail_exception() -> str:
    import traceback
    return traceback.format_exc(limit=6)[-1200:]
