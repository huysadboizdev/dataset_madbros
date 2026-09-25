from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..schemas import DocumentModel, PageSelectionRequest, PageSelectionResponse
from ..services import pdf_service
from ..services.page_selection import SelectionError, parse_from_to, parse_page_expression
from ..storage.artifacts import new_id
from ..db import _now

router = APIRouter(prefix="/api/documents")


def _state(request: Request):
    return request.app.state


@router.post("", response_model=DocumentModel)
async def upload_document(request: Request, file: UploadFile = File(...)):
    st = _state(request)
    settings, db = st.settings, st.db
    max_bytes = settings.input_max_mb * 1024 * 1024
    document_id = new_id("doc")
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = settings.raw_dir / f"{document_id}.pdf"
    part = raw_path.with_suffix(".pdf.part")
    size = 0
    head = b""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(part, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                if size == 0:
                    head = chunk[:2048]
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, detail={
                        "code": "TOO_LARGE",
                        "message": (f"File vượt giới hạn {settings.input_max_mb} MB"
                                    f" (đã nhận {size} byte). "
                                    "Tăng 'input_max_mb' trong config.json nếu cần.")})
                h.update(chunk)
                out.write(chunk)
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:
        # dia day / quyen ghi / upload gian doan — don file tam dung pham vi
        part.unlink(missing_ok=True)
        raise HTTPException(507, detail={
            "code": "STORAGE_ERROR", "message": f"Không ghi được file tạm: {e}"})
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if size == 0:
        part.unlink(missing_ok=True)
        raise HTTPException(400, detail={"code": "EMPTY", "message": "File rỗng"})
    if not head.lstrip().startswith(b"%PDF-"):
        part.unlink(missing_ok=True)
        raise HTTPException(400, detail={
            "code": "NOT_PDF",
            "message": "File không phải PDF thật (dù có thể mang đuôi .pdf)."})
    file_hash = h.hexdigest()
    existing = db.get_document_by_hash(file_hash)
    if existing is not None:
        part.unlink(missing_ok=True)
        row = existing
        meta = json.loads(row["metadata_json"])
        meta["duplicate_of"] = row["document_id"]
        return DocumentModel(document_id=row["document_id"], original_name=row["original_name"],
                             size_bytes=row["size_bytes"], sha256=row["hash"],
                             page_count=row["page_count"], ingested_at=row["ingested_at"],
                             metadata=meta, duplicate=True)
    try:
        with pdf_service.PdfDoc(part) as pdf:
            page_count = pdf.page_count
    except pdf_service.PdfOpenError as e:
        part.unlink(missing_ok=True)
        raise HTTPException(400, detail={"code": e.code, "message": e.message})
    # Finalize: rename -> DB. FS va SQLite KHONG chung mot transaction atomic, nen
    # neu insert that bai phai roll back file vua rename (khong de raw orphan).
    try:
        os.replace(part, raw_path)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise HTTPException(507, detail={"code": "STORAGE_ERROR",
                                         "message": f"Không hoàn tất được file tạm: {e}"})
    try:
        db.execute(
            "INSERT INTO documents(document_id, hash, raw_path, original_name, size_bytes,"
            " page_count, metadata_json, ingested_at) VALUES(?,?,?,?,?,?,?,?)",
            (document_id, file_hash, str(raw_path), file.filename or "document.pdf",
             size, page_count, "{}", _now()))
    except sqlite3.IntegrityError:
        # dau tranh dedupe: upload khac chen hash cung truoc -> bo file cua minh, tra ban cu
        raw_path.unlink(missing_ok=True)
        row = db.get_document_by_hash(file_hash)
        if row is None:
            raise HTTPException(500, detail={"code": "INTERNAL", "message": "Lỗi ghi tài liệu"})
        meta = json.loads(row["metadata_json"])
        return DocumentModel(document_id=row["document_id"], original_name=row["original_name"],
                             size_bytes=row["size_bytes"], sha256=row["hash"],
                             page_count=row["page_count"], ingested_at=row["ingested_at"],
                             metadata=meta, duplicate=True)
    except Exception:
        # moi loi khac khi commit: roll back raw vua rename de reconcile don
        raw_path.unlink(missing_ok=True)
        raise
    return DocumentModel(document_id=document_id, original_name=file.filename or "document.pdf",
                         size_bytes=size, sha256=file_hash, page_count=page_count,
                         ingested_at=_now(), metadata={}, duplicate=False)


