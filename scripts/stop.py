from __future__ import annotations

"""Dung DUNG tien trình cua PDF Cleaner Tool (backend + worker cua no).

Khong bao gio taskkill moi python.exe.
"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.settings import load_settings  # noqa: E402


def cmdline_of(pid: int) -> str:
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            text=True, timeout=10, stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:
        return ""


def pid_alive(pid: int) -> bool:
    return bool(cmdline_of(pid))


def kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    settings = load_settings(ROOT / "config.json")
    data = settings.data_dir

    # 1) goi shutdown cua chinh app (token session)
    try:
        base = f"http://127.0.0.1:{settings.port}"
        with urllib.request.urlopen(base + "/api/session", timeout=3) as r:
            token = json.loads(r.read().decode("utf-8"))["token"]
        req = urllib.request.Request(base + "/api/admin/shutdown", method="POST",
                                     data=b"{}", headers={"x-pdfcleaner-token": token})
        urllib.request.urlopen(req, timeout=5)
        print("Da gui lenh dong ung dung.")
    except Exception:
        pass

    # 2) doi backend ket thuc; neu con va DUNG danh tinh thi moi kill
    sj = data / "server.json"
    if sj.exists():
        try:
            info = json.loads(sj.read_text(encoding="utf-8"))
            pid = int(info.get("pid", -1))
            for _ in range(15):
                time.sleep(1)
                if not pid_alive(pid):
                    break
            else:
                cl = cmdline_of(pid)
                if "backend.app.main" in cl or "uvicorn" in cl:
                    print(f"Backend van song, kill PID {pid} (da kiem tra danh tinh).")
                    kill_pid(pid)
                elif cl:
                    print(f"! PID {pid} khong phai backend cua tool — KHONG kill.")
        except Exception as e:
            print("server.json:", e)
        sj.unlink(missing_ok=True)

    # 3) worker con soc
    wp = data / "worker_pids.txt"
    if wp.exists():
        for line in wp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                pid = int(line)
            except ValueError:
                continue
            cl = cmdline_of(pid)
            if "backend.app.worker.process" in cl:
                print(f"Kill worker soc PID {pid}.")
                kill_pid(pid)
        wp.unlink(missing_ok=True)
    print("Xong. Du lieu va ket qua trang da luu van nguyen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
