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
    # version 4: nguon dataset (SOP §2.1) — source_id la danh tinh chuan, phien ban +
    # lich su trang thai + danh sach file theo SHA-256. Append-only, khong cham bang cu.
    """
    CREATE TABLE sources(
      source_id TEXT PRIMARY KEY,
      subject TEXT NOT NULL,
      grade INTEGER NOT NULL,
      document_type TEXT NOT NULL,
      curriculum_reference TEXT,
      language TEXT NOT NULL,
      title TEXT NOT NULL,
      publisher TEXT,
      source_url TEXT,
      retrieved_at TEXT NOT NULL,
      publication_year INTEGER,
      revision_date TEXT,
      school_year TEXT,
      year_evidence TEXT NOT NULL,
      rights_status TEXT NOT NULL,
      allowed_uses TEXT,
      pii_status TEXT NOT NULL,
      review_status TEXT NOT NULL,
      status TEXT NOT NULL,
      topic TEXT,
      source_version INTEGER NOT NULL DEFAULT 1,
      content_hash TEXT NOT NULL,
      schema_version TEXT NOT NULL,
      owner_code TEXT,
      reviewer_code TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE source_events(
      event_id TEXT PRIMARY KEY,
      source_id TEXT NOT NULL REFERENCES sources(source_id),
      from_status TEXT,
      to_status TEXT NOT NULL,
      reason_code TEXT,
      note TEXT,
      actor_role TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE source_files(
      file_id TEXT PRIMARY KEY,
      source_id TEXT NOT NULL REFERENCES sources(source_id),
      sha256 TEXT NOT NULL,
      rel_path TEXT NOT NULL,
      kind TEXT,
      size_bytes INTEGER,
      created_at TEXT NOT NULL
    );
    CREATE INDEX idx_sources_content_hash ON sources(content_hash);
    CREATE INDEX idx_source_files_sha256 ON source_files(sha256);
    CREATE INDEX idx_source_events_source ON source_events(source_id);
    """,
    # version 5: review workflow (GĐ4) — source_review_events cho quyet dinh duyet
    """
    CREATE TABLE source_review_events(
        decision_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        decision TEXT NOT NULL,  -- APPROVED | RETURNED | HOLD | REJECTED
        reason_code TEXT,
        note TEXT,
        actor_role TEXT NOT NULL,
        actor_code TEXT NOT NULL,
        previous_status TEXT NOT NULL,
        new_status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_source_review_events_source ON source_review_events(source_id);
    CREATE INDEX idx_source_review_events_created ON source_review_events(created_at);
    """,
    # version 6: source issues (SOP §9.3) — phiếu lỗi chi tiết cho phát hành
    """
    CREATE TABLE source_issues(
        issue_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        source_version INTEGER NOT NULL,
        severity TEXT NOT NULL,  -- BLOCKER | HIGH | MEDIUM | LOW
        error_type TEXT NOT NULL,
        location TEXT,  -- page/slide/câu (JSON)
        description TEXT NOT NULL,
        evidence TEXT,
        assignee_code TEXT,
        deadline TEXT,
        resolved_at TEXT,
        resolution TEXT,
        status TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | resolved | wont_fix
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_source_issues_source ON source_issues(source_id);
    CREATE INDEX idx_source_issues_status ON source_issues(status);
    CREATE INDEX idx_source_issues_severity ON source_issues(severity);
    """
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

    def executemany_commit_guarded(
        self, guard: tuple[str, tuple], statements: list[tuple[str, tuple]]
    ) -> int:
        """Transaction có guard CAS (compare-and-swap) — dùng cho transition trạng thái.

        - guard phải là UPDATE ảnh hưởng ĐÚNG 1 dòng (`WHERE ... AND status=?`).
          Không khớp (đã bị chuyển bởi thread khác / id không tồn tại) → rollback,
          KHÔNG ghi gì, trả về rowcount (0).
        - Khớp 1 dòng → chạy tiếp `statements` (ghi event...) TRONG CÙNG transaction.
        """
        with self._lock:
            try:
                cur = self._conn.execute(guard[0], guard[1])
                if cur.rowcount != 1:
                    self._conn.rollback()
                    return cur.rowcount
                for sql, params in statements:
                    self._conn.execute(sql, params)
                self._conn.commit()
                return cur.rowcount
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
