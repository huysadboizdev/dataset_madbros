from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

MIGRATIONS: list[str] = [
    # version 1
    """
    CREATE TABLE documents(
      document_id TEXT PRIMARY KEY,
      hash TEXT NOT NULL UNIQUE,
      raw_path TEXT NOT NULL,
      original_name TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      page_count INTEGER NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      ingested_at TEXT NOT NULL
    );
    CREATE TABLE jobs(
      job_id TEXT PRIMARY KEY,
      document_id TEXT NOT NULL REFERENCES documents(document_id),
      selected_pages_json TEXT NOT NULL,
      pages_fingerprint TEXT NOT NULL,
      mode TEXT NOT NULL,
      ocr_again INTEGER NOT NULL DEFAULT 0,
      config_hash TEXT NOT NULL,
      status TEXT NOT NULL,
      notes_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT
    );
    CREATE TABLE page_runs(
      job_id TEXT NOT NULL REFERENCES jobs(job_id),
      page_no INTEGER NOT NULL,
      status TEXT NOT NULL,
      method TEXT NOT NULL DEFAULT 'unknown',
      attempt INTEGER NOT NULL DEFAULT 0,
      duration_s REAL,
      error TEXT,
      active_revision_id TEXT,
      review_status TEXT NOT NULL DEFAULT 'unreviewed',
      PRIMARY KEY(job_id, page_no)
    );
    CREATE TABLE revisions(
      revision_id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      page_no INTEGER NOT NULL,
      parent_revision TEXT,
      kind TEXT NOT NULL,
      origin TEXT NOT NULL,
      content_path TEXT NOT NULL,
      hash TEXT NOT NULL,
      created_at TEXT NOT NULL,
      edited_at TEXT
    );
    CREATE TABLE issues(
      issue_id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      page_no INTEGER NOT NULL,
      block_id TEXT,
      type TEXT NOT NULL,
      description TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open'
    );
    CREATE TABLE exports(
      export_id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      format TEXT NOT NULL,
      revision_map_json TEXT NOT NULL,
      included_pages_json TEXT NOT NULL,
      missing_pages_json TEXT NOT NULL,
      artifact_path TEXT NOT NULL,
      checksum TEXT,
      created_at TEXT NOT NULL
    );
    """,
    # version 2: phep resolve/dong issue co ly do + giu lich su (khong xoa)
    """
    ALTER TABLE issues ADD COLUMN resolved_at TEXT;
    ALTER TABLE issues ADD COLUMN resolved_reason TEXT;
    ALTER TABLE issues ADD COLUMN checked_revision TEXT;
    """,
    # version 3: gan resolution voi NOI DUNG da kiem (fingerprint) de khong tu ke thua
    # xac nhan chuyen mon sang noi dung Da DOI o revision moi.
    """
    ALTER TABLE issues ADD COLUMN content_fp TEXT;
    """,
]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        cur = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(cur, len(MIGRATIONS)):
            with self._lock:
                self._conn.executescript(MIGRATIONS[version])
                self._conn.execute(f"PRAGMA user_version={version + 1}")
                self._conn.commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def executemany_commit(self, statements: list[tuple[str, tuple]]) -> None:
        """Transaction nhiều câu: parent là nơi duy nhất ghi."""
        with self._lock:
            try:
                for sql, params in statements:
                    self._conn.execute(sql, params)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ------- helpers used by services -------

    def get_document(self, document_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM documents WHERE document_id=?", (document_id,))

    def get_document_by_hash(self, hash_: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM documents WHERE hash=?", (hash_,))

    def get_job(self, job_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))

    def running_job(self) -> Optional[sqlite3.Row]:
        return self.query_one(
            "SELECT * FROM jobs WHERE status IN ('RUNNING','PAUSE_REQUESTED') ORDER BY created_at LIMIT 1"
        )

    def list_page_runs(self, job_id: str) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM page_runs WHERE job_id=? ORDER BY page_no", (job_id,))

    def set_job_status(self, job_id: str, status: str, finished: bool = False) -> None:
        if finished:
            self.execute("UPDATE jobs SET status=?, finished_at=? WHERE job_id=?",
                         (status, _now(), job_id))
        else:
            self.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))

    def insert_revision(self, revision_id: str, job_id: str, page_no: int,
                        parent_revision: Optional[str], kind: str, origin: str,
                        content_path: str, hash_: str) -> None:
        self.execute(
            "INSERT INTO revisions(revision_id, job_id, page_no, parent_revision, kind, origin,"
            " content_path, hash, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (revision_id, job_id, page_no, parent_revision, kind, origin,
             content_path, hash_, _now()),
        )

    def get_revision(self, revision_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM revisions WHERE revision_id=?", (revision_id,))

    def replace_issues(self, job_id: str, page_no: int, issues: list[dict]) -> None:
        stmts: list[tuple[str, tuple]] = [
            ("DELETE FROM issues WHERE job_id=? AND page_no=?", (job_id, page_no))
        ]
        for it in issues:
            stmts.append((
                "INSERT INTO issues(issue_id, job_id, page_no, block_id, type, description, status)"
                " VALUES(?,?,?,?,?,?,?)",
                (it["issue_id"], job_id, page_no, it.get("block_id"), it["type"],
                 it["description"], it.get("status", "open")),
            ))
        self.executemany_commit(stmts)
