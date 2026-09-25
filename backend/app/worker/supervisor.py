from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..settings import Settings
from . import protocol


class WorkerDead(Exception):
    pass


class WorkerSupervisor:
    """Sở hữu lịch sử xử lý. Parent sinh worker, gửi từng trang đã chốt,
    đọc sự kiện, và là nơi duy nhất ghi DB/artifact."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.engine_meta: Dict[str, Any] = {}
        self.load_seconds: Optional[float] = None
        self.last_output: List[str] = []
        self._stop_reader = threading.Event()

    def spec_args(self, engine: str, extra: Optional[List[str]] = None,
                  identity_file: Optional[Path] = None) -> List[str]:
        args = [sys.executable, "-u", "-m", "backend.app.worker.process", "--engine", engine]
        o = self.settings.ocr
        if engine == "paddle":
            args += ["--pipeline-version", o.pipeline_version,
                     "--layout-model", o.layout_model_name,
                     "--vl-model", o.vl_rec_model_name,
                     "--device", o.device, "--dpi", str(o.render_dpi)]
            if identity_file:
                args += ["--pinned-identity-file", str(identity_file)]
        elif engine == "fake":
            # F2: engine fake cung nhan ten model + identity pin de kiem CUNG hop dong
            # danh tinh nhu engine that (test tich hop khong the bo qua duong nay).
            args += ["--layout-model", o.layout_model_name, "--vl-model", o.vl_rec_model_name]
            if identity_file:
                args += ["--pinned-identity-file", str(identity_file)]
        if extra:
            args += extra
        return args

    def repo_root(self) -> Path:
        # backend/app/worker/supervisor.py -> project root
        return Path(__file__).resolve().parents[3]

    def _pid_file(self) -> Path:
        return self.settings.data_dir / "worker_pids.txt"

    def _record_pid(self, pid: int) -> None:
        try:
            self._pid_file().parent.mkdir(parents=True, exist_ok=True)
            with open(self._pid_file(), "a", encoding="utf-8") as f:
                f.write(f"{pid}\n")
        except OSError:
            pass

    def _remove_pid(self, pid: int) -> None:
        try:
            pf = self._pid_file()
            if not pf.exists():
                return
            lines = [l for l in pf.read_text(encoding="utf-8").splitlines()
                     if l.strip() and int(l) != pid]
            pf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        except OSError:
            pass

    def start(self, engine: str = "paddle", extra_args: Optional[List[str]] = None,
              identity_file: Optional[Path] = None) -> None:
        with self._lock:
            if self._proc is not None:
                raise RuntimeError("Worker đã chạy; mỗi job chỉ một worker, một trang inference")
            args = self.spec_args(engine, extra_args, identity_file=identity_file)
            env_extra = {"PYTHONIOENCODING": "utf-8"}
            import os
            env = {**os.environ, **env_extra}
            self._proc = subprocess.Popen(
                args, cwd=str(self.repo_root()),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
            )
            self._record_pid(self._proc.pid)
            self._stop_reader.clear()
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self.last_output.append(line.rstrip()[:500])
            self.last_output = self.last_output[-50:]
            msg = protocol.decode(line)
            if msg:
                if msg.get("evt") == "model_ready":
                    self.engine_meta = msg.get("meta", {})
                    self.load_seconds = msg.get("load_s")
                self.events.put(msg)
        self.events.put({"evt": "worker_exit", "returncode": proc.wait()})
        self._stop_reader.set()

    def _drain_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for line in proc.stderr:
            # log kỹ thuật, KHÔNG ghi nội dung tài liệu
            self.last_output.append("[stderr] " + line.rstrip()[:300])
            self.last_output = self.last_output[-80:]

    def send(self, obj: Dict[str, Any]) -> None:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                raise WorkerDead("Worker không còn sống")
            assert proc.stdin is not None
            proc.stdin.write(protocol.encode(obj) + "\n")
            proc.stdin.flush()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def wait_event(self, predicate, timeout: float):
        """Chờ event thỏa predicate; các event khác được đưa lại queue."""
        deadline = time.time() + timeout
        held: List[Dict[str, Any]] = []
        got = None
        while time.time() < deadline:
            try:
                evt = self.events.get(timeout=0.5)
            except queue.Empty:
                if not self.alive():
                    break
                continue
            if got is None and predicate(evt):
                got = evt
            else:
                held.append(evt)
            if got is not None:
                break
        if not self.alive() and got is None:
            raise WorkerDead("Worker đã thoát")
        for evt in held:
            self.events.put(evt)
        return got

    def terminate(self, grace_s: float = 3.0) -> None:
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            pid = proc.pid
            try:
                if proc.poll() is None and proc.stdin is not None:
                    proc.stdin.write(protocol.encode({"cmd": "shutdown"}) + "\n")
                    proc.stdin.flush()
            except Exception:
                pass
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._remove_pid(pid)
        with self._lock:
            self._proc = None
