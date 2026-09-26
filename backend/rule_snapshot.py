"""Persist one current-version commercial-rule draft from structured evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.auth import AuthStore, User
from backend.demo_rules import RULE_VERSION, evaluate_persisted_rule_evidence
from backend.errors import ApiError


def _evidence_digest(normalized_text: str, clauses: list, missing: list, pdf_context=None) -> str:
    data = {"normalized_text": normalized_text, "clauses": clauses,
            "missing_clause_types": missing}
    if pdf_context is not None:
        data["pdf_context"] = pdf_context
    evidence = json.dumps(
        data,
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(evidence).hexdigest()


class RuleSnapshotStore:
    def __init__(self, auth_store: AuthStore) -> None:
        self.auth_store = auth_store

    def initialize(self) -> None:
        with self.auth_store.lock, self.auth_store.connection:
            self.auth_store.connection.execute(
                """CREATE TABLE IF NOT EXISTS rule_draft_snapshots (
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    rule_version TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, document_version),
                    FOREIGN KEY (task_id, document_version)
                        REFERENCES document_versions(task_id, version)
                )"""
            )
            self.auth_store.connection.execute(
                """CREATE TABLE IF NOT EXISTS rule_processing_attempts (
                    task_id TEXT NOT NULL, document_version INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'completed', 'blocked', 'superseded')),
                    code TEXT, created_at TEXT NOT NULL, finished_at TEXT,
                    PRIMARY KEY (task_id, document_version, attempt),
                    FOREIGN KEY (task_id, document_version) REFERENCES document_versions(task_id, version)
                )"""
            )

    def run_next(self) -> dict:
        """Process one current rule stage atomically, including durable outcome."""
        connection = self.auth_store.connection
        with self.auth_store.lock:
            connection.execute("BEGIN IMMEDIATE")
            try:
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """UPDATE rule_processing_attempts SET outcome = 'superseded', finished_at = ?
                    WHERE outcome = 'pending' AND NOT EXISTS (
                        SELECT 1 FROM tasks t WHERE t.id = task_id
                        AND t.current_document_version = document_version)""", (now,))
                connection.execute(
                    """INSERT OR IGNORE INTO rule_processing_attempts
                    (task_id, document_version, attempt, outcome, created_at)
                    SELECT t.id, t.current_document_version, 1, 'pending', ?
                    FROM tasks t JOIN parsed_documents p ON p.task_id = t.id
                        AND p.document_version = t.current_document_version
                    JOIN document_versions d ON d.task_id = t.id AND d.version = t.current_document_version
                    WHERE t.machine_status = 'reviewing' AND p.structured_extraction_status = 'available'
                        AND d.format IN ('docx', 'pdf', 'png', 'jpeg', 'tiff')""", (now,))
                job = connection.execute(
                    """SELECT a.* FROM rule_processing_attempts a JOIN tasks t ON t.id = a.task_id
                    WHERE a.outcome = 'pending' AND a.document_version = t.current_document_version
                        AND t.machine_status = 'reviewing'
                    ORDER BY a.created_at, a.task_id LIMIT 1"""
                ).fetchone()
                if job is None:
                    connection.commit()
                    return {"status": "no_pending_rules"}
                task_id, version = job["task_id"], job["document_version"]
                # ponytail: local rules hold one SQLite write transaction; use leases before adding network/model work.
                connection.execute("SAVEPOINT rule_draft")
                try:
                    result = self._persist(task_id, version)
                    if result.get("operation") not in ("created", "already_exists"):
                        raise ApiError(409, result.get("code", "RULE_EVIDENCE_NOT_READY"), "规则证据尚不可用")
                    source = connection.execute(
                        "SELECT * FROM parsed_documents WHERE task_id = ? AND document_version = ?",
                        (task_id, version),
                    ).fetchone()
                    self.read({"task_id": task_id, "document_version": version,
                        "normalized_text": source["normalized_text"], "page_count": source["page_count"],
                        "paragraphs": json.loads(source["paragraphs_json"]),
                        "clauses": json.loads(source["clauses_json"]),
                        "missing_clause_types": json.loads(source["missing_clause_types_json"])})
                except sqlite3.Error:
                    raise
                except Exception as error:
                    connection.execute("ROLLBACK TO rule_draft")
                    code = error.code if isinstance(error, ApiError) else "RULE_PROCESSING_FAILED"
                    result = {"status": "blocked", "code": code}
                    connection.execute(
                        """UPDATE tasks SET machine_status = 'blocked', blocked_code = ?,
                        blocked_reason = ?, recovery_action = ?
                        WHERE id = ? AND current_document_version = ?""",
                        (code, "规则草稿处理暂时失败，请管理员排查后重试" if code == "RULE_PROCESSING_FAILED"
                         else "规则草稿与当前证据不可用或不一致，请换传附件",
                         "admin_retry" if code == "RULE_PROCESSING_FAILED" else "replace_attachment",
                         task_id, version))
                else:
                    result = {"status": "completed", "operation": result["operation"]}
                connection.execute("RELEASE rule_draft")
                connection.execute(
                    """UPDATE rule_processing_attempts SET outcome = ?, code = ?, finished_at = ?
                    WHERE task_id = ? AND document_version = ? AND attempt = ?""",
                    (result["status"], result.get("code"), now, task_id, version, job["attempt"]))
                connection.commit()
                return {**result, "task_id": task_id, "document_version": version, "attempt": job["attempt"]}
            except BaseException:
                connection.rollback()
                raise

    def retry(self, task_id: str, document_version: int, actor: User) -> dict:
        """Only an administrator may queue a temporary rule-stage failure again."""
        if actor.role != "admin":
            raise ApiError(403, "FORBIDDEN", "仅管理员可重试")
        connection = self.auth_store.connection
        with self.auth_store.lock:
            connection.execute("BEGIN IMMEDIATE")
            try:
                task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if task is None:
                    raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
                if task["current_document_version"] != document_version:
                    raise ApiError(409, "DOCUMENT_VERSION_CONFLICT", "文档版本已变化")
                previous = connection.execute(
                    """SELECT * FROM rule_processing_attempts WHERE task_id = ? AND document_version = ?
                    ORDER BY attempt DESC LIMIT 1""", (task_id, document_version)).fetchone()
                if (task["machine_status"] != "blocked" or task["blocked_code"] != "RULE_PROCESSING_FAILED"
                        or task["recovery_action"] != "admin_retry" or previous is None
                        or previous["outcome"] != "blocked" or previous["code"] != "RULE_PROCESSING_FAILED"):
                    raise ApiError(409, "TASK_STATE_CONFLICT", "当前不是可重试的规则处理暂时故障")
                now = datetime.now(timezone.utc).isoformat()
                attempt = previous["attempt"] + 1
                connection.execute(
                    """INSERT INTO rule_processing_attempts
                    (task_id, document_version, attempt, outcome, created_at) VALUES (?, ?, ?, 'pending', ?)""",
                    (task_id, document_version, attempt, now))
                connection.execute(
                    """UPDATE tasks SET machine_status = 'reviewing', blocked_code = NULL, blocked_reason = NULL,
                    recovery_action = NULL WHERE id = ?""", (task_id,))
                connection.execute(
                    """INSERT INTO audit_events (task_id, actor_user_id, action, document_version, created_at)
                    VALUES (?, ?, 'rule_retry_requested', ?, ?)""", (task_id, actor.id, document_version, now))
                connection.commit()
                return {"task_id": task_id, "document_version": document_version, "stage": "rules",
                        "attempt": attempt, "status": "pending", "machine_status": "reviewing"}
            except BaseException:
                connection.rollback()
                raise

    def read(self, document: dict) -> dict:
        """Read an immutable draft; never evaluate rules or create a snapshot."""
        with self.auth_store.lock:
            row = self.auth_store.connection.execute(
                "SELECT * FROM rule_draft_snapshots WHERE task_id = ? AND document_version = ?",
                (document["task_id"], document["document_version"]),
            ).fetchone()
        if row is None:
            raise ApiError(409, "RULE_SNAPSHOT_NOT_READY", "该文档版本尚未保存规则草稿")
        digest = _evidence_digest(
            document["normalized_text"], document["clauses"], document["missing_clause_types"],
            {"paragraphs": document["paragraphs"], "page_count": document["page_count"]}
            if document["page_count"] is not None else None,
        )
        if digest != row["evidence_sha256"]:
            raise ApiError(409, "RULE_EVIDENCE_CHANGED", "解析证据与已保存草稿不一致")
        try:
            snapshot = json.loads(row["snapshot_json"])
            valid = (
                isinstance(snapshot, dict)
                and snapshot.get("task_id") == document["task_id"]
                and snapshot.get("document_version") == document["document_version"]
                and "review_version" in snapshot and snapshot["review_version"] is None
                and snapshot.get("persisted") is True
                and snapshot.get("evaluation_mode") == "persisted_rule_draft_only"
                and snapshot.get("status") == "machine_draft"
                and isinstance(snapshot.get("machine_suggestion"), str)
                and isinstance(snapshot.get("enabled_rule_risk_summary"), str)
                and isinstance(snapshot.get("risks"), list)
                and all(isinstance(risk, dict)
                        and risk.get("document_version") == document["document_version"]
                        and risk.get("rule_version") == row["rule_version"]
                        and risk.get("source") == "rule"
                        and risk.get("status") == "machine_draft"
                        and all(isinstance(risk.get(key), str) for key in (
                            "rule_id", "clause_type", "risk_type", "risk_level", "trigger_reason",
                            "evidence_source", "suggestion", "legal_basis_status"))
                        and "review_version" in risk and risk["review_version"] is None
                        and isinstance(risk.get("anchors"), list) and risk["anchors"]
                        and all(anchor in document["clauses"] for anchor in risk["anchors"])
                        for risk in snapshot["risks"])
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ApiError(409, "RULE_SNAPSHOT_INVALID", "已保存的规则草稿损坏或版本不一致")
        return {**snapshot, "rule_version": row["rule_version"],
                "rule_version_current": row["rule_version"] == RULE_VERSION,
                "evidence_sha256": row["evidence_sha256"], "created_at": row["created_at"]}

    def persist(self, task_id: str, document_version: int) -> dict:
        """Write at most one draft for the current parsed version, or fail closed."""
        connection = self.auth_store.connection
        with self.auth_store.lock:
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = self._persist(task_id, document_version)
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def _persist(self, task_id: str, document_version: int) -> dict:
        """Caller holds the lock and transaction, including any stage bookkeeping."""
        connection = self.auth_store.connection
        task = connection.execute(
            """SELECT t.current_document_version, t.machine_status, d.format,
                p.structured_extraction_status
            FROM tasks AS t JOIN document_versions AS d
              ON d.task_id = t.id AND d.version = t.current_document_version
            LEFT JOIN parsed_documents AS p ON p.task_id = t.id
              AND p.document_version = t.current_document_version
            WHERE t.id = ?""", (task_id,)
        ).fetchone()
        if task is None:
            result = {"status": "task_not_found", "task_id": task_id}
        elif task["current_document_version"] != document_version:
            result = {"status": "stale_document_version", "task_id": task_id,
                      "document_version": document_version}
        elif task["format"] not in ("docx", "pdf", "png", "jpeg", "tiff"):
            result = {"status": "unsupported_document_format", "task_id": task_id,
                      "document_version": document_version}
        elif task["machine_status"] != "reviewing":
            result = {"status": "document_not_ready", "task_id": task_id,
                      "document_version": document_version}
        elif task["structured_extraction_status"] != "available":
            result = {"status": "document_not_ready", "code": "RULE_EVIDENCE_NOT_READY",
                      "task_id": task_id, "document_version": document_version}
        else:
            existing = connection.execute(
                """SELECT snapshot_json, evidence_sha256, rule_version FROM rule_draft_snapshots
                WHERE task_id = ? AND document_version = ?""",
                (task_id, document_version),
            ).fetchone()
            if existing is not None and existing["rule_version"] != RULE_VERSION:
                result = {"status": "rule_version_changed", "code": "RULE_VERSION_CHANGED",
                          "task_id": task_id, "document_version": document_version}
            elif existing is not None:
                source = connection.execute(
                    """SELECT normalized_text, clauses_json, missing_clause_types_json,
                        paragraphs_json, page_count
                    FROM parsed_documents WHERE task_id = ? AND document_version = ?""",
                    (task_id, document_version),
                ).fetchone()
                try:
                    digest = _evidence_digest(
                        source["normalized_text"], json.loads(source["clauses_json"]),
                        json.loads(source["missing_clause_types_json"]),
                        {"paragraphs": json.loads(source["paragraphs_json"]),
                         "page_count": source["page_count"]} if task["format"] != "docx" else None,
                    )
                except (TypeError, ValueError):
                    digest = None
                if digest != existing["evidence_sha256"]:
                    result = {"status": "evidence_changed", "code": "RULE_EVIDENCE_CHANGED",
                              "task_id": task_id, "document_version": document_version}
                else:
                    try:
                        result = {**json.loads(existing["snapshot_json"]),
                                  "operation": "already_exists"}
                    except (TypeError, ValueError):
                        result = {"status": "snapshot_invalid", "code": "RULE_SNAPSHOT_INVALID",
                                  "task_id": task_id, "document_version": document_version}
            else:
                row = connection.execute(
                    """SELECT normalized_text, paragraphs_json, clauses_json, missing_clause_types_json, page_count
                    FROM parsed_documents WHERE task_id = ? AND document_version = ?""",
                    (task_id, document_version),
                ).fetchone()
                if row is None:
                    result = {"status": "document_not_ready", "task_id": task_id,
                              "document_version": document_version}
                else:
                    try:
                        clauses_data = json.loads(row["clauses_json"])
                        missing = json.loads(row["missing_clause_types_json"])
                        draft = evaluate_persisted_rule_evidence(
                            document_version, row["normalized_text"],
                            json.loads(row["paragraphs_json"]), clauses_data, missing,
                        )
                    except (TypeError, ValueError, KeyError):
                        result = {"status": "evidence_invalid", "code": "RULE_EVIDENCE_INVALID",
                                  "task_id": task_id, "document_version": document_version}
                    else:
                        snapshot = {
                            "task_id": task_id, **draft,
                            "evaluation_mode": "persisted_rule_draft_only",
                            "persisted": True,
                        }
                        connection.execute(
                            """INSERT INTO rule_draft_snapshots
                            (task_id, document_version, rule_version, evidence_sha256,
                             snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                            (task_id, document_version, RULE_VERSION,
                             _evidence_digest(row["normalized_text"], clauses_data, missing,
                                 {"paragraphs": json.loads(row["paragraphs_json"]),
                                  "page_count": row["page_count"]} if task["format"] != "docx" else None),
                             json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                             datetime.now(timezone.utc).isoformat()),
                        )
                        result = {**snapshot, "operation": "created"}
        return result


def main() -> int:
    from backend.main import default_database_path, default_upload_root
    from backend.tasks import TaskStore

    parser = argparse.ArgumentParser(description="Persist one same-version rule draft")
    parser.add_argument("task_id")
    parser.add_argument("document_version", type=int)
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--uploads", type=Path, default=default_upload_root())
    args = parser.parse_args()
    store = AuthStore(args.database)
    try:
        store.initialize()
        tasks = TaskStore(store, args.uploads)
        tasks.initialize()
        result = tasks.rule_snapshots.persist(args.task_id, args.document_version)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("operation") in ("created", "already_exists") else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
