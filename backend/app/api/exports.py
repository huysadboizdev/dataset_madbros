from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..services.export_service import _pages_range_label

router = APIRouter(prefix="/api/exports")


@router.get("")
def list_exports(request: Request, job_id: str | None = None):
    db = request.app.state.db
    if job_id:
        rows = db.query("SELECT * FROM exports WHERE job_id=? ORDER BY created_at DESC",
                        (job_id,))
    else:
        rows = db.query("SELECT * FROM exports ORDER BY created_at DESC LIMIT 50")
    return {"items": [dict(r) for r in rows]}


@router.get("/{export_id}/download")
def download(request: Request, export_id: str):
    db = request.app.state.db
    row = db.query_one("SELECT * FROM exports WHERE export_id=?", (export_id,))
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Export không tồn tại"})
    path = Path(row["artifact_path"])
    if not path.exists():
        raise HTTPException(410, detail={"code": "GONE", "message": "File xuất không còn; tạo lại export"})
    job = db.get_job(row["job_id"])
    ordinal = 0
    if job is not None:
        doc = db.get_document(job["document_id"])
        if doc is not None:
            ordinal = db.query_one("SELECT rowid rid FROM documents WHERE document_id=?",
                                   (doc["document_id"],))["rid"]
    fmt = row["format"]
    ext = {"md": "md", "json": "json"}.get(fmt, "zip")
    included = json.loads(row["included_pages_json"])
    fname = f"document_{ordinal:03d}_pages_{_pages_range_label(included)}_draft.{ext}"
    media = {"md": "text/markdown", "json": "application/json"}.get(
        fmt, "application/zip")
    return FileResponse(path, media_type=media, filename=fname)
