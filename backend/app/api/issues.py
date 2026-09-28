"""API issue tracking (SOP §9.3).

Endpoints:
- POST /api/issues — tạo phiếu lỗi
- GET /api/issues?source_id=... — liệt kê issues
- GET /api/issues/{issue_id} — chi tiết issue
- PATCH /api/issues/{issue_id} — cập nhật trạng thái
- GET /api/sources/{source_id}/issues/blockers — kiểm tra blockers
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..cleaning.export_sanitize import sanitize_public
from ..dataset.issue_tracker import (
    ERROR_TYPE_FORMULA_ERROR,
    ERROR_TYPE_MISSING_CONTEXT,
    ERROR_TYPE_PII,
    ERROR_TYPE_SOURCE_CONDITION,
    ERROR_TYPE_TEST_LEAK,
    ERROR_TYPE_WRONG_ANSWER,
    IssueTracker,
    SEVERITY_BLOCKER,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RESOLVED,
    STATUS_WONT_FIX,
)

router = APIRouter(prefix="/api/issues")


def _tracker(request: Request) -> IssueTracker:
    return IssueTracker(request.app.state.db)


def _public(obj):
    return sanitize_public(obj)


class CreateIssueRequest(BaseModel):
    source_id: str = Field(..., pattern=r"^[A-Z]{2,4}_G\d{2}_\d{4}_\d{4}$")
    source_version: int = Field(default=1, ge=1)
    severity: str = Field(..., pattern=f"^{SEVERITY_BLOCKER}|{SEVERITY_HIGH}|{SEVERITY_MEDIUM}|{SEVERITY_LOW}$")
    error_type: str = Field(..., min_length=1)
    description: str = Field(..., min_length=10)
    location: Optional[dict] = None
    evidence: Optional[str] = None
    assignee_code: Optional[str] = None
    deadline: Optional[str] = None


class UpdateIssueRequest(BaseModel):
    status: Optional[str] = Field(
        default=None,
        pattern=f"^{STATUS_OPEN}|{STATUS_IN_PROGRESS}|{STATUS_RESOLVED}|{STATUS_WONT_FIX}$",
    )
    resolution: Optional[str] = None
    assignee_code: Optional[str] = None


# NOTE: /sources/{...} MUST come before /{issue_id} — FastAPI matches paths in order

@router.post("", response_model=dict)
def create_issue(request: Request, req: CreateIssueRequest):
    """Tạo phiếu lỗi mới theo SOP §9.3."""
    tracker = _tracker(request)
    issue_id = tracker.create_issue(
        source_id=req.source_id,
        source_version=req.source_version,
        severity=req.severity,
        error_type=req.error_type,
        description=req.description,
        location=req.location,
        evidence=req.evidence,
        assignee_code=req.assignee_code,
        deadline=req.deadline,
    )
    return _public({"issue_id": issue_id, "status": "created"})


@router.get("", response_model=dict)
def list_issues(
    request: Request,
    source_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    error_type: Optional[str] = None,
):
    """Liệt kê issues (có thể lọc theo source_id/severity/status/error_type)."""
    tracker = _tracker(request)
    issues = tracker.list_issues(
        source_id=source_id,
        severity=severity,
        status=status,
        error_type=error_type,
    )
    return _public({
        "count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    })


@router.get("/sources/{source_id}/blockers", response_model=dict)
def check_blockers(request: Request, source_id: str):
    """Kiểm tra xem source có blockers chưa giải quyết không."""
    tracker = _tracker(request)
    blockers = tracker.has_blockers(source_id)
    count = tracker.count_blockers(source_id)
    return _public({"has_blockers": blockers, "blocker_count": count})


@router.get("/{issue_id}", response_model=dict)
def get_issue(request: Request, issue_id: str):
    """Lấy chi tiết một issue."""
    tracker = _tracker(request)
    issue = tracker.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=_public({
            "code": "ISSUE_NOT_FOUND",
            "message": f"Issue {issue_id} not found",
        }))
    return _public({"issue": issue.to_dict()})


@router.patch("/{issue_id}", response_model=dict)
def update_issue(request: Request, issue_id: str, req: UpdateIssueRequest):
    """Cập nhật trạng thái issue."""
    tracker = _tracker(request)
    issue = tracker.get_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=_public({
            "code": "ISSUE_NOT_FOUND",
            "message": f"Issue {issue_id} not found",
        }))

    updated = tracker.update_issue(
        issue_id=issue_id,
        status=req.status,
        resolution=req.resolution,
        assignee_code=req.assignee_code,
    )
    if not updated:
        raise HTTPException(status_code=400, detail=_public({
            "code": "UPDATE_FAILED",
            "message": "No fields to update",
        }))
    return _public({"issue_id": issue_id, "updated": True})
