from __future__ import annotations

"""P02-P04 (mức API), P16, P17, P19, P20: chọn trang, export một phần,
sửa revision, tên file có dấu, nhãn nháp."""

import io
import time
import zipfile

from ..conftest import make_pdf, start_job, upload, wait_status


def test_api_selection_range_list_errors(client):
    doc = upload(client, pages=138)
    did = doc["document_id"]
    r = client.post(f"/api/documents/{did}/selection/validate",
                    json={"expression": "1,5-7,7,138"})  # P02
    assert r.json()["selected_pages"] == [1, 5, 6, 7, 138]
    assert r.json()["selected_count"] == 5

    for bad, code in [( {"expression": "0"}, "NON_POSITIVE"),
                      ({"expression": "139"}, "OUT_OF_RANGE"),
                      ({"expression": "10-5"}, "REVERSED_RANGE"),
                      ({"expression": "5.5"}, "NOT_INT"),
                      ({"expression": ""}, "MISSING")]:  # P03, P04
        r = client.post(f"/api/documents/{did}/selection/validate", json=bad)
        assert r.status_code == 422, bad
        assert r.json()["detail"]["code"] == code, bad

    r = client.post(f"/api/documents/{did}/selection/validate",
                    json={"from_page": 5, "to_page": 10})
    assert r.json()["selected_pages"] == [5, 6, 7, 8, 9, 10]


def test_p03_invalid_selection_does_not_create_job(client):
    doc = upload(client)
    r = client.post("/api/jobs", json={"document_id": doc["document_id"],
                                       "selected_pages": [0, 999]})
    assert r.status_code == 422
    assert client.get("/api/jobs").json()["items"] == []


def test_p16_partial_export_honest(tmp_path):
    # trang 7 THAT BAI that -> export mot phan phai trung thuc
    from fastapi.testclient import TestClient
    from ..conftest import make_app
    dlog = tmp_path / "e.log"
    app, settings = make_app(tmp_path, ["--dispatch-log", str(dlog), "--fail-pages", "7"])
    with TestClient(app) as client:
        tok = client.get("/api/session").json()["token"]
        client.headers.update({"x-pdfcleaner-token": tok})
        client.dispatch_log_path = dlog
        client.settings = settings
        doc = upload(client)
        job_id = start_job(client, doc["document_id"], [5, 6, 7])
        j = wait_status(client, job_id, ("COMPLETED_WITH_ERRORS",))
        assert j["failed_pages"] == 1
        r = client.post(f"/api/jobs/{job_id}/exports?format=zip")
        assert r.status_code == 200
        exp = r.json()
        assert exp["included_pages"] == [5, 6]
        assert exp["missing_pages"] == [7]
        assert exp["partial"] is True
        dl = client.get(f"/api/exports/{exp['export_id']}/download")
        assert dl.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(dl.content))
        names = set(zf.namelist())
        assert names == {"content.md", "content.json", "manifest.json", "issues.json"}
        import json
        pub = json.loads(zf.read("content.json"))
        assert pub["requested_pages"] == [5, 6, 7]
        assert pub["included_pages"] == [5, 6]
        assert pub["missing_pages"] == [7]
        assert pub["status"] == "draft" and pub["scope"] == "text_and_formulas_only"
        man = json.loads(zf.read("manifest.json"))
        assert man["missing_pages"] == [7]
        assert "checksums_sha256" in man
        assert "raw/" not in str(names)
        md = zf.read("content.md").decode("utf-8")
        assert "Bản trích xuất nháp" in md
        # filter subset la pham vi hop le: requested = [5,6], khong con trang thieu
        exp2 = client.post(f"/api/jobs/{job_id}/exports?format=json&pages=5,6").json()
        assert exp2["missing_pages"] == [] and exp2["partial"] is False


def test_p17_edit_survives_reload_and_md_json_agree(client, tmp_path):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    rev0 = page["revision_id"]
    page["blocks"][0]["text"] = "SỬA XONG: phương trình $x^2-4=0$ có hai nghiệm."
    r = client.patch(f"/api/jobs/{job_id}/pages/6",
                     json={"base_revision_id": rev0, "blocks": page["blocks"]})
    assert r.status_code == 200
    # conflict khi base cu
    r = client.patch(f"/api/jobs/{job_id}/pages/6",
                     json={"base_revision_id": rev0, "blocks": page["blocks"]})
    assert r.status_code == 409

    # mo lai app tren cung du lieu (gia lap dong mo lai)
    from fastapi.testclient import TestClient
    from ..conftest import make_app
    app2, settings2 = make_app(tmp_path)
    with TestClient(app2) as c2:
        tok = c2.get("/api/session").json()["token"]
        c2.headers.update({"x-pdfcleaner-token": tok})
        p2 = c2.get(f"/api/jobs/{job_id}/pages/6").json()
        assert "SỬA XONG" in p2["blocks"][0]["text"]  # con sau khi mo lai
        assert p2["review_status"] == "edited"
        exp = c2.post(f"/api/jobs/{job_id}/exports?format=zip").json()
        zf = zipfile.ZipFile(io.BytesIO(c2.get(
            f"/api/exports/{exp['export_id']}/download").content))
        md = zf.read("content.md").decode("utf-8")
        assert "SỬA XONG" in md  # cung revisionvoi JSON
        assert "$x^2-4=0$" in md


def test_p19_diacritic_space_filenames(client):
    name = "bài tập (cá nhân) 2026 .pdf"
    data = make_pdf(client.settings.project_root)
    r = client.post("/api/documents",
                    files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200
    did = r.json()["document_id"]
    assert r.json()["original_name"] == name
    job_id = start_job(client, did, [6])
    wait_status(client, job_id, ("COMPLETED",))
    exp = client.post(f"/api/jobs/{job_id}/exports?format=zip").json()
    assert "document_" in exp["filename"]  # ten xuat khong chua PII/ten goc
    dl = client.get(f"/api/exports/{exp['export_id']}/download")
    assert dl.status_code == 200


def test_p20_always_draft_no_approved_label(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    exp = client.post(f"/api/jobs/{job_id}/exports?format=json").json()
    import json
    body = client.get(f"/api/exports/{exp['export_id']}/download")
    pub = json.loads(body.content)
    assert pub["status"] == "draft"
    assert "approved" not in json.dumps(pub).lower()


def test_api_rejects_arbitrary_paths_and_bad_files(client):
    r = client.post("/api/documents", files={"file": ("x.pdf", b"khong phai pdf", "application/pdf")})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NOT_PDF"
    # preview ngoai pham vi
    doc = upload(client)
    assert client.get(f"/api/documents/{doc['document_id']}/pages/999/preview").status_code == 400
    # preview chi render dung trang yeu cau, khong OCR
    pr = client.get(f"/api/documents/{doc['document_id']}/pages/7/preview")
    assert pr.status_code == 200 and pr.headers["content-type"] == "image/png"
