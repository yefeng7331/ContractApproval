"""Durable parse-job registration, exclusive claim, and expired-lease recovery."""

from __future__ import annotations

import uuid
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from backend.auth import AuthStore


@dataclass(frozen=True)
class JobLease:
    task_id: str
    document_version: int
    attempt: int
    lease_token: str
    file_path: str
    sha256: str


class JobStore:
    def __init__(self, auth_store: AuthStore, clock: Callable[[], datetime] | None = None) -> None:
        self.auth_store = auth_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    def initialize(self) -> None:
        with self.auth_store.lock, self.auth_store.connection:
            self.auth_store.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    stage TEXT NOT NULL CHECK (stage = 'parse'),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'blocked', 'superseded')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, document_version, stage),
                    FOREIGN KEY (task_id, document_version)
                        REFERENCES document_versions(task_id, version)
                );
                CREATE TABLE IF NOT EXISTS processing_attempts (
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    claimed_at TEXT NOT NULL,
                    finished_at TEXT,
                    outcome TEXT NOT NULL CHECK (outcome IN ('running', 'lease_expired', 'superseded', 'completed', 'blocked')),
                    PRIMARY KEY (task_id, document_version, stage, attempt),
                    FOREIGN KEY (task_id, document_version, stage)
                        REFERENCES processing_jobs(task_id, document_version, stage)
                );
                CREATE TABLE IF NOT EXISTS parsed_documents (
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    normalized_text TEXT NOT NULL,
                    paragraphs_json TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    clauses_json TEXT NOT NULL,
                    missing_clause_types_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, document_version),
                    FOREIGN KEY (task_id, document_version)
                        REFERENCES document_versions(task_id, version)
                );
                """
            )
            self._migrate_attempt_outcomes()
            now = self._now().isoformat()
            self.auth_store.connection.execute(
                """INSERT OR IGNORE INTO processing_jobs
                (task_id, document_version, stage, status, created_at, updated_at)
                SELECT t.id, t.current_document_version, 'parse', 'pending', t.created_at, ?
                FROM tasks AS t JOIN document_versions AS d
                    ON d.task_id = t.id AND d.version = t.current_document_version
                WHERE t.machine_status = 'pending'""",
                (now,),
            )
        self.recover_expired()

    def _migrate_attempt_outcomes(self) -> None:
        """Preserve pre-existing attempt history while allowing terminal outcomes."""
        connection = self.auth_store.connection
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'processing_attempts'"
        ).fetchone()[0]
        if "'completed'" in definition:
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """CREATE TABLE processing_attempts_v2 (
                    task_id TEXT NOT NULL, document_version INTEGER NOT NULL,
                    stage TEXT NOT NULL, attempt INTEGER NOT NULL,
                    claimed_at TEXT NOT NULL, finished_at TEXT,
                    outcome TEXT NOT NULL CHECK (outcome IN
                        ('running', 'lease_expired', 'superseded', 'completed', 'blocked')),
                    PRIMARY KEY (task_id, document_version, stage, attempt),
                    FOREIGN KEY (task_id, document_version, stage)
                        REFERENCES processing_jobs(task_id, document_version, stage)
                )"""
            )
            connection.execute(
                """INSERT INTO processing_attempts_v2
                SELECT task_id, document_version, stage, attempt, claimed_at, finished_at, outcome
                FROM processing_attempts"""
            )
            original_count = connection.execute("SELECT COUNT(*) FROM processing_attempts").fetchone()[0]
            copied_count = connection.execute("SELECT COUNT(*) FROM processing_attempts_v2").fetchone()[0]
            if original_count != copied_count:
                raise RuntimeError("attempt migration did not preserve every row")
            connection.execute("DROP TABLE processing_attempts")
            connection.execute("ALTER TABLE processing_attempts_v2 RENAME TO processing_attempts")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def enqueue_parse(self, task_id: str, document_version: int, created_at: str) -> None:
        """Called inside the task/document transaction, after document_versions insert."""
        self.auth_store.connection.execute(
            """INSERT INTO processing_jobs
            (task_id, document_version, stage, status, created_at, updated_at)
            VALUES (?, ?, 'parse', 'pending', ?, ?)""",
            (task_id, document_version, created_at, created_at),
        )

    def supersede(self, task_id: str, document_version: int, when: str) -> None:
        """Called inside a successful document-replacement transaction."""
        self.auth_store.connection.execute(
            """UPDATE processing_attempts SET finished_at = ?, outcome = 'superseded'
            WHERE task_id = ? AND document_version = ? AND stage = 'parse'
                AND outcome = 'running'""",
            (when, task_id, document_version),
        )
        self.auth_store.connection.execute(
            """UPDATE processing_jobs SET status = 'superseded', lease_token = NULL,
                lease_expires_at = NULL, updated_at = ?
            WHERE task_id = ? AND document_version = ? AND stage = 'parse'
                AND status IN ('pending', 'running')""",
            (when, task_id, document_version),
        )

    def recover_expired(self) -> int:
        now = self._now().isoformat()
        with self.auth_store.lock:
            connection = self.auth_store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """SELECT task_id, document_version, attempt_count
                    FROM processing_jobs WHERE status = 'running' AND lease_expires_at <= ?""",
                    (now,),
                ).fetchall()
                for row in rows:
                    connection.execute(
                        """UPDATE processing_attempts SET finished_at = ?, outcome = 'lease_expired'
                        WHERE task_id = ? AND document_version = ? AND stage = 'parse'
                            AND attempt = ? AND outcome = 'running'""",
                        (now, row["task_id"], row["document_version"], row["attempt_count"]),
                    )
                    connection.execute(
                        """UPDATE processing_jobs SET status = 'pending', lease_token = NULL,
                            lease_expires_at = NULL, updated_at = ?
                        WHERE task_id = ? AND document_version = ? AND stage = 'parse'""",
                        (now, row["task_id"], row["document_version"]),
                    )
                    connection.execute(
                        """UPDATE tasks SET machine_status = 'pending'
                        WHERE id = ? AND current_document_version = ? AND machine_status = 'parsing'""",
                        (row["task_id"], row["document_version"]),
                    )
                connection.commit()
                return len(rows)
            except BaseException:
                connection.rollback()
                raise

    def claim_next(self, lease_seconds: int = 60, *, file_format: str | None = None) -> JobLease | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.recover_expired()
        now = self._now()
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
        token = uuid.uuid4().hex
        with self.auth_store.lock:
            connection = self.auth_store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                active = connection.execute(
                    """SELECT 1 FROM processing_jobs WHERE status = 'running'
                    AND lease_expires_at > ? LIMIT 1""",
                    (now_text,),
                ).fetchone()
                if active is not None:
                    connection.commit()
                    return None
                row = connection.execute(
                    """SELECT j.task_id, j.document_version, j.attempt_count, d.file_path, d.sha256
                    FROM processing_jobs AS j JOIN tasks AS t ON t.id = j.task_id
                    JOIN document_versions AS d ON d.task_id = j.task_id
                        AND d.version = j.document_version
                    WHERE j.stage = 'parse' AND j.status = 'pending'
                        AND t.current_document_version = j.document_version
                        AND t.machine_status = 'pending'
                        AND (? IS NULL OR d.format = ?)
                    ORDER BY j.created_at, j.task_id LIMIT 1""",
                    (file_format, file_format),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                attempt = row["attempt_count"] + 1
                connection.execute(
                    """UPDATE processing_jobs SET status = 'running', attempt_count = ?,
                        lease_token = ?, lease_expires_at = ?, updated_at = ?
                    WHERE task_id = ? AND document_version = ? AND stage = 'parse'
                        AND status = 'pending'""",
                    (attempt, token, expires_at, now_text, row["task_id"], row["document_version"]),
                )
                connection.execute(
                    """UPDATE tasks SET machine_status = 'parsing', attempt_count = ?
                    WHERE id = ? AND current_document_version = ? AND machine_status = 'pending'""",
                    (attempt, row["task_id"], row["document_version"]),
                )
                connection.execute(
                    """INSERT INTO processing_attempts
                    (task_id, document_version, stage, attempt, claimed_at, outcome)
                    VALUES (?, ?, 'parse', ?, ?, 'running')""",
                    (row["task_id"], row["document_version"], attempt, now_text),
                )
                connection.commit()
                return JobLease(row["task_id"], row["document_version"], attempt, token, row["file_path"], row["sha256"])
            except BaseException:
                connection.rollback()
                raise

    def has_unfinished(self, *, file_format: str) -> bool:
        """Whether a current version is pending or held by an active lease."""
        with self.auth_store.lock:
            return self.auth_store.connection.execute(
                """SELECT 1 FROM processing_jobs AS j
                JOIN tasks AS t ON t.id = j.task_id
                JOIN document_versions AS d ON d.task_id = j.task_id
                    AND d.version = j.document_version
                WHERE j.stage = 'parse'
                    AND t.current_document_version = j.document_version
                    AND d.format = ?
                    AND ((j.status = 'pending' AND t.machine_status = 'pending')
                        OR (j.status = 'running' AND t.machine_status = 'parsing'
                            AND j.lease_expires_at > ?)) LIMIT 1""",
                (file_format, self._now().isoformat()),
            ).fetchone() is not None

    def renew(self, lease: JobLease, lease_seconds: int = 60) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._now()
        with self.auth_store.lock, self.auth_store.connection:
            changed = self.auth_store.connection.execute(
                """UPDATE processing_jobs SET lease_expires_at = ?, updated_at = ?
                WHERE task_id = ? AND document_version = ? AND stage = 'parse'
                    AND status = 'running' AND lease_token = ? AND lease_expires_at > ?""",
                ((now + timedelta(seconds=lease_seconds)).isoformat(), now.isoformat(),
                 lease.task_id, lease.document_version, lease.lease_token, now.isoformat()),
            )
            return changed.rowcount == 1

    def _lease_is_current(self, connection, lease: JobLease, now: str) -> bool:
        return connection.execute(
            """SELECT 1 FROM processing_jobs AS j JOIN tasks AS t ON t.id = j.task_id
            WHERE j.task_id = ? AND j.document_version = ? AND j.stage = 'parse'
                AND j.status = 'running' AND j.attempt_count = ?
                AND j.lease_token = ? AND j.lease_expires_at > ?
                AND t.current_document_version = j.document_version
                AND t.machine_status = 'parsing'""",
            (lease.task_id, lease.document_version, lease.attempt, lease.lease_token, now),
        ).fetchone() is not None

    def complete_docx(self, lease: JobLease, parsed, metadata, clauses) -> bool:
        """Atomically persist same-version evidence and finish an active parse attempt."""
        if parsed.document_version != lease.document_version:
            raise ValueError("parsed document version does not match lease")
        anchors = [*parsed.paragraphs, *clauses.clauses]
        anchors.extend(field.anchor for field in metadata.fields if field.anchor is not None)
        for anchor in anchors:
            if (anchor.document_version != lease.document_version or anchor.start < 0
                    or anchor.end <= anchor.start or anchor.end > len(parsed.normalized_text)
                    or parsed.normalized_text[anchor.start:anchor.end] != anchor.quote):
                raise ValueError("anchor does not match document text and version")
        now = self._now().isoformat()
        with self.auth_store.lock:
            connection = self.auth_store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not self._lease_is_current(connection, lease, now):
                    connection.rollback()
                    return False
                dumps = lambda value: json.dumps(value, ensure_ascii=False)
                connection.execute(
                    """INSERT INTO parsed_documents
                    (task_id, document_version, normalized_text, paragraphs_json,
                     fields_json, clauses_json, missing_clause_types_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (lease.task_id, lease.document_version, parsed.normalized_text,
                     dumps([asdict(item) for item in parsed.paragraphs]),
                     dumps([asdict(item) for item in metadata.fields]),
                     dumps([asdict(item) for item in clauses.clauses]),
                     dumps(clauses.missing_types), now),
                )
                connection.execute(
                    """UPDATE processing_jobs SET status = 'completed', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ? AND document_version = ? AND stage = 'parse'""",
                    (now, lease.task_id, lease.document_version),
                )
                finished = connection.execute(
                    """UPDATE processing_attempts SET outcome = 'completed', finished_at = ?
                    WHERE task_id = ? AND document_version = ? AND stage = 'parse' AND attempt = ?""",
                    (now, lease.task_id, lease.document_version, lease.attempt),
                )
                if finished.rowcount != 1:
                    raise RuntimeError("active parse attempt is missing")
                connection.execute(
                    "UPDATE tasks SET machine_status = 'reviewing' WHERE id = ?",
                    (lease.task_id,),
                )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

    def block_parse(self, lease: JobLease, code: str, reason: str) -> bool:
        now = self._now().isoformat()
        with self.auth_store.lock:
            connection = self.auth_store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                if not self._lease_is_current(connection, lease, now):
                    connection.rollback()
                    return False
                connection.execute(
                    """UPDATE processing_jobs SET status = 'blocked', lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ? AND document_version = ? AND stage = 'parse'""",
                    (now, lease.task_id, lease.document_version),
                )
                finished = connection.execute(
                    """UPDATE processing_attempts SET outcome = 'blocked', finished_at = ?
                    WHERE task_id = ? AND document_version = ? AND stage = 'parse' AND attempt = ?""",
                    (now, lease.task_id, lease.document_version, lease.attempt),
                )
                if finished.rowcount != 1:
                    raise RuntimeError("active parse attempt is missing")
                connection.execute(
                    """UPDATE tasks SET machine_status = 'blocked', blocked_code = ?,
                    blocked_reason = ?, recovery_action = 'replace_attachment' WHERE id = ?""",
                    (code, reason, lease.task_id),
                )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise
