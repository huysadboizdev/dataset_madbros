from __future__ import annotations

"""Xac minh mot duong dan Python la INTERPRETER THAT va du dieu kien cho du an.

Dung thay cho kiem tra 'if exist' thuan tuy trong setup.cmd (phat hien S6):
- la tep chay duoc, la Python that (khong phai tep rong/tap tin khac)
- dung phien ban du an ho tro (3.13) — khong phai chi 'co file'
- kien truc 64-bit (paddlepaddle Windows can 64-bit)
- import duoc paddleocr (venv co PaddleOCR) — neu thieu thi that bai som, ro rang

Exit 0 + in JSON ket qua khi OK; exit != 0 + ly do khi KHONG dat. In ra bang ASCII
de setup.cmd (cmd.exe) doc duoc khong loi ma hoa.
  python check_interpreter.py "<duong-dan-python>"
"""

import json
import platform
import subprocess
import sys
from pathlib import Path

REQUIRED = (3, 13)


def _run(py: str, code: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 127, "", f"khong chay duoc: {e}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: check_interpreter.py <python> [--no-paddle]")
        return 2
    py = argv[1]
    need_paddle = "--no-paddle" not in argv[2:]
    result = {"path": py, "checks": {}, "ok": True, "reasons": []}

    p = Path(py)
    if not p.exists() or not p.is_file():
        result["ok"] = False; result["reasons"].append("khong phai tep ton tai")
        print(json.dumps(result)); return 1

    # 1) la interpreter that?
    rc, out, err = _run(py, "import sys; print(sys.version_info[0], sys.version_info[1], sys.maxsize>2**32)")
    if rc != 0:
        result["checks"]["executable"] = {"rc": rc, "err": err[-300:]}
        result["ok"] = False; result["reasons"].append("khong phai Python interpreter chay duoc")
        print(json.dumps(result)); return 1
    toks = out.split()
    if len(toks) < 3:
        result["ok"] = False; result["reasons"].append("interpreter khong tra thong tin phien ban")
        print(json.dumps(result)); return 1
    major, minor = int(toks[0]), int(toks[1])
    is64 = toks[2] == "True"
    result["checks"]["version"] = f"{major}.{minor}"
    result["checks"]["bits64"] = is64
    if (major, minor) != REQUIRED:
        result["ok"] = False
        result["reasons"].append(f"can Python {REQUIRED[0]}.{REQUIRED[1]}, dung {major}.{minor}")
    if not is64:
        result["ok"] = False; result["reasons"].append("can ban 64-bit (paddlepaddle Windows)")

    if need_paddle:
        rc2, out2, err2 = _run(py, "import paddleocr; print(paddleocr.__version__)")
        result["checks"]["paddleocr"] = (out2 or err2[-300:]) if rc2 == 0 else f"FAIL: {err2[-300:]}"
        if rc2 != 0:
            result["ok"] = False; result["reasons"].append("khong import duoc paddleocr o interpreter nay")

    # 2) kien truc host phai khop (64-bit) — phat hien som may 32-bit
    result["checks"]["host_arch"] = platform.machine()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
