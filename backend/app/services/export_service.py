from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cleaning.pii import scan_pii
from ..cleaning.export_sanitize import sanitize_public
from ..db import Database, _now
from ..settings import Settings
from ..storage.artifacts import new_id, sha256_bytes
from .revision_service import load_revision_content

TOOL_VERSION = "0.1.1"
SCOPE = "text_and_formulas_only"
DONE_STATUSES = ("SUCCEEDED", "NEEDS_REVIEW")


def _pages_range_label(pages: List[int]) -> str:
    if not pages:
        return "none"
    parts: List[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        parts.append(f"{start:03d}" if start == prev else f"{start:03d}-{prev:03d}")
        start = prev = p
    parts.append(f"{start:03d}" if start == prev else f"{start:03d}-{prev:03d}")
    return "_".join(parts)


def _block_markdown(b: Dict[str, Any], page_no: int) -> str:
    t = b.get("type")
    text = b.get("text")
    if t == "skipped_visual":
        bbox = b.get("bbox") or []
        pos = f" (vị trí approximate: {[round(x) for x in bbox]})" if bbox else ""
        note = f"> ⚠️ Hình minh họa tại trang PDF {page_no} chưa được xử lý{pos}."
        # P14: neu OCR thuc su ghi nhan text tren vung hinh thi giu lai (1 lan,
        # khong nhan doi), kem ghi chu chua-xac-thuc; KHONG bia mo ta noi dung hinh.
        if text and str(text).strip():
            note += f"\n> Text OCR ghi nhận tại vùng hình (chưa xác thực): {text}"
        return note
    if t == "formula":
        return f"$$\n{text or ''}\n$$"
    if t == "heading":
        return f"### {text or ''}"
    if t == "table":
        return text or ""
    if t == "list":
        return "\n".join(f"- {line}" for line in (text or "").split("\n") if line.strip())
    return text or ""


def safe_export_title(document_label: str, user_meta: Dict[str, Any]) -> str:
    """Tieu de Markdown AN TOAN: khong dung ten file goc (co the chua PII).

    Chi dung nhan do nguoi dung dien co nhan (mon/lop/bo sach) — da duoc scan
    PII o goi tri truoc khi vao day; neu con nghi ngor thi dung nhan opague.
    """
    parts = [str(user_meta.get(k) or "").strip() for k in ("subject", "grade", "series")]
    parts = [p for p in parts if p and not scan_pii(p)]
    if parts:
        return " — ".join(parts)
    return document_label


def build_markdown(display_title: str, document_id: str, job_id: str,
                   requested: List[int], pages: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        f"# {display_title}",
        "",
        f"- `document_id`: {document_id} · `job_id`: {job_id}",
        f"- Trang PDF đã chọn: {requested[0] if requested else '—'}"
        f"–{requested[-1] if requested else ''} ({len(requested)} trang được yêu cầu,"
        f" {len(pages)} trang có kết quả)",
        "- **Trạng thái: Bản trích xuất nháp** (chưa duyệt độc lập).",
        f"- Phạm vi: chỉ chữ và công thức (`{SCOPE}`); chưa xử lý hình học/đồ thị.",
        "- Lưu ý ranh giới: các trang không liên tiếp được giữ riêng theo số trang PDF;"
        " không tự nối đoạn qua khoảng trống.",
        "",
    ]
    for page in pages:
        pn = page["pdf_page"]
        lines.append(f"## Trang PDF {pn}")
        if page.get("printed_page"):
            lines.append(f"*(Số trang in theo ghi chú người dùng: {page['printed_page']})*")
        for b in page.get("blocks", []):
            md = _block_markdown(b, pn)
            if md:
                lines.append(md)
                lines.append("")
        lines.append("> Ranh giới trang: nội dung có thể tiếp tục ở trang khác chưa được chọn."
                     " Xem trang kề nếu cần.")
        lines.append("")
    return "\n".join(lines)


def build_public_json(document_id: str, job_id: str, doc_page_count: int,
                      requested: List[int], pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    included = [p["pdf_page"] for p in pages]
    missing = [p for p in requested if p not in included]
    return {
        "schema_version": "1.0.1",
        "tool_version": TOOL_VERSION,
        "document_id": document_id,
        "job_id": job_id,
        "document_page_count": doc_page_count,
        "requested_pages": requested,
        "included_pages": included,
        "missing_pages": missing,
        "status": "draft",
        "partial": bool(missing),
        "scope": SCOPE,
        "generated_at": _now(),
        "pages": pages,
    }


class ExportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _sanitize_meta_for_export(meta: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Metadata xuat ra ZIP phai qua PII scan; gia tri nghi ngo bi thay placeholder."""
    out: Dict[str, Any] = {}
    notes: List[str] = []
    for k, v in (meta or {}).items():
        sval = str(v)
        if scan_pii(sval):
            out[k] = "[REDACTED_PII_SUSPECT]"
            notes.append(f"metadata.{k} chua noi dung nghi PII — da redact khi xuat")
        else:
            out[k] = sval
    return out, notes


def build_export(db: Database, settings: Settings, job_id: str, fmt: str,
                 pages_filter: Optional[List[int]] = None) -> Dict[str, Any]:
    job = db.get_job(job_id)
    if job is None:
        raise ExportError("NOT_FOUND", "Job không tồn tại")
    doc = db.get_document(job["document_id"])
    requested = json.loads(job["selected_pages_json"])
    if pages_filter:
        bad = [p for p in pages_filter if p not in requested]
        if bad:
            raise ExportError("OUT_OF_SCOPE", f"Trang ngoài phạm vi đã chọn: {bad}")
        wanted = [p for p in requested if p in pages_filter]
    else:
        wanted = list(requested)

    pages_out: List[Dict[str, Any]] = []
    revision_map: Dict[str, str] = {}
    engine_metas: Dict[str, Any] = {}
    # uu tien ghi model THAT (engine OCR/cache) vao manifest, khong phai lop chu
    # truc tiep pdf_text_layer — tranh truong hop xuat tron trang khi trang cuoi
    # la direct nen manifest mat han danh tinh model da OCR cac trang khac.
    model_metas: Dict[str, Any] = {}
    page_issues: List[Dict[str, Any]] = []
    for run in db.list_page_runs(job_id):
        if run["page_no"] not in wanted or run["status"] not in DONE_STATUSES:
            continue
        if not run["active_revision_id"]:
            continue
        content = load_revision_content(db, run["active_revision_id"])
        revision_map[str(run["page_no"])] = run["active_revision_id"]
        page_meta = content.get("engine_meta") or {}
        engine_metas = page_meta or engine_metas
        if page_meta.get("engine") and page_meta["engine"] != "pdf_text_layer":
            model_metas = page_meta
        page_obj = {
            "pdf_page": run["page_no"],
            "printed_page": content.get("printed_page"),
            "revision_id": run["active_revision_id"],
            "method": run["method"],
            "review_status": "edited" if content.get("kind") == "edited" else "unreviewed",
            "blocks": content.get("blocks", []),
            "coordinate_space": content.get("coordinate_space"),
            "issues": sorted({i["type"] for i in content.get("issues", [])}),
        }
        pages_out.append(page_obj)
    # van de lay tu DB (nguon chan ly ve open/resolved), khong phai snapshot trong revision
    for run in db.list_page_runs(job_id):
        if run["page_no"] not in wanted:
            continue
        for r in db.query(
                "SELECT issue_id, block_id, type, description, status, resolved_at,"
                " resolved_reason, checked_revision FROM issues WHERE job_id=? AND page_no=?",
                (job_id, run["page_no"])):
            page_issues.append({"page_no": run["page_no"], **dict(r)})
    pages_out.sort(key=lambda p: p["pdf_page"])

    included = [p["pdf_page"] for p in pages_out]
    missing = [p for p in wanted if p not in included]
    if not included:
        raise ExportError("NO_RESULTS", "Chưa có trang nào hoàn thành để xuất")

    ordinal = db.query_one("SELECT rowid AS rid FROM documents WHERE document_id=?",
                           (doc["document_id"],))["rid"]
    doc_label = f"document_{ordinal:03d}"
    user_meta = json.loads(doc["metadata_json"] or "{}")
    meta_out, meta_notes = _sanitize_meta_for_export(user_meta)
    display_title = safe_export_title(doc_label, user_meta)
    if meta_notes:
        page_issues.append({"page_no": None, "issue_id": new_id("iss"),
                            "block_id": None, "type": "PII_REDACTED_METADATA",
                            "description": "; ".join(meta_notes), "status": "open"})

    md_text = build_markdown(display_title, doc["document_id"], job_id, wanted, pages_out)
    public = build_public_json(doc["document_id"], job_id, doc["page_count"], wanted, pages_out)
    manifest = {
        "tool_version": TOOL_VERSION,
        "job_id": job_id,
        "document": {"document_id": doc["document_id"],
                     "sha256": doc["hash"], "page_count": doc["page_count"],
                     "user_metadata": meta_out},
        "requested_pages": wanted,
        "included_pages": included,
        "missing_pages": missing,
        "revision_map": revision_map,
        "config_hash": job["config_hash"],
        "engine_meta": model_metas or engine_metas,
        "method_by_page": {str(p["pdf_page"]): p["method"] for p in pages_out},
        "scope": SCOPE,
        "status": "draft",
        "generated_at": _now(),
        "notes": "Bản nháp trích xuất; chưa duyệt độc lập; không phải dữ liệu đã sẵn sàng huấn luyện."
                 " Tên file gốc được giữ trong kho nội bộ, không đưa vào gói xuất.",
    }
    issues_doc = {"job_id": job_id, "issues": page_issues}

    # Sanitize CAU TRUC toan bo metadata dau ra (loai duong dan tuyet doi / username /
    # PII trong chuoi), GIU hash + ten model + so. Ap dung cho manifest + issues dieu khong
    # (KHONG cham NOI DUNG toan hoc trong content pages).
    manifest = sanitize_public(manifest)
    issues_doc = sanitize_public(issues_doc)

    export_id = new_id("exp")
    label = _pages_range_label(included)
    base_name = f"{doc_label}_pages_{label}_draft"
    files = {
        "content.md": md_text,
        "content.json": json.dumps(public, ensure_ascii=False, indent=1),
        "issues.json": json.dumps(issues_doc, ensure_ascii=False, indent=1),
    }
    # Manifest KHONG tu khai checksum cua chinh no (no thay doi khi chen checksum).
    # Chi khai bao checksum cac file khac; checksum ZIP nam NGOAI ZIP (DB + API response).
    checksums = {name: sha256_bytes(data.encode("utf-8")) for name, data in files.items()}
    manifest["checksums_sha256"] = checksums
    manifest["self_checksum_note"] = ("manifest.json không có self-checksum;"
                                      " SHA-256 của cả ZIP lưu ở DB exports.checksum")
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=1)

    if fmt == "md":
        fname = base_name + ".md"
        artifact = settings.exports_dir / f"{export_id}.md"
        data = md_text.encode("utf-8")
    elif fmt == "json":
        fname = base_name + ".json"
        artifact = settings.exports_dir / f"{export_id}.json"
        data = json.dumps(public, ensure_ascii=False, indent=1).encode("utf-8")
    else:
        fname = base_name + ".zip"
        artifact = settings.exports_dir / f"{export_id}.zip"
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, txt in files.items():
                zf.writestr(name, txt)
        data = buf.getvalue()
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(data)
    zip_checksum = sha256_bytes(data)
    db.execute(
        "INSERT INTO exports(export_id, job_id, format, revision_map_json,"
        " included_pages_json, missing_pages_json, artifact_path, checksum, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (export_id, job_id, fmt, json.dumps(revision_map), json.dumps(included),
         json.dumps(missing), str(artifact), zip_checksum, _now()))
    return {
        "export_id": export_id, "job_id": job_id, "format": fmt,
        "included_pages": included, "missing_pages": missing,
        "partial": bool(missing), "filename": fname,
        "created_at": _now(), "checksum_sha256": zip_checksum,
        "file_checksums_sha256": checksums,
    }
