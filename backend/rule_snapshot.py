"""Persist one current-version commercial-rule draft from parsed DOCX evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.auth import AuthStore
from backend.demo_rules import RULE_VERSION, evaluate_persisted_rule_evidence


def _evidence_digest(normalized_text: str, clauses: list, missing: list) -> str:
    evidence = json.dumps(
        {"normalized_text": normalized_text, "clauses": clauses,
         "missing_clause_types": missing},
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

    def persist(self, task_id: str, document_version: int) -> dict:
        """Write at most one draft for the current parsed version, or fail closed."""
        connection = self.auth_store.connection
        with self.auth_store.lock:
            connection.execute("BEGIN IMMEDIATE")
            try:
                task = connection.execute(
                    """SELECT t.current_document_version, t.machine_status, d.format
                    FROM tasks AS t JOIN document_versions AS d
                      ON d.task_id = t.id AND d.version = t.current_document_version
                    WHERE t.id = ?""", (task_id,)
                ).fetchone()
                if task is None:
                    result = {"status": "task_not_found", "task_id": task_id}
                elif task["current_document_version"] != document_version:
                    result = {"status": "stale_document_version", "task_id": task_id,
                              "document_version": document_version}
                elif task["format"] != "docx":
                    result = {"status": "unsupported_document_format", "task_id": task_id,
                              "document_version": document_version}
                elif task["machine_status"] != "reviewing":
                    result = {"status": "document_not_ready", "task_id": task_id,
                              "document_version": document_version}
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
                            """SELECT normalized_text, clauses_json, missing_clause_types_json
                            FROM parsed_documents WHERE task_id = ? AND document_version = ?""",
                            (task_id, document_version),
                        ).fetchone()
                        try:
                            digest = _evidence_digest(
                                source["normalized_text"], json.loads(source["clauses_json"]),
                                json.loads(source["missing_clause_types_json"]),
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
                            """SELECT normalized_text, paragraphs_json, clauses_json, missing_clause_types_json
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
                                     _evidence_digest(row["normalized_text"], clauses_data, missing),
                                     json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                                     datetime.now(timezone.utc).isoformat()),
                                )
                                result = {**snapshot, "operation": "created"}
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise


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
