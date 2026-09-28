"""Issue tracking theo SOP §9.3 — phiếu lỗi chi tiết.

Phiếu lỗi gồm: issue_id, source_id, phiên bản, vị trí trang/slide/câu,
loại lỗi, mức độ, mô tả, người nhận, hạn sửa và bằng chứng đã kiểm tra lại.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..db import Database, _now

# Các mức độ lỗi theo SOP
SEVERITY_BLOCKER = "BLOCKER"  # Lỗi chặn phát hành
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

# Các loại lỗi phổ biến
ERROR_TYPE_PII = "PII"
ERROR_TYPE_WRONG_ANSWER = "WRONG_ANSWER"
ERROR_TYPE_MISSING_CONTEXT = "MISSING_CONTEXT"
ERROR_TYPE_FORMULA_ERROR = "FORMULA_ERROR"
ERROR_TYPE_SOURCE_CONDITION = "SOURCE_CONDITION"
ERROR_TYPE_TEST_LEAK = "TEST_LEAK"
ERROR_TYPE_LOST_SOURCE_LINK = "LOST_SOURCE_LINK"

# Các trạng thái issue
STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUS_WONT_FIX = "wont_fix"

ALL_SEVERITIES = {SEVERITY_BLOCKER, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW}
ALL_STATUSES = {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_WONT_FIX}


@dataclass
class SourceIssue:
    """Phiếu lỗi theo SOP §9.3."""
    issue_id: str
    source_id: str
    source_version: int
    severity: str  # BLOCKER | HIGH | MEDIUM | LOW
    error_type: str
    description: str
    location: Optional[str] = None  # JSON string: {"page": 5, "question": "Q3"}
    evidence: Optional[str] = None
    assignee_code: Optional[str] = None
    deadline: Optional[str] = None
    resolved_at: Optional[str] = None
    resolution: Optional[str] = None
    status: str = STATUS_OPEN
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "severity": self.severity,
            "error_type": self.error_type,
            "location": self.location,
            "description": self.description,
            "evidence": self.evidence,
            "assignee_code": self.assignee_code,
            "deadline": self.deadline,
            "resolved_at": self.resolved_at,
            "resolution": self.resolution,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class IssueTracker:
    """Quản lý phiếu lỗi cho dataset sources (SOP §9.3).

    Phiếu lỗi gồm: issue_id, source_id, phiên bản, vị trí trang/slide/câu,
    loại lỗi, mức độ, mô tả, người nhận, hạn sửa và bằng chứng.
    """

    def __init__(self, db: Database):
        self.db = db

    def create_issue(
        self,
        source_id: str,
        source_version: int,
        severity: str,
        error_type: str,
        description: str,
        location: Optional[Dict[str, Any]] = None,
        evidence: Optional[str] = None,
        assignee_code: Optional[str] = None,
        deadline: Optional[str] = None,
    ) -> str:
        """Tạo phiếu lỗi mới. Trả về issue_id.

        Args:
            source_id: ID nguồn dữ liệu
            source_version: Phiên bản nguồn
            severity: Mức độ (BLOCKER/HIGH/MEDIUM/LOW)
            error_type: Loại lỗi (PII/WRONG_ANSWER/FORMULA_ERROR/...)
            description: Mô tả lỗi
            location: Vị trí (page, slide, question_number) dưới dạng dict
            evidence: Bằng chứng kiểm tra
            assignee_code: Mã người nhận
            deadline: Hạn sửa (ISO format)
        """
        if severity not in ALL_SEVERITIES:
            raise ValueError(f"severity không hợp lệ: {severity}")

        issue_id = f"ISSUE_{uuid.uuid4().hex[:12].upper()}"
        now = _now()
        location_str = _serialize_location(location)

        self.db.execute(
            "INSERT INTO source_issues "
            "(issue_id, source_id, source_version, severity, error_type, "
            " location, description, evidence, assignee_code, deadline, "
            " status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                issue_id, source_id, source_version, severity, error_type,
                location_str, description, evidence, assignee_code, deadline,
                STATUS_OPEN, now, now,
            ),
        )
        return issue_id

    def get_issue(self, issue_id: str) -> Optional[SourceIssue]:
        """Lấy thông tin phiếu lỗi."""
        row = self.db.query_one(
            "SELECT * FROM source_issues WHERE issue_id=?",
            (issue_id,),
        )
        if row is None:
            return None
        return self._row_to_issue(row)

    def list_issues(
        self,
        source_id: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> List[SourceIssue]:
        """Lấy danh sách phiếu lỗi (có thể lọc)."""
        query = "SELECT * FROM source_issues WHERE 1=1"
        params: List[Any] = []

        if source_id:
            query += " AND source_id=?"
            params.append(source_id)
        if severity:
            query += " AND severity=?"
            params.append(severity)
        if status:
            query += " AND status=?"
            params.append(status)
        if error_type:
            query += " AND error_type=?"
            params.append(error_type)

        query += " ORDER BY severity DESC, created_at DESC"

        rows = self.db.query(query, params)
        return [self._row_to_issue(row) for row in rows]

    def list_issues_for_source(self, source_id: str) -> List[SourceIssue]:
        """Lấy tất cả issue cho một source."""
        return self.list_issues(source_id=source_id)

    def update_issue(
        self,
        issue_id: str,
        status: Optional[str] = None,
        resolution: Optional[str] = None,
        assignee_code: Optional[str] = None,
    ) -> bool:
        """Cập nhật trạng thái issue. Trả về True nếu cập nhật thành công."""
        if status and status not in ALL_STATUSES:
            raise ValueError(f"status không hợp lệ: {status}")

        now = _now()
        fields = []
        params: List[Any] = []

        if status:
            fields.append("status=?")
            params.append(status)
            if status == STATUS_RESOLVED and resolution:
                fields.append("resolved_at=?")
                params.append(now)
        if resolution:
            fields.append("resolution=?")
            params.append(resolution)
        if assignee_code:
            fields.append("assignee_code=?")
            params.append(assignee_code)

        fields.append("updated_at=?")
        params.append(now)

        if not fields:
            return False

        params.append(issue_id)
        # Verify issue exists before update
        existing = self.db.query_one(
            "SELECT issue_id FROM source_issues WHERE issue_id=?",
            (issue_id,),
        )
        if existing is None:
            return False
        
        self.db.execute(
            f"UPDATE source_issues SET {', '.join(fields)} WHERE issue_id=?",
            tuple(params),
        )
        return True

    def resolve_issue(self, issue_id: str, resolution: str) -> bool:
        """Đánh dấu issue đã được giải quyết."""
        return self.update_issue(
            issue_id, status=STATUS_RESOLVED, resolution=resolution
        )

    def count_blockers(self, source_id: str) -> int:
        """Đếm số lượng BLOCKER issues chưa giải quyết cho một source."""
        result = self.db.query_one(
            "SELECT COUNT(*) as cnt FROM source_issues "
            "WHERE source_id=? AND severity=? AND status != ?",
            (source_id, SEVERITY_BLOCKER, STATUS_RESOLVED),
        )
        return result["cnt"] if result else 0

    def has_blockers(self, source_id: str) -> bool:
        """Kiểm tra source có blocker issue chưa giải quyết không."""
        return self.count_blockers(source_id) > 0

    def _row_to_issue(self, row: Any) -> SourceIssue:
        return SourceIssue(
            issue_id=row["issue_id"],
            source_id=row["source_id"],
            source_version=row["source_version"],
            severity=row["severity"],
            error_type=row["error_type"],
            location=row["location"],
            description=row["description"],
            evidence=row["evidence"],
            assignee_code=row["assignee_code"],
            deadline=row["deadline"],
            resolved_at=row["resolved_at"],
            resolution=row["resolution"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _serialize_location(location: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serialize location dict thành JSON string."""
    if location is None:
        return None
    import json
    return json.dumps(location, ensure_ascii=False, sort_keys=True)


def parse_location(location_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse location JSON string thành dict."""
    if not location_str:
        return None
    import json
    try:
        return json.loads(location_str)
    except (json.JSONDecodeError, TypeError):
        return None


__all__ = [
    "IssueTracker",
    "SourceIssue",
    "SEVERITY_BLOCKER",
    "SEVERITY_HIGH",
    "SEVERITY_MEDIUM",
    "SEVERITY_LOW",
    "STATUS_OPEN",
    "STATUS_IN_PROGRESS",
    "STATUS_RESOLVED",
    "STATUS_WONT_FIX",
    "ERROR_TYPE_PII",
    "ERROR_TYPE_WRONG_ANSWER",
    "ERROR_TYPE_MISSING_CONTEXT",
    "ERROR_TYPE_FORMULA_ERROR",
    "ERROR_TYPE_SOURCE_CONDITION",
    "ERROR_TYPE_TEST_LEAK",
    "ERROR_TYPE_LOST_SOURCE_LINK",
    "parse_location",
]
