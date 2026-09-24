"""Persistent synthetic-contract intake and role-filtered task summaries."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from backend.auth import AuthStore, User
from backend.demo_rules import evaluate_persisted_rule_evidence
from backend.errors import ApiError
from backend.jobs import JobStore
from backend.rule_snapshot import RuleSnapshotStore


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
FORMATS = {
    ".docx": "docx",
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".tif": "tiff",
    ".tiff": "tiff",
}


def identify_document(filename: str, content: bytes) -> tuple[str, str]:
    safe_name = filename.replace("\\", "/").split("/")[-1]
    if not safe_name or len(safe_name) > 255 or any(ord(char) < 32 for char in safe_name):
        raise ApiError(422, "INVALID_FILE", "文件名无效")
    suffix = Path(safe_name).suffix.lower()
    file_format = FORMATS.get(suffix)
    if file_format is None:
        raise ApiError(415, "UNSUPPORTED_FILE", "仅接受 DOCX、PDF 或常见扫描图片")
    if not content:
        raise ApiError(422, "EMPTY_FILE", "附件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "附件不能超过 25 MiB")

    valid = False
    if file_format == "pdf":
        valid = content.startswith(b"%PDF-")
    elif file_format == "png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif file_format == "jpeg":
        valid = content.startswith(b"\xff\xd8\xff")
    elif file_format == "tiff":
        valid = content.startswith((b"II*\x00", b"MM\x00*"))
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                valid = (
                    "[Content_Types].xml" in names
                    and "word/document.xml" in names
                    and len(names) <= 1000
                    and sum(entry.file_size for entry in archive.infolist())
                    <= MAX_DOCX_UNCOMPRESSED_BYTES
                )
        except (OSError, zipfile.BadZipFile):
            valid = False
    if not valid:
        raise ApiError(422, "INVALID_FILE", "附件内容与文件格式不符或文件损坏")
    return safe_name, file_format


@contextmanager
def stored_attachment(file_path: Path, content: bytes, *, new_task: bool = False):
    """Keep only a file whose database transaction completes successfully."""
    staging_path = file_path.with_name(file_path.name + ".part")
    created_directory = False
    staging_created = False
    published = False
    try:
        file_path.parent.mkdir(parents=True, exist_ok=not new_task)
        created_directory = new_task
        with staging_path.open("xb") as target:
            staging_created = True
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        staging_path.rename(file_path)
        published = True
        yield
    except BaseException:
        if staging_created:
            staging_path.unlink(missing_ok=True)
        if published:
            file_path.unlink(missing_ok=True)
        if created_directory:
            file_path.parent.rmdir()
        raise


class TaskStore:
    def __init__(self, auth_store: AuthStore, upload_root: str | Path) -> None:
        self.auth_store = auth_store
        self.upload_root = Path(upload_root)
        self.jobs = JobStore(auth_store)
        self.rule_snapshots = RuleSnapshotStore(auth_store)

    def initialize(self) -> None:
        with self.auth_store.lock, self.auth_store.connection:
            self.auth_store.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id),
                    source TEXT NOT NULL CHECK (source IN ('upload', 'mock_pending')),
                    department TEXT NOT NULL,
                    applicant TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    current_document_version INTEGER NOT NULL,
                    current_review_version INTEGER,
                    machine_status TEXT NOT NULL,
                    legal_status TEXT NOT NULL,
                    writeback_status TEXT NOT NULL,
                    blocked_code TEXT,
                    blocked_reason TEXT,
                    recovery_action TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    mock_approval_id TEXT
                );
                CREATE INDEX IF NOT EXISTS tasks_owner_idx ON tasks(owner_user_id);
                CREATE TABLE IF NOT EXISTS document_versions (
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    version INTEGER NOT NULL,
                    original_filename TEXT NOT NULL,
                    format TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    submitted_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, version)
                );
                CREATE TABLE IF NOT EXISTS document_state_history (
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    version INTEGER NOT NULL,
                    review_version INTEGER,
                    machine_status TEXT NOT NULL,
                    legal_status TEXT NOT NULL,
                    writeback_status TEXT NOT NULL,
                    blocked_code TEXT,
                    blocked_reason TEXT,
                    recovery_action TEXT,
                    attempt_count INTEGER NOT NULL,
                    superseded_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, version),
                    FOREIGN KEY (task_id, version) REFERENCES document_versions(task_id, version)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    actor_user_id INTEGER NOT NULL REFERENCES users(id),
                    action TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in self.auth_store.connection.execute("PRAGMA table_info(tasks)")
            }
            if "mock_approval_id" not in columns:
                self.auth_store.connection.execute(
                    "ALTER TABLE tasks ADD COLUMN mock_approval_id TEXT"
                )
        self.jobs.initialize()
        self.rule_snapshots.initialize()

    def create_task(
        self,
        actor: User,
        filename: str,
        content: bytes,
        department: str,
        applicant: str,
        *,
        source: str = "upload",
        mock_approval_id: str | None = None,
    ) -> dict:
        if actor.role != "business":
            raise ApiError(403, "FORBIDDEN", "无权执行此操作")
        if source not in ("upload", "mock_pending") or (
            source == "upload" and mock_approval_id is not None
        ) or (source == "mock_pending" and not mock_approval_id):
            raise ValueError("invalid task source")
        department = department.strip()
        applicant = applicant.strip()
        if not department or not applicant or len(department) > 120 or len(applicant) > 120:
            raise ApiError(422, "INVALID_REQUEST", "部门和申请人须为 1 至 120 个字符")
        safe_name, file_format = identify_document(filename, content)
        task_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(content).hexdigest()
        file_path = self.upload_root / task_id / f"v1.{Path(safe_name).suffix.lower().lstrip('.')}"
        # A random internal path prevents uploaded filenames from controlling storage paths.
        with self.auth_store.lock, stored_attachment(file_path, content, new_task=True), self.auth_store.connection:
            self.auth_store.connection.execute(
                """INSERT INTO tasks
                (id, owner_user_id, source, department, applicant, created_at,
                 current_document_version, machine_status, legal_status, writeback_status,
                 mock_approval_id)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'pending', 'pending', 'not_written', ?)""",
                (task_id, actor.id, source, department, applicant, now, mock_approval_id),
            )
            self.auth_store.connection.execute(
                """INSERT INTO document_versions
                (task_id, version, original_filename, format, sha256, file_path, submitted_by, created_at)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?)""",
                (task_id, safe_name, file_format, digest, str(file_path), actor.id, now),
            )
            self.jobs.enqueue_parse(task_id, 1, now)
            self.auth_store.connection.execute(
                """INSERT INTO audit_events
                (task_id, actor_user_id, action, document_version, created_at)
                VALUES (?, ?, ?, 1, ?)""",
                (task_id, actor.id,
                 "mock_pending_imported" if source == "mock_pending" else "task_created", now),
            )
        return self.get_task(task_id, actor)

    def add_document_version(
        self,
        task_id: str,
        actor: User,
        base_document_version: int,
        filename: str,
        content: bytes,
    ) -> dict:
        if actor.role != "business":
            raise ApiError(403, "FORBIDDEN", "无权执行此操作")
        with self.auth_store.lock:
            row = self.auth_store.connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None or row["owner_user_id"] != actor.id:
                raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
            if base_document_version != row["current_document_version"]:
                raise ApiError(
                    409, "DOCUMENT_VERSION_CONFLICT", "文档版本已变化，请刷新任务",
                    task_id=task_id, current_status=self._current_status(row),
                )
            if not (
                (row["machine_status"] == "blocked" and row["recovery_action"] == "replace_attachment")
                or (row["machine_status"] == "completed" and row["legal_status"] == "confirmed")
            ):
                raise ApiError(
                    409, "TASK_STATE_CONFLICT", "当前状态不能更换附件",
                    task_id=task_id, current_status=self._current_status(row),
                )

            safe_name, file_format = identify_document(filename, content)
            next_version = base_document_version + 1
            now = datetime.now(timezone.utc).isoformat()
            digest = hashlib.sha256(content).hexdigest()
            suffix = Path(safe_name).suffix.lower().lstrip(".")
            file_path = self.upload_root / task_id / f"v{next_version}-{uuid.uuid4().hex}.{suffix}"
            with stored_attachment(file_path, content), self.auth_store.connection:
                self.auth_store.connection.execute(
                    """INSERT INTO document_state_history
                    (task_id, version, review_version, machine_status, legal_status, writeback_status,
                     blocked_code, blocked_reason, recovery_action, attempt_count, superseded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_id, base_document_version, row["current_review_version"],
                        row["machine_status"], row["legal_status"],
                        row["writeback_status"], row["blocked_code"], row["blocked_reason"],
                        row["recovery_action"], row["attempt_count"], now,
                    ),
                )
                self.auth_store.connection.execute(
                    """INSERT INTO document_versions
                    (task_id, version, original_filename, format, sha256, file_path, submitted_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, next_version, safe_name, file_format, digest, str(file_path), actor.id, now),
                )
                self.auth_store.connection.execute(
                    """UPDATE tasks SET current_document_version = ?, current_review_version = NULL,
                        machine_status = 'pending', legal_status = 'pending',
                        writeback_status = 'not_written', blocked_code = NULL,
                        blocked_reason = NULL, recovery_action = NULL, attempt_count = 0
                    WHERE id = ?""",
                    (next_version, task_id),
                )
                self.jobs.supersede(task_id, base_document_version, now)
                self.jobs.enqueue_parse(task_id, next_version, now)
                self.auth_store.connection.execute(
                    """INSERT INTO audit_events
                    (task_id, actor_user_id, action, document_version, created_at)
                    VALUES (?, ?, 'document_version_created', ?, ?)""",
                    (task_id, actor.id, next_version, now),
                )
        return self.get_task(task_id, actor)

    @staticmethod
    def _current_status(row: sqlite3.Row) -> dict:
        return {
            "document_version": row["current_document_version"],
            "review_version": row["current_review_version"],
            "machine_status": row["machine_status"],
            "legal_status": row["legal_status"],
            "writeback_status": row["writeback_status"],
            "blocked_code": row["blocked_code"],
            "blocked_reason": row["blocked_reason"],
            "recovery_action": row["recovery_action"],
            "attempt_count": row["attempt_count"],
        }

    def get_task(self, task_id: str, actor: User) -> dict:
        with self.auth_store.lock:
            row = self.auth_store.connection.execute(
                """SELECT t.*, u.username AS owner_username,
                    d.original_filename, d.format, d.sha256
                FROM tasks AS t JOIN users AS u ON u.id = t.owner_user_id
                JOIN document_versions AS d ON d.task_id = t.id
                    AND d.version = t.current_document_version
                WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
        if row is None or (actor.role == "business" and row["owner_user_id"] != actor.id):
            raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
        return self._visible_summary(row, actor)

    def get_parsed_document(
        self, task_id: str, actor: User, document_version: int | None = None
    ) -> dict:
        """Return persisted, same-version parse evidence to legal reviewers only."""
        with self.auth_store.lock:
            task = self.auth_store.connection.execute(
                "SELECT owner_user_id, current_document_version FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task is None or (actor.role == "business" and task["owner_user_id"] != actor.id):
                raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
            if actor.role == "business":
                raise ApiError(403, "DOCUMENT_NOT_CONFIRMED", "法务确认前不可查看解析结果")
            if actor.role != "legal":
                raise ApiError(403, "FORBIDDEN", "无权查看合同解析结果")
            version = task["current_document_version"] if document_version is None else document_version
            exists = self.auth_store.connection.execute(
                "SELECT 1 FROM document_versions WHERE task_id = ? AND version = ?",
                (task_id, version),
            ).fetchone()
            if exists is None:
                raise ApiError(404, "DOCUMENT_VERSION_NOT_FOUND", "文档版本不存在")
            parsed = self.auth_store.connection.execute(
                "SELECT * FROM parsed_documents WHERE task_id = ? AND document_version = ?",
                (task_id, version),
            ).fetchone()
            if parsed is None:
                raise ApiError(409, "DOCUMENT_NOT_READY", "该文档版本尚无解析结果")
            try:
                paragraphs = json.loads(parsed["paragraphs_json"])
                fields = json.loads(parsed["fields_json"])
                clauses = json.loads(parsed["clauses_json"])
                missing = json.loads(parsed["missing_clause_types_json"])
            except (TypeError, ValueError):
                raise ApiError(409, "DOCUMENT_EVIDENCE_INVALID", "已保存的解析证据损坏") from None
            return {
                "task_id": task_id,
                "document_version": version,
                "review_version": None,
                "normalized_text": parsed["normalized_text"],
                "paragraphs": paragraphs,
                "fields": fields,
                "clauses": clauses,
                "missing_clause_types": missing,
                "page_count": None,
                "preview_available": False,
                "created_at": parsed["created_at"],
            }

    def get_rule_drafts(
        self, task_id: str, actor: User, document_version: int | None = None,
        review_version: int | None = None,
    ) -> dict:
        """Evaluate persisted evidence without creating a review or changing status."""
        try:
            document = self.get_parsed_document(task_id, actor, document_version)
        except ApiError as error:
            if error.code == "DOCUMENT_EVIDENCE_INVALID":
                raise ApiError(409, "RULE_EVIDENCE_INVALID", "解析证据损坏，无法生成规则草稿") from None
            raise
        if review_version is not None:
            raise ApiError(404, "REVIEW_VERSION_NOT_FOUND", "审查版本不存在")
        try:
            result = evaluate_persisted_rule_evidence(
                document["document_version"], document["normalized_text"],
                document["paragraphs"], document["clauses"],
                document["missing_clause_types"],
            )
        except (TypeError, ValueError, KeyError):
            raise ApiError(409, "RULE_EVIDENCE_INVALID", "解析证据与文档不一致，无法生成规则草稿") from None
        return {
            "task_id": task_id,
            **result,
            "evaluation_mode": "on_demand_rules_only",
            "persisted": False,
        }

    def list_tasks(
        self,
        actor: User,
        machine_status: str | None = None,
        legal_status: str | None = None,
        writeback_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        clauses: list[str] = []
        values: list[object] = []
        if actor.role == "business":
            clauses.append("t.owner_user_id = ?")
            values.append(actor.id)
        if machine_status is not None:
            clauses.append("t.machine_status = ?")
            values.append(machine_status)
        if legal_status is not None:
            clauses.append("t.legal_status = ?")
            values.append(legal_status)
        if writeback_status is not None:
            clauses.append("t.writeback_status = ?")
            values.append(writeback_status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.auth_store.lock:
            total = self.auth_store.connection.execute(
                f"SELECT COUNT(*) FROM tasks AS t {where}", values
            ).fetchone()[0]
            rows = self.auth_store.connection.execute(
                f"""SELECT t.*, u.username AS owner_username,
                    d.original_filename, d.format, d.sha256
                FROM tasks AS t JOIN users AS u ON u.id = t.owner_user_id
                JOIN document_versions AS d ON d.task_id = t.id
                    AND d.version = t.current_document_version
                {where} ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?""",
                [*values, limit, offset],
            ).fetchall()
        return {"items": [self._visible_summary(row, actor) for row in rows], "total": total}

    @staticmethod
    def _visible_summary(row: sqlite3.Row, actor: User) -> dict:
        summary = {
            "task_id": row["id"],
            "owner_username": row["owner_username"],
            "source": row["source"],
            "created_at": row["created_at"],
            "document_version": row["current_document_version"],
            "review_version": row["current_review_version"],
            "machine_status": row["machine_status"],
            "legal_status": row["legal_status"],
            "writeback_status": row["writeback_status"],
            "blocked_code": row["blocked_code"],
            "blocked_reason": row["blocked_reason"],
            "recovery_action": row["recovery_action"],
            "attempt_count": row["attempt_count"],
        }
        if actor.role != "admin":
            summary["submission"] = {
                "department": row["department"],
                "applicant": row["applicant"],
                "filename": row["original_filename"],
                "format": row["format"],
                "sha256": row["sha256"],
            }
        if actor.role != "admin" and row["mock_approval_id"] is not None:
            summary["mock_approval_id"] = row["mock_approval_id"]
        return summary
