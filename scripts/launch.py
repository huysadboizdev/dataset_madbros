from __future__ import annotations

"""Launcher PDF Cleaner Tool (Windows).

Mo backend (neu chua chay) + trinh duyet. KHONG mo instance thu hai.
"""

import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.settings import load_settings  # noqa: E402


def health(port: int, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main() -> int:
    settings = load_settings(ROOT / "config.json")
    url = f"http://{settings.host}:{settings.port}"
    h = health(settings.port)
    if h and h.get("app") == "ok":
        print(f"Ung dung dang chay san — mo trinh duyet: {url}")
        webbrowser.open(url)
        return 0
    if h is None:
        # kiem tra port chiem boi chuong khac
        import socket
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", settings.port)) == 0:
                print(f"! Port {settings.port} dang bi chuong trinh KHAC chiem."
                      " Sua 'port' trong config.json roi chay lai.")
                return 1
    print("Dang khoi dong backend (lan dau co the cham hon)…")
    log = settings.data_dir / "server.out.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log, "ab")
    creationflags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app",
         "--host", settings.host, "--port", str(settings.port), "--log-level", "warning"],
        cwd=str(ROOT), stdout=logf, stderr=logf, creationflags=creationflags,
    )
    (settings.data_dir / "server.json").write_text(json.dumps(
        {"pid": proc.pid, "port": settings.port, "started": time.time()}), encoding="utf-8")
    for _ in range(60):
        time.sleep(1)
        h = health(settings.port, timeout=2)
        if h and h.get("app") == "ok":
            break
    else:
        print(f"! Backend khong khoi dong duoc. Xem log: {log}")
        return 1
    print(f"San sang: {url}")
    webbrowser.open(url)
    print("Giu cua so nay mo ho dong la thu cong. Dong ung dung: Stop_Tool.cmd")
    return 0


if __name__ == "__main__":
    sys.exit(main())
