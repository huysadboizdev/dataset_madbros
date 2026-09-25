from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from typing import Optional

from ..db import Database
from ..schemas import PageEditRequest
from ..services.export_service import ExportError, build_export
from ..services.job_service import JobError
from ..services.revision_service import (RevisionError, edit_page, get_page_result,
                                         list_revisions, resolve_issue,
                                         revert_to_base_ocr, use_revision)

router = APIRouter(prefix="/api/jobs")


class ResolveRequest(BaseModel):
    reason: str
    base_revision_id: Optional[str] = None


def _deps(request: Request):
    return request.app.state.db, request.app.state.settings, request.app.state.jobs


@router.get("/{job_id}/pages/{page_no}")
def get_page(request: Request, job_id: str, page_no: int):
    db, settings, mgr = _deps(request)
    res = get_page_result(db, settings, job_id, page_no,
                          reprocess_state=mgr.reprocess_state(job_id, page_no))
    if res is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND",
                                         "message": "Trang không thuộc job"})
    return res


@router.get("/{job_id}/pages/{page_no}/revisions")
def get_revisions(request: Request, job_id: str, page_no: int):
    db, _, _ = _deps(request)
    return {"items": list_revisions(db, job_id, page_no)}


@router.patch("/{job_id}/pages/{page_no}")
def patch_page(request: Request, job_id: str, page_no: int, req: PageEditRequest):
    db, settings, _ = _deps(request)
    try:
        return edit_page(db, settings, job_id, page_no, req.base_revision_id,
                         [b.model_dump() for b in req.blocks], req.printed_page)
    except RevisionError as e:
        code = 409 if e.code == "CONFLICT" else 422
        raise HTTPException(code, detail={"code": e.code, "message": e.message})


@router.post("/{job_id}/pages/{page_no}/reprocess")
def reprocess_page(request: Request, job_id: str, page_no: int):
    db, _, mgr = _deps(request)
    try:
        state = mgr.reprocess_page(job_id, page_no)
        return {"state": state, "note": "Tạo revision OCR mới; không ghi đè bản sửa đang dùng."}
    except JobError as e:
        raise HTTPException(422 if e.code != "BUSY" else 409,
                            detail={"code": e.code, "message": e.message})


@router.post("/{job_id}/pages/{page_no}/use_revision")
def apply_revision(request: Request, job_id: str, page_no: int, revision_id: str):
    db, settings, _ = _deps(request)
    try:
        return use_revision(db, settings, job_id, page_no, revision_id)
    except RevisionError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})


@router.post("/{job_id}/pages/{page_no}/revert")
def revert(request: Request, job_id: str, page_no: int):
    db, settings, _ = _deps(request)
    try:
        return revert_to_base_ocr(db, settings, job_id, page_no)
    except RevisionError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})


@router.post("/{job_id}/pages/{page_no}/issues/{issue_id}/resolve")
def resolve(request: Request, job_id: str, page_no: int, issue_id: str, req: ResolveRequest):
    db, settings, _ = _deps(request)
    try:
        return resolve_issue(db, settings, job_id, page_no, issue_id, req.reason,
                             req.base_revision_id)
    except RevisionError as e:
        code = 409 if e.code == "CONFLICT" else 422
        raise HTTPException(code, detail={"code": e.code, "message": e.message})


@router.post("/{job_id}/exports")
def create_export(request: Request, job_id: str, format: str = "zip",
                  pages: str | None = None):
    db, settings, _ = _deps(request)
    page_list = None
    if pages:
        try:
            page_list = [int(p) for p in pages.split(",") if p.strip()]
        except ValueError:
            raise HTTPException(422, detail={"code": "BAD_PAGES",
                                             "message": "Danh sách trang không hợp lệ"})
    try:
        return build_export(db, settings, job_id, format, page_list)
    except ExportError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
