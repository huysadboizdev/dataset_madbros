from __future__ import annotations

"""Van hanh Windows THAT: hard-kill server mid-job -> mo lai -> reconcile -> resume.

Bang chung worker chi dispatch dung trang con lai, khong tu chay them, khong mat
trang da luu. Dung fake engine (test co nhan) + data dir tach rieng.
  python scripts/test_ops_hardkill.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8901
BASE = f"http://127.0.0.1:{PORT}"
DATA = ROOT / "data" / "_ops_hardkill"


def req(path, data=None, token=None, method=None, timeout=15):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["x-pdfcleaner-token"] = token
    r = urllib.request.Request(BASE + path, data=data, headers=headers,
                               method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def start_server():
    env = {**os.environ, "PDFCLEANER_E2E": "1", "PDFCLEANER_PORT": str(PORT),
           "PDFCLEANER_E2E_DATA": str(DATA), "PDFCLEANER_E2E_DELAY": "1.5",
           "PYTHONIOENCODING": "utf-8"}
    log = open(DATA / "server.log", "ab")
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "run_e2e_server.py")],
        cwd=str(ROOT), env=env, stdout=log, stderr=log,
    )
    for _ in range(90):
        time.sleep(1)
        try:
            h = req("/api/health")
            if h.get("app") == "ok":
                return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("server chet ngay khi khoi dong; xem server.log")
    raise RuntimeError("server khong health kip")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import shutil
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)

    proc = start_server()
    token = req("/api/session")["token"]
    fixture = ROOT / "frontend" / "tests" / "fixtures" / "book.pdf"
    if not fixture.exists():
        subprocess.run([sys.executable, str(ROOT / "backend/app/tests/fixtures/make_pdf_gen_cli.py"),
                        str(fixture)], check=True, cwd=str(ROOT))
    # upload multipart
    import io
    import uuid
    b = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"bk.pdf\"\r\n"
               "Content-Type: application/pdf\r\n\r\n".encode())
    body.write(fixture.read_bytes())
    body.write(f"\r\n--{b}--\r\n".encode())
    r = urllib.request.Request(BASE + "/api/documents", data=body.getvalue(), method="POST",
                               headers={"Content-Type": "multipart/form-data; boundary=" + b,
                                        "x-pdfcleaner-token": token})
    doc = json.loads(urllib.request.urlopen(r, timeout=60).read())
    did = doc["document_id"]
    job = req("/api/jobs", json.dumps({"document_id": did,
                                       "selected_pages": [5, 6, 7]}).encode(), token)
    jid = job["job_id"]
    req(f"/api/jobs/{jid}/start", b"{}", token, "POST")

    # cho trang 5 committed
    for _ in range(60):
        st = req(f"/api/jobs/{jid}")
        done5 = [p for p in st["pages"] if p["page_no"] == 5][0]["status"]
        if done5 in ("SUCCEEDED", "NEEDS_REVIEW"):
            break
        time.sleep(1)
    assert done5 in ("SUCCEEDED", "NEEDS_REVIEW"), "trang 5 chua xong de kill"
    # HARD KILL: taskkill /T /F ca cay (khong shutdown sach) — mo phong mat nguon
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print("da hard-kill server PID", proc.pid)

    proc2 = start_server()
    try:
        st = req(f"/api/jobs/{jid}")
        assert st["status"] == "INTERRUPTED", f"mong INTERRUPTED, duoc {st['status']}"
        p5 = [p for p in st["pages"] if p["page_no"] == 5][0]
        assert p5["status"] in ("SUCCEEDED", "NEEDS_REVIEW"), "trang da luu bi mat!"
        page5 = req(f"/api/jobs/{jid}/pages/5")
        assert page5["blocks"], "trang 5 mat noi dung sau restart"
        print("reconcile OK: job INTERRUPTED, trang 5 con nguyen noi dung")
        token = req("/api/session")["token"]
        dlog = Path(req("/api/session") and "")  # not used
        # engine log cu: so lan goi trang 5 truoc kill
        eng_log = DATA / "engine_dispatch.log"
        def calls5():
            return sum(1 for l in eng_log.read_text(encoding="utf-8").splitlines()
                       if json.loads(l)["page_no"] == 5)
        n5_before = calls5()
        req(f"/api/jobs/{jid}/resume", b"{}", token, "POST")
        for _ in range(90):
            st = req(f"/api/jobs/{jid}")
            if st["status"] in ("COMPLETED", "COMPLETED_WITH_ERRORS"):
                break
            time.sleep(1)
        assert st["status"] == "COMPLETED", st["status"]
        assert calls5() == n5_before, "resume da OCR LAI trang 5 da xong"
        called = sorted({json.loads(l)["page_no"]
                         for l in eng_log.read_text(encoding="utf-8").splitlines()})
        assert called == [5, 6, 7], f"engine goi {called}, mong chi [5,6,7]"
        print("resume OK: chi chay dung trang con lai 6,7; khong cham ngoai [5,6,7]")
        # khong con file .part/.tmp roi rac ngoai pham vi
        leftovers = [p for p in DATA.rglob("*.part")] + [p for p in DATA.rglob("*.tmp*")]
        assert not leftovers, f"san pham tam con sot: {leftovers}"
        print("don dep tmp: OK")
    finally:
        try:
            req("/api/admin/shutdown", b"{}", token, "POST")
            proc2.wait(timeout=20)
        except Exception:
            subprocess.run(["taskkill", "/PID", str(proc2.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("OPS TEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
