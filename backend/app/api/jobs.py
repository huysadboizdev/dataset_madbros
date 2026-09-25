from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import Database
from ..schemas import JobCreateRequest, JobModel, PageRunModel
from ..services.job_service import JobError, JobManager

router = APIRouter(prefix="/api/jobs")


def _mgr(request: Request) -> JobManager:
    return request.app.state.jobs


def _db(request: Request) -> Database:
    return request.app.state.db


def _job_model(db: Database, mgr: JobManager, job_id: str) -> JobModel:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Job không tồn tại"})
    doc = db.get_document(job["document_id"])
    runs = db.list_page_runs(job_id)
    ui = mgr.ui_state(job_id)
    counts = ui["counts"]
    return JobModel(
        job_id=job_id, document_id=job["document_id"],
        document_name=doc["original_name"], document_page_count=doc["page_count"],
        selected_pages=json.loads(job["selected_pages_json"]), mode=job["mode"],
        config_hash=job["config_hash"], status=job["status"],
        current_page=ui["current_page"],
        succeeded_pages=counts["SUCCEEDED"] + counts["NEEDS_REVIEW"],
        failed_pages=counts["FAILED"],
        pending_pages=counts["PENDING"] + counts["INTERRUPTED"],
        eta_s=ui["eta_s"], model_phase=ui["model_phase"],
        process_phase=ui.get("process_phase"),
        pages=[PageRunModel(page_no=r["page_no"], status=r["status"], method=r["method"],
                            attempt=r["attempt"], duration_s=r["duration_s"],
                            error=r["error"], active_revision_id=r["active_revision_id"],
                            review_status=r["review_status"]) for r in runs],
        created_at=job["created_at"], started_at=job["started_at"],
        finished_at=job["finished_at"],
    )


class RetryRequest(BaseModel):
    page_no: int


@router.post("", response_model=JobModel)
def create_job(request: Request, req: JobCreateRequest):
    mgr, db = _mgr(request), _db(request)
    doc = db.get_document(req.document_id)
    if doc is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Tài liệu không tồn tại"})
    try:
        job_id = mgr.create_job(req.document_id, req.selected_pages, req.mode, req.ocr_again,
                                req.notes)
    except JobError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
    return _job_model(db, mgr, job_id)


@router.get("")
def list_jobs(request: Request, limit: int = 20):
    mgr, db = _mgr(request), _db(request)
    rows = db.query("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (min(limit, 100),))
    return {"items": [_job_model(db, mgr, r["job_id"]) for r in rows]}


@router.get("/{job_id}", response_model=JobModel)
def get_job(request: Request, job_id: str):
    return _job_model(_db(request), _mgr(request), job_id)


@router.post("/{job_id}/start", response_model=JobModel)
def start_job(request: Request, job_id: str):
    mgr = _mgr(request)
    try:
        mgr.start(job_id)
    except JobError as e:
        code = 409 if e.code == "BUSY" else 422
        raise HTTPException(code, detail={"code": e.code, "message": e.message})
    return _job_model(_db(request), mgr, job_id)


@router.post("/{job_id}/pause", response_model=JobModel)
def pause_job(request: Request, job_id: str):
    mgr = _mgr(request)
    try:
        mgr.pause(job_id)
    except JobError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
    return _job_model(_db(request), mgr, job_id)


@router.post("/{job_id}/cancel", response_model=JobModel)
def cancel_job(request: Request, job_id: str):
    mgr = _mgr(request)
    try:
        mgr.cancel(job_id)
    except JobError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
    return _job_model(_db(request), mgr, job_id)


@router.post("/{job_id}/resume", response_model=JobModel)
def resume_job(request: Request, job_id: str):
    mgr = _mgr(request)
    try:
        mgr.start(job_id)
    except JobError as e:
        raise HTTPException(422 if e.code != "BUSY" else 409,
                            detail={"code": e.code, "message": e.message})
    return _job_model(_db(request), mgr, job_id)


@router.post("/{job_id}/retry", response_model=JobModel)
def retry_page(request: Request, job_id: str, req: RetryRequest):
    mgr = _mgr(request)
    try:
        mgr.retry_page(job_id, req.page_no)
    except JobError as e:
        raise HTTPException(422, detail={"code": e.code, "message": e.message})
    return _job_model(_db(request), mgr, job_id)
