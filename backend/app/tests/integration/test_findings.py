from __future__ import annotations

"""Test cho cac phat hien: checksum ZIP doi chieu byte thuc, PII trong
ten file/metadata, cache vo hieu hoa khi model doi, resolve issue + validator chay lai."""

import hashlib
import io
import json
import zipfile

from ..conftest import job_ops, start_job, upload, wait_status


# ---------- Phat hien 1: checksum manifest khong con tu doi chieu gia tri cu ----------

def _export_zip(client, job_id):
    exp = client.post(f"/api/jobs/{job_id}/exports?format=zip").json()
    body = client.get(f"/api/exports/{exp['export_id']}/download").content
    return exp, zipfile.ZipFile(io.BytesIO(body))


def test_manifest_checksums_match_actual_bytes(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [5, 6])
    wait_status(client, job_id, ("COMPLETED",))
    exp, zf = _export_zip(client, job_id)
    man = json.loads(zf.read("manifest.json"))
    # khong co self-checksum trong chinh manifest
    assert "checksums_sha256" in man
    assert "manifest.json" not in man["checksums_sha256"], "manifest khong duoc tu hash chinh no"
    # doi chieu MỌI checksum khai bao voi SHA-256 cua BYTE THAT trong ZIP
    for name, declared in man["checksums_sha256"].items():
        real = hashlib.sha256(zf.read(name)).hexdigest()
        assert real == declared, f"{name}: khai bao {declared} != thuc {real}"
    # checksum ZIP tinh SAU khi hoan tat, luu NGOAI zip (DB/API), khong phai trong manifest
    assert "zip_sha256" not in man  # ZIP khong tu chua hash cua chinh no
    assert exp["checksum_sha256"] and len(exp["checksum_sha256"]) == 64


# ---------- Phat hien 4: PII trong ten file / metadata khong thoat ra goi xuat ----------

def test_pii_filename_not_leaked_into_markdown(client):
    from ..conftest import make_pdf
    data = make_pdf(client.settings.project_root)
    r = client.post("/api/documents", files={
        "file": ("nguyen-van-a-0912345678-email.pdf", data, "application/pdf")})
    did = r.json()["document_id"]
    job_id = start_job(client, did, [6])
    wait_status(client, job_id, ("COMPLETED",))
    md = client.post(f"/api/jobs/{job_id}/exports?format=md")
    body = client.get(f"/api/exports/{md.json()['export_id']}/download").content.decode("utf-8")
    assert "0912345678" not in body  # so dien thoai trong ten file khong vao Markdown
    assert "nguyen-van-a-0912345678-email" not in body
    # KIEM CA GOI ZIP: content.md/manifest.json/issues.json khong leak ten goc
    exp, zf = _export_zip(client, job_id)
    blob = "\n".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    assert "0912345678" not in blob
    assert "nguyen-van-a-0912345678-email" not in blob
    # ten tap tin ZIP ra de dang la opaque, khong chua ten goc
    assert "nguyen-van-a" not in exp["filename"] and exp["filename"].startswith("document_")



def test_optional_metadata_and_pii_redaction(client):
    doc = upload(client)
    did = doc["document_id"]
    r = client.patch(f"/api/documents/{did}/metadata",
                     json={"subject": "Toán", "grade": "10", "series": "Kết nối"})
    assert r.status_code == 200
    assert r.json()["metadata"]["subject"] == "Toán"
    job_id = start_job(client, did, [6])
    wait_status(client, job_id, ("COMPLETED",))
    exp, zf = _export_zip(client, job_id)
    man = json.loads(zf.read("manifest.json"))
    assert man["document"]["user_metadata"]["subject"] == "Toán"
    # metadata chua PII bi redact khi xuat, khong im lang
    client.patch(f"/api/documents/{did}/metadata", json={"notes": "liên hệ a@b.com"})
    exp2, zf2 = _export_zip(client, job_id)
    man2 = json.loads(zf2.read("manifest.json"))
    assert man2["document"]["user_metadata"].get("notes") != "liên hệ a@b.com"
    issues = json.loads(zf2.read("issues.json"))["issues"]
    assert any(i["type"] == "PII_REDACTED_METADATA" for i in issues)


