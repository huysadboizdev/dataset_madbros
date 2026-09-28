from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from backend.app.db import Database, MIGRATIONS
from backend.app.dataset.registry import DuplicateSourceError, SourceRegistry
from backend.app.dataset.source_id import make_source_id
from backend.app.settings import Settings

# ---------------- Task 1.1: migration v4 ----------------


def test_migrations_append_only_structure():
    assert len(MIGRATIONS) == 6
    assert "CREATE TABLE documents" in MIGRATIONS[0]
    assert "ALTER TABLE issues ADD COLUMN resolved_at" in MIGRATIONS[1]
    assert "ALTER TABLE issues ADD COLUMN content_fp" in MIGRATIONS[2]
    assert "CREATE TABLE sources" in MIGRATIONS[3]
    assert "CREATE TABLE source_events" in MIGRATIONS[3]
    assert "CREATE TABLE source_files" in MIGRATIONS[3]
    assert "CREATE TABLE source_review_events" in MIGRATIONS[4]
    assert "idx_source_review_events_source" in MIGRATIONS[4]
    assert "CREATE TABLE source_issues" in MIGRATIONS[5]
    assert "idx_source_issues_source" in MIGRATIONS[5]
    assert "idx_source_issues_severity" in MIGRATIONS[5]


def test_migrate_v3_to_v4_keeps_data(tmp_path):
    path = tmp_path / "app.db"
    conn = sqlite3.connect(str(path))
    for m in MIGRATIONS[:3]:
        conn.executescript(m)
    conn.execute("PRAGMA user_version=3")
    conn.execute(
        "INSERT INTO documents(document_id, hash, raw_path, original_name, size_bytes,"
        " page_count, metadata_json, ingested_at) VALUES(?,?,?,?,?,?,?,?)",
        ("doc1", "hash1", "raw/a.pdf", "a.pdf", 10, 1, "{}", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    db = Database(path)  # migrate 3 → 4 → 5 → 6
    assert db.query_one("PRAGMA user_version")[0] == 6
    row = db.get_document("doc1")
    assert row is not None and row["original_name"] == "a.pdf"
    tables = {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "jobs", "page_runs", "revisions", "issues", "exports"} <= tables
    assert {"sources", "source_events", "source_files", "source_review_events"} <= tables


def test_fresh_db_created_at_v4(tmp_path):
    db = Database(tmp_path / "fresh.db")
    assert db.query_one("PRAGMA user_version")[0] == 6
    tables = {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sources", "source_events", "source_files", "source_review_events"} <= tables


# ---------------- Task 1.7: registry + manifest ----------------


def _settings(tmp_path) -> Settings:
    s = Settings(project_root=tmp_path)
    s.ensure_dirs()
    return s


def _meta(source_id: str, payload: bytes, **over) -> dict:
    d = {
        "source_id": source_id,
        "source_version": 1,
        "content_hash": hashlib.sha256(payload).hexdigest(),
        "schema_version": "source_metadata/1",
        "subject": "MATH",
        "grade": 10,
        "document_type": "textbook",
        "language": "vi",
        "title": "Toan 10 tap mot",
        "retrieved_at": "2026-09-25",
        "publication_year": 2026,
        "year_evidence": "Ban cong bo 2026, xac minh duoc.",
        "rights_status": "granted",
        "pii_status": "clean",
        "review_status": "unreviewed",
        "explanation_origin": "source",
    }
    d.update(over)
    return d


def test_create_source_and_manifest(tmp_path):
    from backend.app.dataset.metadata import SourceMetadata

    s = _settings(tmp_path)
    db = Database(s.data_dir / "app.db")
    reg = SourceRegistry(db, s)
    payload = b"%PDF-1.4 fake raw v1"
    sid = make_source_id("MATH", 10, 2026, 1)
    meta = SourceMetadata.model_validate(_meta(sid, payload))
    got = reg.create_source(meta, raw_bytes=payload)
    assert got == sid

    row = reg.get_source(sid)
    assert row["source_id"] == sid
    assert row["status"] == "NEW"
    assert row["content_hash"] == hashlib.sha256(payload).hexdigest()
    assert row["source_version"] == 1

    manifest = reg.build_manifest(sid)
    assert manifest["schema_version"] == "dataset_manifest/1"
    assert manifest["source_id"] == sid
    assert manifest["content_hash"] == hashlib.sha256(payload).hexdigest()
    assert manifest["status"] == "NEW"
    assert manifest["version_history"] and manifest["version_history"][0]["source_version"] == 1
    assert "issues" in manifest
    assert manifest["files"] and manifest["files"][0]["sha256"] == hashlib.sha256(payload).hexdigest()

    # checksum SHA-256 cua manifest phai xac minh duoc
    body = {k: v for k, v in manifest.items() if k != "checksum"}
    expect = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert manifest["checksum"] == expect

    # artifact khong duoc chua duong dan tuyet doi / username
    text = json.dumps(manifest, ensure_ascii=False)
    assert "C:\\" not in text and "/Users/" not in text and "\\\\users\\\\" not in text.lower()

    p = reg.write_manifest(sid)
    assert p.is_file()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["checksum"] == manifest["checksum"]


def test_duplicate_content_not_two_documents(tmp_path):
    from backend.app.dataset.metadata import SourceMetadata

    s = _settings(tmp_path)
    db = Database(s.data_dir / "app.db")
    reg = SourceRegistry(db, s)
    payload = b"%PDF-1.4 same bytes from 2 websites"
    sid1 = make_source_id("MATH", 10, 2026, 1)
    sid2 = make_source_id("MATH", 10, 2026, 2)
    reg.create_source(SourceMetadata.model_validate(_meta(sid1, payload)), raw_bytes=payload)
    with pytest.raises(DuplicateSourceError):
        reg.create_source(SourceMetadata.model_validate(_meta(sid2, payload)), raw_bytes=payload)
    assert reg.get_source(sid2) is None
    rows = db.query("SELECT source_id FROM sources")
    assert len(rows) == 1


def test_update_content_bumps_version_keeps_id(tmp_path):
    from backend.app.dataset.metadata import SourceMetadata

    s = _settings(tmp_path)
    db = Database(s.data_dir / "app.db")
    reg = SourceRegistry(db, s)
    v1 = b"%PDF-1.4 content v1"
    v2 = b"%PDF-1.4 content v2 changed"
    sid = make_source_id("ENG", 11, 2025, 5)
    meta = SourceMetadata.model_validate(
        _meta(sid, v1, subject="ENG", grade=11, publication_year=2025)
    )
    reg.create_source(meta, raw_bytes=v1)

    # cung noi dung → khong tang version
    same = reg.update_content(sid, v1)
    assert same["source_version"] == 1

    # doi noi dung → tang version, GIU NGUYEN source_id
    out = reg.update_content(sid, v2, note="sua loi OCR trang 12")
    assert out["source_version"] == 2
    assert out["source_id"] == sid
    row = reg.get_source(sid)
    assert row["source_version"] == 2
    assert row["source_id"] == sid
    assert row["content_hash"] == hashlib.sha256(v2).hexdigest()

    manifest = reg.build_manifest(sid)
    assert [h["source_version"] for h in manifest["version_history"]] == [1, 2]
    assert len(manifest["files"]) == 2
