from __future__ import annotations

"""MOT luong THAT qua backend + worker process + PaddleOCR-VL tren trang that.

 dung cho OC08 (khong phai unit test; can may da cai model).
 Vi du: python scripts/e2e_real_page.py --input D:/OCR_Local/input/test.pdf --page 6
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--page", type=int, required=True)
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    from backend.app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine="paddle")
    with TestClient(app) as c:
        tok = c.get("/api/session").json()["token"]
        c.headers.update({"x-pdfcleaner-token": tok})
        with open(args.input, "rb") as f:
            r = c.post("/api/documents", files={"file": (Path(args.input).name, f.read(),
                                                         "application/pdf")})
        assert r.status_code == 200, r.text
        doc = r.json()
        print("document:", doc["document_id"], "pages:", doc["page_count"])
        r = c.post("/api/jobs", json={"document_id": doc["document_id"],
                                      "selected_pages": [args.page]})
        job_id = r.json()["job_id"]
        c.post(f"/api/jobs/{job_id}/start")
        t0 = time.time()
        while time.time() - t0 < 1800:
            j = c.get(f"/api/jobs/{job_id}").json()
            print(f"  [{round(time.time() - t0)}s] status={j['status']} "
                  f"model_phase={j['model_phase']} current={j['current_page']}")
            if j["status"] in ("COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"):
                break
            time.sleep(5)
        page = c.get(f"/api/jobs/{job_id}/pages/{args.page}").json()
        print("page status:", page["status"], "method:", page["method"])
        print("blocks:", len(page["blocks"]), "issues:", [i["type"] for i in page["issues"]])
        for b in page["blocks"][:6]:
            print(" ", b["type"], "|", (b["text"] or "")[:70])
        exp = c.post(f"/api/jobs/{job_id}/exports?format=zip").json()
        print("export:", exp.get("export_id"), exp.get("filename"), exp.get("checksum_sha256"))
        dl = c.get(f"/api/exports/{exp['export_id']}/download")
        out = ROOT / "docs" / "e2e_real_export.zip"
        out.write_bytes(dl.content)
        print("da ghi:", out)
        return 0 if page["status"] in ("SUCCEEDED", "NEEDS_REVIEW") else 1


if __name__ == "__main__":
    sys.exit(main())
