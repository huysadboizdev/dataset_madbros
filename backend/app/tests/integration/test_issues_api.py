"""Integration tests cho issues API (SOP §9.3)."""
from __future__ import annotations

import json
import pytest


def _create_source_directly(client, source_id="MATH_G10_2026_0001"):
    """Helper: tạo source trực tiếp trong DB (bypass API validation)."""
    from backend.app.db import Database
    db = client.app.state.db
    
    content_hash = "a" * 64  # SHA-256 hex 64 ký tự
    db.execute(
        "INSERT INTO sources (source_id, subject, grade, document_type, language, "
        "title, retrieved_at, year_evidence, rights_status, pii_status, review_status, "
        "status, source_version, content_hash, schema_version, owner_code, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source_id, "MATH", 10, "textbook", "vi",
         f"Test {source_id}", "2026-09-25", "published", "granted", "CLEAN", "APPROVED",
         "APPROVED", 1, content_hash, "source_metadata/1", "test_01",
         "2026-09-25", "2026-09-25"),
    )


class TestIssuesAPI:
    def test_create_and_get_issue(self, client):
        """POST /api/issues → tạo issue, GET lấy lại."""
        _create_source_directly(client)
        
        r = client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "BLOCKER",
            "error_type": "PII",
            "description": "Có thông tin cá nhân trong tài liệu",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["issue_id"].startswith("ISSUE_")
        assert body["status"] == "created"
        
        # Get issue
        issue_id = body["issue_id"]
        r2 = client.get(f"/api/issues/{issue_id}")
        assert r2.status_code == 200
        issue = r2.json()["issue"]
        assert issue["source_id"] == "MATH_G10_2026_0001"
        assert issue["severity"] == "BLOCKER"
        assert issue["status"] == "open"

    def test_get_issue_not_found(self, client):
        """GET /api/issues/{invalid_id} → 404."""
        r = client.get("/api/issues/ISSUE_NONEXISTENT000000")
        assert r.status_code == 404
        # Response format tùy theo HTTPException
        assert "ISSUE_NOT_FOUND" in r.text

    def test_list_issues_by_source(self, client):
        """GET /api/issues?source_id=... → liệt kê."""
        _create_source_directly(client)
        
        client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "BLOCKER",
            "error_type": "PII",
            "description": "Blocker issue 1",
        })
        client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "HIGH",
            "error_type": "WRONG_ANSWER",
            "description": "Wrong answer issue 2",
        })
        
        r = client.get("/api/issues?source_id=MATH_G10_2026_0001")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert len(body["issues"]) == 2

    def test_list_issues_by_severity(self, client):
        """GET /api/issues?severity=HIGH → lọc theo severity."""
        _create_source_directly(client)
        
        client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "HIGH",
            "error_type": "PII",
            "description": "High severity issue",
        })
        
        r = client.get("/api/issues?severity=HIGH")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1

    def test_update_issue_status(self, client):
        """PATCH /api/issues/{id} → cập nhật trạng thái."""
        _create_source_directly(client)
        
        r = client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "MEDIUM",
            "error_type": "FORMULA_ERROR",
            "description": "Công thức sai",
        })
        issue_id = r.json()["issue_id"]
        
        r2 = client.patch(f"/api/issues/{issue_id}", json={
            "status": "in_progress",
            "assignee_code": "cleaner_01",
        })
        assert r2.status_code == 200
        assert r2.json()["updated"] is True
        
        # Verify
        r3 = client.get(f"/api/issues/{issue_id}")
        issue = r3.json()["issue"]
        assert issue["status"] == "in_progress"
        assert issue["assignee_code"] == "cleaner_01"

    def test_resolve_issue(self, client):
        """PATCH để resolve issue."""
        _create_source_directly(client)
        
        r = client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "BLOCKER",
            "error_type": "PII",
            "description": "PII issue that needs to be resolved from document",
        })
        issue_id = r.json()["issue_id"]

        client.patch(f"/api/issues/{issue_id}", json={
            "status": "resolved",
            "resolution": "Removed PII from document",
        })
        
        r3 = client.get(f"/api/issues/{issue_id}")
        issue = r3.json()["issue"]
        assert issue["status"] == "resolved"
        assert issue["resolved_at"] is not None

    def test_blockers_check(self, client):
        """GET /api/issues/sources/{id}/blockers → kiểm tra blockers."""
        _create_source_directly(client)
        
        # Initially no blockers
        r = client.get("/api/issues/sources/MATH_G10_2026_0001/blockers")
        assert r.status_code == 200
        body = r.json()
        assert body["has_blockers"] is False
        assert body["blocker_count"] == 0
        
        # Add a blocker
        client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "BLOCKER",
            "error_type": "PII",
            "description": "Blocker issue",
        })
        
        r = client.get("/api/issues/sources/MATH_G10_2026_0001/blockers")
        body = r.json()
        assert body["has_blockers"] is True
        assert body["blocker_count"] == 1

    def test_create_issue_invalid_severity(self, client):
        """POST issue với severity không hợp lệ → 422."""
        _create_source_directly(client)
        
        r = client.post("/api/issues", json={
            "source_id": "MATH_G10_2026_0001",
            "source_version": 1,
            "severity": "INVALID",
            "error_type": "PII",
            "description": "Test invalid severity",
        })
        assert r.status_code == 422

    def test_create_issue_missing_source(self, client):
        """POST issue cho source không tồn tại → FOREIGN KEY constraint lỗi."""
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            client.post("/api/issues", json={
                "source_id": "MATH_G10_2026_9999",
                "source_version": 1,
                "severity": "BLOCKER",
                "error_type": "PII",
                "description": "Issue for non-existent source with enough words here",
            })