@router.get("")
def list_documents(request: Request, offset: int = 0, limit: int = 50):
    st = _state(request)
    rows = st.db.query(
        "SELECT * FROM documents ORDER BY ingested_at DESC LIMIT ? OFFSET ?",
        (min(limit, 200), max(offset, 0)))
    items = [{"document_id": r["document_id"], "original_name": r["original_name"],
              "size_bytes": r["size_bytes"], "page_count": r["page_count"],
              "sha256": r["hash"], "ingested_at": r["ingested_at"]} for r in rows]
    return {"items": items,
            "total": st.db.query_one("SELECT COUNT(*) c FROM documents")["c"]}


def _must_document(st, document_id: str):
    row = st.db.get_document(document_id)
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Tài liệu không tồn tại"})
    return row


@router.patch("/{document_id}/metadata")
def patch_metadata(request: Request, document_id: str, metadata: dict):
    """Tuy chon: mon/lop/bo_sach/ghi chu. Khong bat buoc de duoc OCR."""
    st = _state(request)
    row = _must_document(st, document_id)
    allowed = {"subject", "grade", "series", "notes"}
    meta = json.loads(row["metadata_json"] or "{}")
    for k, v in metadata.items():
        if k not in allowed:
            raise HTTPException(422, detail={"code": "BAD_KEY",
                                             "message": f"Khong ho tro truong '{k}'"})
        if v is not None:
            sval = str(v)[:120]
            if sval.strip():
                meta[k] = sval.strip()
            else:
                meta.pop(k, None)
    st.db.execute("UPDATE documents SET metadata_json=? WHERE document_id=?",
                  (json.dumps(meta, ensure_ascii=False), document_id))
    return {"document_id": document_id, "metadata": meta}


@router.get("/{document_id}/pages/{page_no}/preview")
def preview_page(request: Request, document_id: str, page_no: int):
    st = _state(request)
    doc = _must_document(st, document_id)
    if isinstance(page_no, bool) or page_no < 1 or page_no > doc["page_count"]:
        raise HTTPException(400, detail={
            "code": "OUT_OF_RANGE",
            "message": f"Trang phải trong 1..{doc['page_count']}"})
    cache = st.settings.preview_dir / document_id / f"p{page_no:04d}.png"
    if not cache.exists():
        try:
            with pdf_service.PdfDoc(Path(doc["raw_path"])) as pdf:
                png = pdf.render_page_png(page_no, st.settings.preview_dpi)
        except pdf_service.PdfOpenError as e:
            raise HTTPException(400, detail={"code": e.code, "message": e.message})
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".png.tmp")
        tmp.write_bytes(png)
        tmp.replace(cache)
    return FileResponse(cache, media_type="image/png")


@router.post("/{document_id}/selection/validate", response_model=PageSelectionResponse)
def validate_selection(request: Request, document_id: str, req: PageSelectionRequest):
    st = _state(request)
    doc = _must_document(st, document_id)
    page_count = doc["page_count"]
    warnings = []
    try:
        if req.all_pages:
            pages = list(range(1, page_count + 1))
            warnings.append(f"Bạn đã chủ động chọn TOÀN BỘ {page_count} trang."
                            " Tool sẽ xử lý đủ số trang này rồi dừng.")
        elif req.expression and req.expression.strip():
            pages = parse_page_expression(req.expression, page_count, allow_all=True)
        elif req.from_page is not None or req.to_page is not None:
            pages = parse_from_to(req.from_page, req.to_page, page_count)
        else:
            raise SelectionError("MISSING", "Chưa chọn trang nào.")
    except SelectionError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
    warnings.append(f"Số trang PDF tính cả trang bìa là {page_count} (không dùng số trang in trong sách).")
    return PageSelectionResponse(selected_pages=pages, selected_count=len(pages),
                                 document_page_count=page_count, warnings=warnings)