def test_nested_metadata_path_pii_never_in_exported_zip(client):
    """S3: ngay ca khi metadata co email/dien thoai, ZIP ra khong duoc con PII;
    va khong mot file nao trong ZIP lo duong dan tuyet doi cua may chay thu nghiem."""
    doc = upload(client)
    did = doc["document_id"]
    client.patch(f"/api/documents/{did}/metadata",
                 json={"subject": "Toán", "notes": "gọi 0987654321 hoặc mail t@x.edu.vn"})
    job_id = start_job(client, did, [6])
    wait_status(client, job_id, ("COMPLETED",))
    exp, zf = _export_zip(client, job_id)
    all_text = "\n".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    # nhung gia tri nhay da cai vao fixture KHONG con trong bat ky file xuat nao
    assert "0987654321" not in all_text
    assert "t@x.edu.vn" not in all_text
    # khong lo duong dan tuyet doi cua may chay thu nghiem
    import os
    assert os.sep + "Users" not in all_text or "\\Users" not in all_text
    root = str(client.settings.project_root)
    if len(root) > 3:
        assert root not in all_text and root.replace("\\", "\\\\") not in all_text
    # checksum van tinh sau sanitize va van khop byte thuc
    man = json.loads(zf.read("manifest.json"))
    for name, declared in man["checksums_sha256"].items():
        assert hashlib.sha256(zf.read(name)).hexdigest() == declared, name


# ---------- Phat hien 5 + 4: danh tinh model tren dia, cache vo hieu hoa, khong
# lo duong dan ra ZIP. Test doi ARTIFACT model that (conftest _isolate_model_root
# chi PDFCLEANER_MODEL_ROOT toi thu muc gia lap), KHONG sua model_identity.json. ----------

def test_config_or_model_change_invalidates_cache(tmp_path, monkeypatch):
    """Doi noi dung weights (CUNG kich thuoc) hoac config -> danh tinh doi ->
    cache cu khong dugc dung; job moi OCR lai dung trang da chon."""
    from fastapi.testclient import TestClient
    from ..conftest import build_fake_model_root, make_app
    root = tmp_path / "models"
    build_fake_model_root(root, tag_seed="A")
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))

    def new_client(logname):
        dlog = tmp_path / logname
        app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog)])
        c = TestClient(app); c.__enter__()
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        c.dispatch_log_path = dlog; c.settings = settings
        return c

    c1 = new_client("e1.log")
    doc = upload(c1)
    did = doc["document_id"]
    from backend.app.ocr import model_identity as mi
    tag_before = mi.identity_hash(["PP-DocLayoutV3", "PaddleOCR-VL-1.6"], root, full=True)
    j1 = start_job(c1, did, [6]); wait_status(c1, j1, ("COMPLETED",))
    assert c1.get(f"/api/jobs/{j1}/pages/6").json()["method"] == "ocr"
    # cung model -> job 2 dung cache
    j2 = start_job(c1, did, [6]); wait_status(c1, j2, ("COMPLETED",))
    assert c1.get(f"/api/jobs/{j2}/pages/6").json()["method"] == "cached"
    # cache file gan voi tag_before (FULL identity, nhu cache path) ton tai
    cachedir = c1.settings.data_dir / "cache" / "ocr" / doc["sha256"]
    assert any(tag_before in p.name for p in cachedir.glob("*.json"))
    c1.__exit__(None, None, None)

    # DOI NOI DUNG WEIGHTS NHUNG GIU KICH THUOC GIONG NGUYEN (khong chi doi ten/size)
    w = root / "PaddleOCR-VL-1.6" / "model.safetensors"
    same_len = w.stat().st_size
    w.write_bytes(b"B" * same_len)  # noi dung khac hoan toan, CUNG kich thuoc
    tag_after = mi.identity_hash(["PP-DocLayoutV3", "PaddleOCR-VL-1.6"], root, full=True)
    assert tag_after != tag_before, "doi noi dung weights cung size phai doi danh tinh"
    c2 = new_client("e2.log")
    j3 = start_job(c2, did, [6]); wait_status(c2, j3, ("COMPLETED",))
    j3m = c2.get(f"/api/jobs/{j3}/pages/6").json()
    assert j3m["method"] == "ocr", "doi noi dung weights phai vo hieu hoa cache"
    ops = [o["op"] for o in job_ops(c2, j3) if o["page_no"] == 6]
    assert "cache_hit" not in ops and "render" in ops
    # cache moi gan tag moi, cache model cu cho trang nay KHONG con
    assert any(tag_after in p.name for p in cachedir.glob("*.json"))
    assert not any(tag_before in p.name for p in cachedir.glob("*.json")), \
        "cache khong tuong thich (model cu) phai bi vo hieu hoa/xoa"
    c2.__exit__(None, None, None)


