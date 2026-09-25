from __future__ import annotations

"""Phat hien 3 + 6: cong thuc that di qua toan bo duong dan sua -> revision ->
export -> MO LAI goi xuat. Chay bang fake engine (co nhan); OCR that o
scripts/verify_formula_ocr.py. Khong thay bang chung OCR that bang mock.

- JSON escaping: '\' va $ trong LaTeX phai round-trip qua content.json khong bi
  bien dang (mo lai ZIP, json.loads, doi chieu tung ky tu).
- Markdown/KaTeX: block formula xuat ra '$$...$$'; cong thuc noi dong giu '$...$'.
- Resolve issue: sau khi sua dung, FORMULA_REVIEW khong con mo; lich su giu nguyen.
"""

import io
import json
import zipfile

from ..conftest import start_job, upload, wait_status

REAL_LATEX = r"\frac{2x-1}{x+3} \geq 5"          # co \ va $ (sau delimiter)
INLINE_TXT = "Xét \\(\\sqrt{a^{2}+b^{2}}\\) với a, b nguyên."  # \(..\)->$..$ khi lam sach


def _seed_broken_formula(client, page_no=6):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [page_no])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/{page_no}").json()
    # them block formula SAI (unbalanced) + block inline chua \(..\), luu revision
    blocks = list(page["blocks"])
    blocks.append({"block_id": "p0006_b900", "type": "formula",
                   "text": "\\frac{2x-1}{x+3", "order": len(blocks),
                   "bbox": None, "confidence": None})
    blocks.append({"block_id": "p0006_b901", "type": "paragraph",
                   "text": INLINE_TXT, "order": len(blocks) + 1,
                   "bbox": None, "confidence": None})
    r = client.patch(f"/api/jobs/{job_id}/pages/{page_no}",
                     json={"base_revision_id": page["revision_id"], "blocks": blocks})
    assert r.status_code == 200, r.text
    return job_id, r.json()["page"]


def _open_zip(client, job_id):
    exp = client.post(f"/api/jobs/{job_id}/exports?format=zip").json()
    body = client.get(f"/api/exports/{exp['export_id']}/download").content
    return exp, zipfile.ZipFile(io.BytesIO(body))


def test_edit_formula_then_export_reopen_preserves_latex(client):
    job_id, _page = _seed_broken_formula(client)
    current = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # van con issue FORMULA_REVIEW mo vi block hong
    assert any(i["type"] == "FORMULA_REVIEW" and i["status"] == "open"
               for i in current["issues"])
    # SUA block hong thanh LaTeX dung + inline $
    for b in current["blocks"]:
        if b["block_id"] == "p0006_b900":
            b["text"] = REAL_LATEX
    rr = client.patch(f"/api/jobs/{job_id}/pages/6",
                      json={"base_revision_id": current["revision_id"],
                            "blocks": current["blocks"]})
    assert rr.status_code == 200, rr.text

    # MO LAI ZIP va doi chieu LaTeX round-trip NGUYEN VEN trong content.json
    _, zf = _open_zip(client, job_id)
    pub = json.loads(zf.read("content.json").decode("utf-8"))
    pages = {p["pdf_page"]: p for p in pub["pages"]}
    formula_blocks = [b for b in pages[6]["blocks"] if b["type"] == "formula"]
    assert any(b["text"] == REAL_LATEX for b in formula_blocks), \
        "LaTeX phai tra nguyen trong JSON (escape \\\\ khong bi mat)"
    md = zf.read("content.md").decode("utf-8")
    assert f"$$\n{REAL_LATEX}\n$$" in md           # block formula -> $$
    assert "$\\sqrt{a^{2}+b^{2}}$" in md            # inline giu sau lam sach \(..\)
    # sau khi dung, issue da sua bien mat (khong con mo)
    after = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert not any(i["type"] == "FORMULA_REVIEW" and i["status"] == "open"
                   for i in after["issues"])
    assert after["status"] == "SUCCEEDED"


def test_reopened_revision_keeps_history_and_engine_identity(client):
    """Revision da luu van doc lai duoc sau 'mo tai', mang dung ban dang dung."""
    job_id, _page = _seed_broken_formula(client)
    revs = client.get(f"/api/jobs/{job_id}/pages/6/revisions").json()["items"]
    current = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert len(revs) >= 2  # ocr_raw + edited
    ids = {r["revision_id"] for r in revs}
    assert current["revision_id"] in ids
    _, zf = _open_zip(client, job_id)
    man = json.loads(zf.read("manifest.json"))
    # manifest tro DUNG revision dang hoat dong, khong phai ban ocr_raw cu
    assert man["revision_map"]["6"] == current["revision_id"]
    assert man["method_by_page"]["6"] in ("ocr", "cached", "direct")
    assert "checksums_sha256" in man and "manifest.json" not in man["checksums_sha256"]
    pub = json.loads(zf.read("content.json"))
    assert {p["pdf_page"]: p["revision_id"] for p in pub["pages"]} == \
        {6: current["revision_id"]}


def test_inline_math_delimiters_normalized_before_export(client):
    from backend.app.cleaning.normalize import normalize_text
    out = normalize_text("Hàm \\(x^2\\) và \\[\\frac{a}{b}\\]")
    assert "$x^2$" in out        # noi dong
    assert "$$" in out           # block display
