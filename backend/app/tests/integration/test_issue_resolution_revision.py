from __future__ import annotations

"""Phat hien 1: resolution PHAI gan voi NOI DUNG (content_fp) + revision da kiem.

Loi cu: apply_resolution ghep theo (type, block_id) thuan tuy -> xac nhan chuyen mon
R1 tu dong dong len loi MOI phat sinh o R2 khi noi dung block da doi. Cac test nay
chung minh khong con ke thua nham. Du dung (issue_id moi, mo lai) khi noi dung doi;
giu resolved khi chung minh noi dung lien quan KHONG DOI; giu lich su; chong resolve
tren revision cu (409)."""

from ..conftest import start_job, upload, wait_status


def _add_broken_formula(client, job_id, text="\\frac{a}{b"):
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    page["blocks"].append({"block_id": "p0006_b900", "type": "formula", "text": text,
                           "order": 90, "bbox": None, "confidence": None})
    return client.patch(f"/api/jobs/{job_id}/pages/6",
                        json={"base_revision_id": page["revision_id"], "blocks": page["blocks"]})


def _formula_issue(page_json):
    return [i for i in page_json["issues"]
            if i["type"] == "FORMULA_REVIEW" and i.get("block_id") == "p0006_b900"]


def test_resolve_at_R1_does_not_auto_close_new_error_at_R2(client):
    """Resolve co cung block_id o R1, xong R2 doi noi dung thanh LOI KHAC -> issue OPEN."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    # chen loi, resolve, roi doi thanh mot loi khac cung block_id
    _add_broken_formula(client, job_id)
    bad = client.get(f"/api/jobs/{job_id}/pages/6").json()
    iss = _formula_issue(bad)[0]
    r = client.post(f"/api/jobs/{job_id}/pages/6/issues/{iss['issue_id']}/resolve",
                    json={"reason": "Da doi chieu sach o revision nay",
                          "base_revision_id": bad["revision_id"]})
    assert r.status_code == 200
    resolved = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert _formula_issue(resolved)[0]["status"] == "resolved"

    # R2: SUA NOI DUNG block do thanh mot loi khac (unbalanced ngoac khac)
    cur = client.get(f"/api/jobs/{job_id}/pages/6").json()
    for b in cur["blocks"]:
        if b["block_id"] == "p0006_b900":
            b["text"] = "\\frac{a}{b]   ]"   # noi dung moi -> fp doi -> khong duoc ke thua resolved
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": cur["revision_id"], "blocks": cur["blocks"]})
    after = client.get(f"/api/jobs/{job_id}/pages/6").json()
    fi = _formula_issue(after)
    # phai co mot FORMULA_REVIEW MOI dang OPEN cho block da doi noi dung (khong phai copies R1)
    open_b900 = [i for i in fi if i["status"] == "open"]
    resolved_b900 = [i for i in fi if i["status"] == "resolved"]
    assert open_b900, "noi dung doi ma khong phat sinh issue MO dang mo"
    assert open_b900[0]["issue_id"] != resolved_b900[0]["issue_id"] if resolved_b900 else True
    assert after["status"] == "NEEDS_REVIEW"
    # LICH SU resolution cu van con (khong xoa)
    assert resolved_b900 and "doi chieu" in (resolved_b900[0]["resolved_reason"] or "")


def test_resolve_pii_new_pii_reopens_same_block(client):
    """Resolve PII o R1 -> them PII MOI vao CUNG block -> issue PII OPEN lai."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    page = client.get(f"/api/jobs/{job_id}/pages/6").json()
    page["blocks"][0]["text"] = "Liên hệ a@x.com để nhận file"
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": page["revision_id"], "blocks": page["blocks"]})
    cur = client.get(f"/api/jobs/{job_id}/pages/6").json()
    pii = [i for i in cur["issues"] if i["type"] == "PII_SUSPECT_EMAIL" and i["status"] == "open"][0]
    client.post(f"/api/jobs/{job_id}/pages/6/issues/{pii['issue_id']}/resolve",
                json={"reason": "Email công khai, chấp nhận",
                      "base_revision_id": cur["revision_id"]})
    # them SO DIEN THOAI (PII khac kiieu) + giu email -> van can mo
    cur2 = client.get(f"/api/jobs/{job_id}/pages/6").json()
    for b in cur2["blocks"]:
        if b["block_id"] == cur2["blocks"][0]["block_id"]:
            b["text"] = "Liên hệ a@x.com hoặc gọi 0912345678"
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": cur2["revision_id"], "blocks": cur2["blocks"]})
    final = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # ca EMAIL (noi dung doi -> fp doi) va PHONE deu phai mo, khong ke thua resolved cu
    open_types = {i["type"] for i in final["issues"] if i["status"] == "open"}
    assert "PII_SUSPECT_PHONE_VN" in open_types
    assert final["status"] == "NEEDS_REVIEW"


def test_edit_other_block_keeps_history_of_first(client):
    """Sua block KHAC khong xoa lan danh sach issue/lich su cua block da resolve."""
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    _add_broken_formula(client, job_id, text="\\frac{1}{0")
    cur = client.get(f"/api/jobs/{job_id}/pages/6").json()
    iss = _formula_issue(cur)[0]
    client.post(f"/api/jobs/{job_id}/pages/6/issues/{iss['issue_id']}/resolve",
                json={"reason": "Mẫu số khác 0 trong bối cảnh", "base_revision_id": cur["revision_id"]})
    # sua block 0 khong lien quan
    after = client.get(f"/api/jobs/{job_id}/pages/6").json()
    after["blocks"][0]["text"] = "Doan dan thieu khong lien quan cong thuc."
    client.patch(f"/api/jobs/{job_id}/pages/6",
                 json={"base_revision_id": after["revision_id"], "blocks": after["blocks"]})
    fin = client.get(f"/api/jobs/{job_id}/pages/6").json()
    # resolution cua block b900 (noi dung khong doi) van duoc GIU resolved — khong bi xoa
    b900 = [i for i in fin["issues"] if i.get("block_id") == "p0006_b900"
            and i["type"] == "FORMULA_REVIEW"]
    assert b900 and b900[0]["status"] == "resolved"
    assert b900[0]["resolved_reason"]


def test_resolve_against_stale_revision_conflicts(client):
    doc = upload(client)
    job_id = start_job(client, doc["document_id"], [6])
    wait_status(client, job_id, ("COMPLETED",))
    _add_broken_formula(client, job_id)
    cur = client.get(f"/api/jobs/{job_id}/pages/6").json()
    iss = _formula_issue(cur)[0]
    active_rev = cur["revision_id"]
    # resolve dung revision cu (khong phai ban dang hoat dong) -> 409 CONFLICT
    r = client.post(f"/api/jobs/{job_id}/pages/6/issues/{iss['issue_id']}/resolve",
                    json={"reason": "x", "base_revision_id": "rev_giadan_khong_ton_tai"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CONFLICT"
    # van con mo, chua bi danh dau
    still = client.get(f"/api/jobs/{job_id}/pages/6").json()
    assert _formula_issue(still)[0]["status"] == "open"
    # resolve dung revision hien hanh -> OK
    good = client.post(f"/api/jobs/{job_id}/pages/6/issues/{iss['issue_id']}/resolve",
                       json={"reason": "x", "base_revision_id": active_rev})
    assert good.status_code == 200
    assert _formula_issue(good.json())[0]["status"] == "resolved"