def test_model_config_content_change_detected(tmp_path, monkeypatch):
    """Doi config.json cung du phat hien (khong chi weights)."""
    from fastapi.testclient import TestClient
    from ..conftest import build_fake_model_root, make_app
    from backend.app.ocr import model_identity as mi
    root = tmp_path / "models2"
    build_fake_model_root(root, tag_seed="A")
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))
    t1 = mi.identity_hash(["PP-DocLayoutV3", "PaddleOCR-VL-1.6"], root)
    (root / "PP-DocLayoutV3" / "inference.yml").write_text("seed: CHANGED\n", encoding="utf-8")
    t2 = mi.identity_hash(["PP-DocLayoutV3", "PaddleOCR-VL-1.6"], root)
    assert t1 != t2, "doi config phai doi danh tinh"
    # thu muc model bi xoa -> unresolved -> cache cam dung
    import shutil; shutil.rmtree(root)
    assert mi.identity_hash(["PP-DocLayoutV3", "PaddleOCR-VL-1.6"], root) != t1


def test_export_manifest_records_engine_identity_no_paths(tmp_path, monkeypatch):
    """ZIP xuat: engine_meta co identity model + hash, VA khong lo duong dan tuyet doi."""
    from fastapi.testclient import TestClient
    from ..conftest import build_fake_model_root, make_app
    from backend.app.cleaning.export_sanitize import has_private_leak
    root = tmp_path / "mroot"
    build_fake_model_root(root)
    monkeypatch.setenv("PDFCLEANER_MODEL_ROOT", str(root))
    dlog = tmp_path / "d.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog)])
    with TestClient(app) as c:
        c.headers.update({"x-pdfcleaner-token": c.get("/api/session").json()["token"]})
        c.dispatch_log_path = dlog; c.settings = settings
        doc = upload(c)
        job_id = start_job(c, doc["document_id"], [6]); wait_status(c, job_id, ("COMPLETED",))
        em = c.get(f"/api/jobs/{job_id}/pages/6").json()["engine_meta"]
        assert em.get("disk_identity"), "engine_meta phai co chu ky model"
        assert em.get("model_root_present") is True
        exp = c.post(f"/api/jobs/{job_id}/exports?format=zip").json()
        zf = zipfile.ZipFile(io.BytesIO(c.get(f"/api/exports/{exp['export_id']}/download").content))
        man = json.loads(zf.read("manifest.json"))
        # khong mot chuoi nao trong manifest la duong dan tuyet doi / chua Users
        blob = json.dumps(man)
        assert "\\Users" not in blob and str(tmp_path).replace("\\", "\\\\") not in blob
        assert man["engine_meta"].get("disk_identity") == em["disk_identity"]


# ---------- Phat hien 6: resolve issue + validator chay lai khi sua ----------

