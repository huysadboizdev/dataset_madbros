from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..cleaning.normalize import normalize_latex, normalize_text
from ..cleaning.pii import scan_pii
from ..cleaning.validators import latex_basic_check, validate_page_payload
from ..db import Database, _now
from ..settings import Settings
from ..storage.artifacts import canonical_hash, new_id


class RevisionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def load_revision_content(db: Database, revision_id: str) -> Dict[str, Any]:
    row = db.get_revision(revision_id)
    if row is None:
        raise RevisionError("NOT_FOUND", "Revision không tồn tại")
    with open(row["content_path"], "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- issue state (open/resolved, giu lich su) ----------------

def block_content_fp(block: Dict[str, Any]) -> str:
    """Fingerprint NOI DUNG lien quan cua mot block (dung de phat hien noi dung doi).

    Chi dung noi dung co that anh huong ket luan chuyen mon (type + text/latex + bbox
    lam tron), KHONG dung thoi gian/mo ta. 'skipped_visual' khong co text -> lay bbox.
    """
    if not block:
        return ""
    bbox = block.get("bbox")
    bbox_r = None
    if isinstance(bbox, (list, tuple)) and bbox:
        bbox_r = [round(float(x)) for x in bbox]
    return canonical_hash({
        "type": block.get("type"),
        "content": block.get("text") if block.get("type") != "formula" else block.get("text"),
        "bbox": bbox_r,
    })


def page_content_fp(blocks: List[Dict[str, Any]]) -> str:
    """Fingerprint toan bo noi dung trang (cho issue cap trang: NO_CONTENT, PII toan cuc)."""
    return canonical_hash([
        {"t": b.get("type"), "c": b.get("text"),
         "b": ([round(float(x)) for x in b["bbox"]] if isinstance(b.get("bbox"), (list, tuple)) and b.get("bbox") else None)}
        for b in blocks
    ])


def resolved_map(db: Database, job_id: str, page_no: int) -> Dict[tuple, Dict[str, Any]]:
    rows = db.query("SELECT * FROM issues WHERE job_id=? AND page_no=? AND status='resolved'",
                    (job_id, page_no))
    return {(r["type"], r["block_id"]): dict(r) for r in rows}


def apply_resolution(db: Database, job_id: str, page_no: int,
                     issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ke thua resolution CU khi NOI DUNG lien quan KHONG DOI.

    Quy tac (ghi ro): khop (type, block_id) VA content_fp cua issue moi bang content_fp
    da duoc nguoi dung resolve -> giu issue_id cu + trang thai resolved + lich su.
    Neu noi dung LIEN QUAN DA DOI (fp khac) -> issue MOI o trang thai OPEN; KHONG tu
    dong kep nhan xac nhan chuyen mon cua noi dung cu.
    """
    rmap = resolved_map(db, job_id, page_no)
    for it in issues:
        fp_new = it.get("content_fp")
        old = rmap.get((it["type"], it.get("block_id")))
        if old is not None and fp_new is not None and old.get("content_fp") == fp_new:
            it["issue_id"] = old["issue_id"]
            it["status"] = "resolved"
            it["resolved_at"] = old["resolved_at"]
            it["resolved_reason"] = old["resolved_reason"]
            it["checked_revision"] = old["checked_revision"]
            it["content_fp"] = old.get("content_fp")
        else:
            # noi dung doi (fp khac) hoac issue hoan toan moi -> mo, gan nhat revision hien tai
            it.setdefault("status", "open")
    return issues


def sync_issue_rows(db: Database, job_id: str, page_no: int,
                    issues: List[Dict[str, Any]]) -> None:
    stmts: List[tuple] = [
        ("DELETE FROM issues WHERE job_id=? AND page_no=? AND status='open'",
         (job_id, page_no)),
    ]
    for it in issues:
        stmts.append((
            "INSERT OR REPLACE INTO issues(issue_id, job_id, page_no, block_id, type,"
            " description, status, resolved_at, resolved_reason, checked_revision, content_fp)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (it["issue_id"], job_id, page_no, it.get("block_id"), it["type"],
             it["description"], it.get("status", "open"), it.get("resolved_at"),
             it.get("resolved_reason"), it.get("checked_revision"), it.get("content_fp")),
        ))
    db.executemany_commit(stmts)


def recalc_page_status(db: Database, job_id: str, page_no: int) -> None:
    run = db.query_one("SELECT status FROM page_runs WHERE job_id=? AND page_no=?",
                       (job_id, page_no))
    if run is None or run["status"] not in ("SUCCEEDED", "NEEDS_REVIEW"):
        return
    open_c = db.query_one(
        "SELECT COUNT(*) c FROM issues WHERE job_id=? AND page_no=? AND status='open'",
        (job_id, page_no))["c"]
    want = "NEEDS_REVIEW" if open_c else "SUCCEEDED"
    if run["status"] != want:
        db.execute("UPDATE page_runs SET status=? WHERE job_id=? AND page_no=?",
                   (want, job_id, page_no))


def compute_validator_issues(blocks: List[Dict[str, Any]], page_no: int) -> List[Dict[str, Any]]:
    """Chay lai validator TREN BLOCK MOI; khong noi danh sach cu.

    Moi issue gan `content_fp` = fingerprint noi dung LIEN QUAN da sinh ra no, de
    apply_resolution chi ke thua resolution khi noi dung do KHONG DOI.
    """
    issues: List[Dict[str, Any]] = []
    has_content = False
    for b in blocks:
        bid = b.get("block_id")
        text = b.get("text")
        fp = block_content_fp(b)
        if b["type"] == "skipped_visual":
            issues.append({"issue_id": new_id("iss"), "block_id": bid,
                           "type": "VISUAL_SKIPPED", "content_fp": fp,
                           "description": f"Hình minh họa tại trang PDF {page_no} chưa được xử lý"})
            continue
        if text:
            has_content = True
        if b["type"] == "formula" and text:
            bad = latex_basic_check(text)
            if bad:
                issues.append({"issue_id": new_id("iss"), "block_id": bid,
                               "type": "FORMULA_REVIEW", "content_fp": fp, "description": bad})
        if text:
            for pii in scan_pii(text):
                issues.append({"issue_id": new_id("iss"), "block_id": bid,
                               "type": f"PII_SUSPECT_{pii['type']}", "content_fp": fp,
                               "description": f"Có thể chứa PII ({pii['type']}); cân nhắc "
                                              f"thay bằng {pii['suggestion']}"})
    if not has_content:
        issues.append({"issue_id": new_id("iss"), "block_id": None,
                       "type": "NO_CONTENT_DETECTED", "content_fp": page_content_fp(blocks),
                       "description": "Trang không phát hiện nội dung chữ; có thể là ảnh "
                                      "không có chữ — cần người kiểm tra"})
    return issues


# ---------------- doc ghep cho API ----------------

def get_page_result(db: Database, settings: Settings, job_id: str, page_no: int,
                    reprocess_state: str = "idle") -> Optional[Dict[str, Any]]:
    run = db.query_one("SELECT * FROM page_runs WHERE job_id=? AND page_no=?", (job_id, page_no))
    if run is None:
        return None
    content: Optional[Dict[str, Any]] = None
    if run["active_revision_id"]:
        try:
            content = load_revision_content(db, run["active_revision_id"])
        except (RevisionError, OSError, json.JSONDecodeError):
            content = None
    # DB la nguon chan ly ve trang thai issue (open/resolved); content chi snapshot.
    db_rows = [dict(r) for r in db.query(
        "SELECT * FROM issues WHERE job_id=? AND page_no=?", (job_id, page_no))]
    by_id = {r["issue_id"]: r for r in db_rows}
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for i in (content or {}).get("issues", []):
        m = dict(i)
        r = by_id.get(i["issue_id"])
        if r is not None:
            m.update({k: r[k] for k in ("status", "resolved_at", "resolved_reason",
                                        "checked_revision", "content_fp")})
        merged.append(m)
        seen.add(i["issue_id"])
    for r in db_rows:
        if r["issue_id"] not in seen:
            r = dict(r)
            r["history_only"] = True
            merged.append(r)
    base = {
        "job_id": job_id, "pdf_page": page_no, "status": run["status"],
        "method": run["method"], "review_status": run["review_status"],
        "error": run["error"], "attempt": run["attempt"],
        "reprocess_state": reprocess_state,
        "printed_page": (content or {}).get("printed_page"),
        "revision_id": run["active_revision_id"],
        "blocks": (content or {}).get("blocks", []),
        "coordinate_space": (content or {}).get("coordinate_space"),
        "issues": merged,
        "open_issues": [m for m in merged if m.get("status", "open") == "open"],
        "engine_meta": (content or {}).get("engine_meta", {}),
        "updated_at": (content or {}).get("created_at"),
    }
    job = db.get_job(job_id)
    if job is not None:
        doc = db.get_document(job["document_id"])
        if doc is not None:
            base["document_id"] = doc["document_id"]
    return base


def list_revisions(db: Database, job_id: str, page_no: int) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT revision_id, parent_revision, kind, origin, hash, created_at"
        " FROM revisions WHERE job_id=? AND page_no=? ORDER BY created_at", (job_id, page_no))
    active = db.query_one(
        "SELECT active_revision_id FROM page_runs WHERE job_id=? AND page_no=?",
        (job_id, page_no))
    return [{**dict(r), "active": active is not None and active["active_revision_id"] == r["revision_id"]}
            for r in rows]


def edit_page(db: Database, settings: Settings, job_id: str, page_no: int,
              base_revision_id: str, blocks: List[Dict[str, Any]],
              printed_page: Optional[int]) -> Dict[str, Any]:
    run = db.query_one("SELECT * FROM page_runs WHERE job_id=? AND page_no=?", (job_id, page_no))
    if run is None:
        raise RevisionError("NOT_FOUND", "Trang không thuộc job")
    if run["active_revision_id"] != base_revision_id:
        raise RevisionError("CONFLICT", "Bản gốc đã bị thay đổi; tải lại trang trước khi sửa")
    base = load_revision_content(db, base_revision_id)
    new_blocks: List[Dict[str, Any]] = []
    for i, b in enumerate(blocks):
        btype = b.get("type", "paragraph")
        text = b.get("text")
        block_id = b.get("block_id") or f"p{page_no:04d}_b{i + 1:03d}"
        if btype == "formula":
            text = normalize_latex(text)
        elif btype == "skipped_visual":
            text = None
        elif text is not None:
            text = normalize_text(text)
        new_blocks.append({"block_id": block_id, "type": btype, "text": text,
                           "order": i, "bbox": b.get("bbox"),
                           "confidence": b.get("confidence")})
    if printed_page is not None and (isinstance(printed_page, bool)
                                     or not isinstance(printed_page, int) or printed_page < 1):
        raise RevisionError("BAD_TYPE", "Số trang in phải là số nguyên >= 1")
    content = dict(base)
    revision_id = new_id("rev")
    # VALIDATOR CHAY LAI tren noi dung moi; loi da sua thi bien mat, loi da resolve
    # thi giu lich su — KHONG noi danh sach cu.
    fresh = apply_resolution(db, job_id, page_no, compute_validator_issues(new_blocks, page_no))
    content.update({
        "revision_id": revision_id, "parent_revision": base_revision_id,
        "kind": "edited", "origin": "user_edit", "review_status": "edited",
        "blocks": new_blocks, "created_at": _now(), "issues": fresh,
    })
    if printed_page is not None:
        content["printed_page"] = printed_page
    errors = validate_page_payload({**content, "_expected_page": page_no})
    if errors:
        raise RevisionError("INVALID", "; ".join(errors))
    content["hash"] = canonical_hash({k: v for k, v in content.items() if k != "hash"})
    rpath = (settings.jobs_dir / job_id / "pages" / f"{page_no:04d}" /
             "revisions" / f"{revision_id}.json")
    rpath.parent.mkdir(parents=True, exist_ok=True)
    tmp = rpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(rpath)
    db.execute(
        "INSERT INTO revisions(revision_id, job_id, page_no, parent_revision, kind, origin,"
        " content_path, hash, created_at, edited_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (revision_id, job_id, page_no, base_revision_id, "edited", "user_edit",
         str(rpath), content["hash"], _now(), _now()))
    db.execute("UPDATE page_runs SET active_revision_id=?, review_status='edited'"
               " WHERE job_id=? AND page_no=?", (revision_id, job_id, page_no))
    sync_issue_rows(db, job_id, page_no, fresh)
    recalc_page_status(db, job_id, page_no)
    return {"revision_id": revision_id,
            "page": get_page_result(db, settings, job_id, page_no)}


def resolve_issue(db: Database, settings: Settings, job_id: str, page_no: int,
                  issue_id: str, reason: str,
                  base_revision_id: Optional[str] = None) -> Dict[str, Any]:
    """Dong issue theo CHU DINH nguoi dung + ly do + revision duoc kiem; giu lich su.

    - Chong request resolve dung revision cu: neu gui `base_revision_id` khac ban dang
      hoat dong -> CONFLICT (khong danh dau nham revision khac).
    - Gan `content_fp` cua NOI DUNG hien tai vao row resolved, de apply_resolution sau
      nay chi ke thua khi noi dung lien quan KHONG DOI.
    Khong tu dong dong issue chuyen mon chi vi parse JSON thanh cong.
    """
    row = db.query_one("SELECT * FROM issues WHERE issue_id=? AND job_id=? AND page_no=?",
                       (issue_id, job_id, page_no))
    if row is None:
        raise RevisionError("NOT_FOUND", "Issue không tồn tại")
    if row["status"] == "resolved":
        raise RevisionError("BAD_STATE", "Issue đã được đóng trước đó")
    if not reason or not reason.strip():
        raise RevisionError("MISSING_REASON", "Phải nêu lý do đóng issue")
    run = db.query_one("SELECT * FROM page_runs WHERE job_id=? AND page_no=?",
                       (job_id, page_no))
    if run is None:
        raise RevisionError("NOT_FOUND", "Trang không thuộc job")
    active = run["active_revision_id"]
    if base_revision_id is not None and base_revision_id != active:
        raise RevisionError("CONFLICT",
                            "Bản đang hoạt động đã đổi; tải lại trang rồi hãy đánh dấu đã xử lý")
    # fingerprint noi dung LIEN QUAN tai revision dang kiem (active)
    content_fp = row["content_fp"] if "content_fp" in row.keys() else None
    if active:
        try:
            content = load_revision_content(db, active)
        except (RevisionError, OSError, json.JSONDecodeError):
            content = {}
        if row["block_id"]:
            blk = next((b for b in content.get("blocks", [])
                        if b.get("block_id") == row["block_id"]), None)
            content_fp = block_content_fp(blk) if blk is not None else content_fp
        else:
            content_fp = page_content_fp(content.get("blocks", []))
    db.execute(
        "UPDATE issues SET status='resolved', resolved_at=?, resolved_reason=?,"
        " checked_revision=?, content_fp=? WHERE issue_id=?",
        (_now(), reason.strip()[:500], active, content_fp, issue_id))
    recalc_page_status(db, job_id, page_no)
    return get_page_result(db, settings, job_id, page_no)  # type: ignore[return-value]


def revert_to_base_ocr(db: Database, settings: Settings, job_id: str, page_no: int) -> Dict[str, Any]:
    rows = db.query(
        "SELECT * FROM revisions WHERE job_id=? AND page_no=? AND kind='ocr_raw' ORDER BY created_at",
        (job_id, page_no))
    if not rows:
        raise RevisionError("NOT_FOUND", "Không còn bản OCR gốc để hoàn tác")
    base = rows[0]
    db.execute("UPDATE page_runs SET active_revision_id=?, review_status='unreviewed'"
               " WHERE job_id=? AND page_no=?", (base["revision_id"], job_id, page_no))
    content = load_revision_content(db, base["revision_id"])
    issues = apply_resolution(db, job_id, page_no, [dict(i) for i in content.get("issues", [])])
    sync_issue_rows(db, job_id, page_no, issues)
    recalc_page_status(db, job_id, page_no)
    return get_page_result(db, settings, job_id, page_no)  # type: ignore[return-value]


def use_revision(db: Database, settings: Settings, job_id: str, page_no: int,
                 revision_id: str) -> Dict[str, Any]:
    row = db.get_revision(revision_id)
    if row is None or row["job_id"] != job_id or row["page_no"] != page_no:
        raise RevisionError("NOT_FOUND", "Revision không thuộc trang này")
    db.execute("UPDATE page_runs SET active_revision_id=? WHERE job_id=? AND page_no=?",
               (revision_id, job_id, page_no))
    content = load_revision_content(db, revision_id)
    issues = apply_resolution(db, job_id, page_no, [dict(i) for i in content.get("issues", [])])
    sync_issue_rows(db, job_id, page_no, issues)
    recalc_page_status(db, job_id, page_no)
    return get_page_result(db, settings, job_id, page_no)  # type: ignore[return-value]
