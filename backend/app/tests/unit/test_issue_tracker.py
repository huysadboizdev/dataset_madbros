"""Unit tests cho issue tracking module (SOP §9.3)."""
from __future__ import annotations

import sqlite3
import pytest

from backend.app.db import Database, MIGRATIONS
from backend.app.dataset.issue_tracker import (
    IssueTracker,
    SEVERITY_BLOCKER,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
    STATUS_WONT_FIX,
    ERROR_TYPE_PII,
    ERROR_TYPE_WRONG_ANSWER,
    ERROR_TYPE_FORMULA_ERROR,
)


def _make_db(tmp_path) -> Database:
    path = tmp_path / "app.db"
    db = Database(path)
    # Insert a minimal source to test issue tracking
    db.execute(
        "INSERT INTO sources (source_id, subject, grade, document_type, language, "
        "title, retrieved_at, year_evidence, rights_status, pii_status, review_status, "
        "status, source_version, content_hash, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("MATH_G10_2026_0001", "MATH", 10, "textbook", "vi",
         "Test Book", "2026-01-01", "2026-01-01", "OPEN", "CLEAN", "APPROVED",
         "APPROVED", 1, "abc123", "v1", "2026-01-01", "2026-01-01"),
    )
    return db


class TestIssueTracker:
    def test_create_issue_success(self, tmp_path):
        """Tạo phiếu lỗi thành công."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="Có thông tin cá nhân trong tài liệu",
        )
        assert issue_id.startswith("ISSUE_")
        assert len(issue_id) > 10

    def test_create_issue_with_location(self, tmp_path):
        """Tạo issue kèm vị trí trang/câu."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_HIGH,
            error_type=ERROR_TYPE_WRONG_ANSWER,
            description="Đáp án sai ở câu 5",
            location={"page": 12, "question": "Q5"},
            evidence="So sánh với bản gốc trang 12",
        )
        issue = tracker.get_issue(issue_id)
        assert issue is not None
        assert issue.location is not None
        assert "page" in issue.location

    def test_invalid_severity_raises(self, tmp_path):
        """Mức độ lỗi không hợp lệ → ValueError."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        with pytest.raises(ValueError, match="severity"):
            tracker.create_issue(
                source_id="MATH_G10_2026_0001",
                source_version=1,
                severity="INVALID",
                error_type=ERROR_TYPE_PII,
                description="Test",
            )

    def test_get_issue_not_found(self, tmp_path):
        """Lấy issue không tồn tại → None."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        assert tracker.get_issue("ISSUE_NONEXISTENT123") is None

    def test_list_issues_by_source(self, tmp_path):
        """Liệt kê issues theo source_id."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="PII issue 1",
        )
        tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_HIGH,
            error_type=ERROR_TYPE_WRONG_ANSWER,
            description="Wrong answer issue",
        )
        issues = tracker.list_issues(source_id="MATH_G10_2026_0001")
        assert len(issues) == 2

    def test_list_issues_by_severity(self, tmp_path):
        """Lọc issues theo severity."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="Blocker issue",
        )
        tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_LOW,
            error_type=ERROR_TYPE_PII,
            description="Low issue",
        )
        blockers = tracker.list_issues(severity=SEVERITY_BLOCKER)
        assert len(blockers) == 1
        assert blockers[0].severity == SEVERITY_BLOCKER

    def test_list_issues_by_status(self, tmp_path):
        """Lọc issues theo status."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_MEDIUM,
            error_type=ERROR_TYPE_PII,
            description="Medium issue",
        )
        # Default status is open
        open_issues = tracker.list_issues(status=STATUS_OPEN)
        assert len(open_issues) == 1

        # Update to resolved
        tracker.resolve_issue(issue_id, "Fixed by removing PII")
        resolved = tracker.list_issues(status=STATUS_RESOLVED)
        assert len(resolved) == 1

    def test_update_issue_status(self, tmp_path):
        """Cập nhật trạng thái issue."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_MEDIUM,
            error_type=ERROR_TYPE_PII,
            description="Issue to update",
        )
        updated = tracker.update_issue(
            issue_id,
            status=STATUS_IN_PROGRESS,
            assignee_code="cleaner_01",
        )
        assert updated
        issue = tracker.get_issue(issue_id)
        assert issue.status == STATUS_IN_PROGRESS
        assert issue.assignee_code == "cleaner_01"

    def test_resolve_issue(self, tmp_path):
        """Đánh dấu issue đã giải quyết với resolution."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="PII issue to resolve",
        )
        tracker.resolve_issue(issue_id, "Removed PII from page 5")
        issue = tracker.get_issue(issue_id)
        assert issue.status == STATUS_RESOLVED
        assert issue.resolved_at is not None
        assert issue.resolution == "Removed PII from page 5"

    def test_has_blockers_true(self, tmp_path):
        """Source có blocker issue chưa giải quyết → has_blockers = True."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="Blocker PII issue",
        )
        assert tracker.has_blockers("MATH_G10_2026_0001") is True
        assert tracker.count_blockers("MATH_G10_2026_0001") == 1

    def test_has_blockers_false_after_resolve(self, tmp_path):
        """Sau khi resolve blocker → has_blockers = False."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_BLOCKER,
            error_type=ERROR_TYPE_PII,
            description="Blocker to resolve",
        )
        tracker.resolve_issue(issue_id, "Fixed")
        assert tracker.has_blockers("MATH_G10_2026_0001") is False
        assert tracker.count_blockers("MATH_G10_2026_0001") == 0

    def test_has_blockers_false_no_issues(self, tmp_path):
        """Source không có issues → has_blockers = False."""
        db = _make_db(tmp_path)
        db.execute(
            "INSERT INTO sources (source_id, subject, grade, document_type, language, "
            "title, retrieved_at, year_evidence, rights_status, pii_status, review_status, "
            "status, source_version, content_hash, schema_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("ENG_G11_2026_0002", "ENG", 11, "textbook", "en",
             "Test Book 2", "2026-01-01", "2026-01-01", "OPEN", "CLEAN", "APPROVED",
             "APPROVED", 1, "def456", "v1", "2026-01-01", "2026-01-01"),
        )
        tracker = IssueTracker(db)
        assert tracker.has_blockers("ENG_G11_2026_0002") is False
        assert tracker.count_blockers("ENG_G11_2026_0002") == 0

    def test_to_dict_roundtrip(self, tmp_path):
        """Issue.to_dict() chứa đầy đủ trường."""
        db = _make_db(tmp_path)
        tracker = IssueTracker(db)
        issue_id = tracker.create_issue(
            source_id="MATH_G10_2026_0001",
            source_version=1,
            severity=SEVERITY_HIGH,
            error_type=ERROR_TYPE_FORMULA_ERROR,
            description="Công thức LaTeX sai",
            location={"page": 7, "formula_index": 2},
            evidence="So sánh với bản gốc",
            assignee_code="reviewer_01",
            deadline="2026-10-05",
        )
        issue = tracker.get_issue(issue_id)
        d = issue.to_dict()
        assert d["issue_id"] == issue_id
        assert d["severity"] == SEVERITY_HIGH
        assert d["error_type"] == ERROR_TYPE_FORMULA_ERROR
        assert d["assignee_code"] == "reviewer_01"
        assert d["status"] == STATUS_OPEN

    def test_migration_v6_applied(self, tmp_path):
        """Migration v6 tạo bảng source_issues."""
        db = _make_db(tmp_path)
        rows = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_issues'"
        )
        assert len(rows) == 1