def test_resolve_issue_and_revalidate(client):
    doc = upload(client)
    # buoc trang 6 co cong thuc sai (unbalanced) de sinh FORMULA_REVIEW
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # chen block formula hong
    page["blocks"].append({"block_id": f"p0006_b999", "type": "formula",
                           "text": "\\frac{a}{b", "order": 9, "bbox": None,
                           "confidence": None})
    r = client.patch(f"/api/jobs/{job_id}/pages/6",
                     json={"base_revision_id": page["revision_id"], "blocks": page["blocks"]})
    assert r.status_code == 200
    fresh = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert any(i["type"] == "FORMULA_REVIEW" for i in fresh["issues"])
    assert fresh["status"] == "NEEDS_REVIEW"
    formula_issues = [i for i in fresh["issues"] if i["type"] == "FORMULA_REVIEW"]
    assert len(fresh["open_issues"]) == len(formula_issues)
    # resolve issue da kiem tra
    iid = formula_issues[0]["issue_id"]
    rr = client.post(f"/api/jobs/{job_id}/pages/6/issues/{iid}/resolve",
                     json={"reason": "Da doi chieu truc tiep voi sach, LaTeX dung trong bo dem"})
    assert rr.status_code == 200
    after = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # van de khong con mo -> trang khong can review nua
    assert after["open_issues"] == []
    assert after["status"] == "SUCCEEDED"
    resolved = [i for i in after["issues"] if i["issue_id"] == iid]
    assert resolved and resolved[0]["status"] == "resolved"
    assert "doi chieu" in resolved[0]["resolved_reason"]
    assert resolved[0]["checked_revision"]  # luu revision da kiem
    # resolve lai -> loi khong tu dong dong duoc lan 2
    assert client.post(f"/api/jobs/{job_id}/pages/6/issues/{iid}/resolve",
                       json={"reason": "dup"}).status_code == 422


def test_fixed_formula_issue_disappears_on_edit(client):
    """Sua dung cong thuc -> FORMULA_REVIEW bien mat (validator chay lai), khong giu loi cu."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    page["blocks"].append({"block_id": "p0006_b998", "type": "formula",
                           "text": "\\frac{a}{b", "order": 9, "bbox": None, "confidence": None})
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": page["revision_id"], "blocks": page["blocks"]})
    bad = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # sua LaTeX dung
    for b in bad["blocks"]:
        if b["block_id"] == "p0006_b998":
            b["text"] = "\\frac{a}{b}"
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": bad["revision_id"], "blocks": bad["blocks"]})
    good = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert not any(i["type"] == "FORMULA_REVIEW" and i["status"] == "open" for i in good["issues"])
    assert good["status"] == "SUCCEEDED"


# ---------- Phat hien 5: xuat tron trang manifest phai ghi model THAT, khong
# bi lop chu truc tiep (pdf_text_layer) cua trang cuoi ghi de. ----------

def test_mixed_export_manifest_records_real_model(client):
    doc = upload(client)
    # trang 20 = lop chu PDF truc tiep; trang 6 = OCR (engine that trong test = fake_recording)
    job_id = start_job(client, doc["document_id"], [20, 6])
    wait_status(client, job_id, ("COMPLETED",))
    by = {p["page_no"]: p for p in client.get(f"/api/jobs/{job_id}").json()["pages"]}
    assert by[20]["method"] == "direct" and by[6]["method"] in ("ocr", "cached")
    exp, zf = _export_zip(client, job_id)
    man = json.loads(zf.read("manifest.json"))
    em = man["engine_meta"]
    # khong duoc de 'pdf_text_layer' (khong phai model) choan choan manifest khi co trang OCR
    assert em.get("engine") != "pdf_text_layer"
    assert em.get("engine") == "fake_recording" and em.get("fake") is True
    # phan dinh danh theo trang van minh bach
    assert man["method_by_page"]["20"] == "direct" and man["method_by_page"]["6"] in ("ocr", "cached")
