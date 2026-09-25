from __future__ import annotations

"""Smoke test HTTP THAT toi instance production dang chay (khong phai TestClient).

Du dung: python docs/_smoke_http.py  (Open_Tool phai dang mo)
"""

import io
import json
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8765"
SRC = r"D:\OCR_Local\input\test.pdf"


def main() -> int:
    tok = json.loads(urllib.request.urlopen(BASE + "/api/session").read())["token"]
    try:
        req = urllib.request.Request(BASE + "/api/jobs", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)
        print("BUG: mutation khong token van chay")
        return 1
    except urllib.error.HTTPError as e:
        print("thieu token ->", e.code, "(mong doi 401)")
        assert e.code == 401
    h = json.loads(urllib.request.urlopen(BASE + "/api/health").read())
    print("health engine_mode:", h["engine_mode"], "(production phai la paddle, khong fake)")
    assert h["engine_mode"] == "paddle"

    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(("--" + boundary + "\r\n"
                'Content-Disposition: form-data; name="file"; filename="test.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n").encode())
    with open(SRC, "rb") as f:
        body.write(f.read())
    body.write(("\r\n--" + boundary + "--\r\n").encode())
    req = urllib.request.Request(
        BASE + "/api/documents", data=body.getvalue(), method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "x-pdfcleaner-token": tok})
    r = json.loads(urllib.request.urlopen(req, timeout=180).read())
    print("upload:", r["document_id"], "pages:", r["page_count"], "dup:", r["duplicate"])
    assert r["page_count"] == 138
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
