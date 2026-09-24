"""One-shot DOCX processing, durable evidence, and stale-result rejection."""

import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.docx_parser import parse_docx
from backend.jobs import JobStore
from backend.clause_extractor import extract_clauses
from backend.metadata_extractor import extract_metadata
from backend.mock_pending import synthetic_attachment
from backend.tasks import TaskStore


def empty_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t> </w:t></w:r></w:p></w:body></w:document>",
        )
    return output.getvalue()


class DocxJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "demo.sqlite3"
        self.store = AuthStore(self.database)
        self.store.initialize()
        self.addCleanup(lambda: self.store.close())
        self.actor = self.store.create_user("business1", "business", "synthetic-password")
        self.tasks = TaskStore(self.store, self.root / "uploads")
        self.tasks.initialize()

    def upload(self, content: bytes | None = None) -> str:
        return self.tasks.create_task(
            self.actor, "synthetic.docx", content if content is not None else synthetic_attachment(),
            "采购部", "演示用户",
        )["task_id"]

    def test_success_persists_versioned_text_fields_clauses_and_status(self) -> None:
        task_id = self.upload()
        result = run_docx_once(self.tasks.jobs)
        self.assertEqual(result, {"task_id": task_id, "document_version": 1, "status": "reviewing"})
        row = self.store.connection.execute(
            "SELECT * FROM parsed_documents WHERE task_id = ? AND document_version = 1", (task_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        text = row["normalized_text"]
        self.assertIn("付款", text)
        for entry in json.loads(row["paragraphs_json"]) + json.loads(row["clauses_json"]):
            self.assertEqual(entry["document_version"], 1)
            self.assertEqual(text[entry["start"]:entry["end"]], entry["quote"])
            self.assertFalse(entry["locatable"])
            self.assertEqual(entry["reason"], "PREVIEW_NOT_AVAILABLE")
        fields = {field["name"]: field for field in json.loads(row["fields_json"])}
        self.assertEqual(fields["amount"]["value"], "100000")
        self.assertEqual(fields["currency"]["value"], "人民币")
        self.assertEqual(fields["supplier_credit_code"]["status"], "unrecognized")
        for field in fields.values():
            anchor = field["anchor"]
            if anchor is not None:
                self.assertEqual(anchor["document_version"], 1)
                self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])
                self.assertFalse(anchor["locatable"])
        self.assertEqual(self.store.connection.execute(
            "SELECT machine_status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()[0], "reviewing")
        self.assertEqual(self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ?", (task_id,)
        ).fetchone()[0], "completed")
        self.assertEqual(run_docx_once(self.tasks.jobs), {"status": "no_pending_docx"})
        self.store.close()
        reopened = AuthStore(self.database)
        try:
            reopened.initialize()
            self.assertEqual(reopened.connection.execute(
                "SELECT normalized_text FROM parsed_documents WHERE task_id = ?", (task_id,)
            ).fetchone()[0], text)
        finally:
            reopened.close()

    def test_empty_docx_blocks_and_can_be_replaced(self) -> None:
        task_id = self.upload(empty_docx())
        self.assertEqual(run_docx_once(self.tasks.jobs)["code"], "DOCX_EMPTY")
        status = self.tasks.get_task(task_id, self.actor)
        self.assertEqual(status["machine_status"], "blocked")
        self.assertEqual(status["recovery_action"], "replace_attachment")
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)
        revised = self.tasks.add_document_version(task_id, self.actor, 1, "revision.docx", synthetic_attachment())
        self.assertEqual(revised["document_version"], 2)
        self.assertEqual(run_docx_once(self.tasks.jobs)["status"], "reviewing")
        self.assertEqual(self.store.connection.execute(
            "SELECT document_version FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 2)

    def test_modified_attachment_blocks_without_persisting_evidence(self) -> None:
        task_id = self.upload()
        path = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        Path(path).write_bytes(b"changed")
        result = run_docx_once(self.tasks.jobs)
        self.assertEqual(result["code"], "ATTACHMENT_CHANGED")
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)

    def test_missing_attachment_blocks_with_replace_action(self) -> None:
        task_id = self.upload()
        path = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        Path(path).rename(Path(path).with_suffix(".absent"))
        self.assertEqual(run_docx_once(self.tasks.jobs)["code"], "ATTACHMENT_UNREADABLE")
        self.assertEqual(self.tasks.get_task(task_id, self.actor)["recovery_action"],
                         "replace_attachment")

    def test_oversized_original_blocks_with_size_reason(self) -> None:
        task_id = self.upload()
        path = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        Path(path).write_bytes(b"x" * (25 * 1024 * 1024 + 1))
        self.assertEqual(run_docx_once(self.tasks.jobs)["code"], "DOCX_UNREADABLE")
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)

    def test_cli_processes_one_docx_with_explicit_test_database(self) -> None:
        task_id = self.upload()
        command = [
            sys.executable, "-X", "utf8", "-m", "backend.docx_job",
            "--database", str(self.database), "--uploads", str(self.root / "uploads"),
        ]
        finished = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                  capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(finished.stdout)["task_id"], task_id)
        self.assertEqual(json.loads(finished.stdout)["status"], "reviewing")
        self.assertEqual(json.loads(subprocess.run(
            command, cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=True,
        ).stdout), {"status": "no_pending_docx"})

    def test_active_lease_reports_busy_instead_of_empty_queue(self) -> None:
        first_id = self.upload()
        lease = self.tasks.jobs.claim_next()
        self.assertEqual(lease.task_id, first_id)
        self.assertEqual(run_docx_once(self.tasks.jobs), {"status": "busy"})
        second_id = self.upload()
        self.assertEqual(run_docx_once(self.tasks.jobs), {"status": "busy"})
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM processing_jobs WHERE task_id = ?", (second_id,)
        ).fetchone()[0], "pending")

    def test_partial_result_write_rolls_back_all_state(self) -> None:
        task_id = self.upload()
        with self.store.connection:
            self.store.connection.execute(
                """CREATE TRIGGER reject_completed_attempt BEFORE UPDATE ON processing_attempts
                WHEN NEW.outcome = 'completed'
                BEGIN SELECT RAISE(FAIL, 'synthetic write failure'); END"""
            )
        with self.assertRaises(sqlite3.IntegrityError):
            run_docx_once(self.tasks.jobs)
        self.assertIsNone(self.store.connection.execute(
            "SELECT 1 FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone())
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM processing_jobs WHERE task_id = ?", (task_id,)
        ).fetchone()[0], "running")
        self.assertEqual(self.store.connection.execute(
            "SELECT machine_status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()[0], "parsing")
        self.assertEqual(self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ?", (task_id,)
        ).fetchone()[0], "running")
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE processing_jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE task_id = ?",
                (task_id,),
            )
        self.assertEqual(self.tasks.jobs.recover_expired(), 1)
        self.assertEqual(self.store.connection.execute(
            "SELECT machine_status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()[0], "pending")

    def test_missing_attempt_cannot_commit_partial_result(self) -> None:
        task_id = self.upload()
        lease = self.tasks.jobs.claim_next()
        parsed = parse_docx(synthetic_attachment(), 1)
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM processing_attempts WHERE task_id = ?", (task_id,)
            )
        with self.assertRaisesRegex(RuntimeError, "active parse attempt is missing"):
            self.tasks.jobs.complete_docx(lease, parsed, extract_metadata(parsed), extract_clauses(parsed))
        self.assertIsNone(self.store.connection.execute(
            "SELECT 1 FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone())
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM processing_jobs WHERE task_id = ?", (task_id,)
        ).fetchone()[0], "running")

    def test_expired_or_superseded_lease_cannot_commit(self) -> None:
        task_id = self.upload()
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        jobs = JobStore(self.store, clock=lambda: now)
        lease = jobs.claim_next(lease_seconds=5)
        parsed = parse_docx(synthetic_attachment(), 1)
        metadata = extract_metadata(parsed)
        clauses = extract_clauses(parsed)
        later = JobStore(self.store, clock=lambda: now + timedelta(seconds=6))
        self.assertFalse(later.complete_docx(lease, parsed, metadata, clauses))
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)
        later.recover_expired()
        replacement = later.claim_next()
        self.assertFalse(later.complete_docx(lease, parsed, metadata, clauses))
        self.assertTrue(later.complete_docx(replacement, parsed, metadata, clauses))

    def test_superseded_lease_cannot_write_old_version(self) -> None:
        task_id = self.upload()
        lease = self.tasks.jobs.claim_next()
        parsed = parse_docx(synthetic_attachment(), 1)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', recovery_action = 'replace_attachment' WHERE id = ?",
                (task_id,),
            )
        self.tasks.add_document_version(task_id, self.actor, 1, "new.docx", synthetic_attachment())
        self.assertFalse(self.tasks.jobs.complete_docx(
            lease, parsed, extract_metadata(parsed), extract_clauses(parsed)))
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)

    def test_existing_attempt_table_migrates_without_losing_history(self) -> None:
        task_id = self.upload()
        self.tasks.jobs.claim_next()
        with self.store.connection:
            self.store.connection.execute("DROP TABLE processing_attempts")
            self.store.connection.execute(
                """CREATE TABLE processing_attempts (
                    task_id TEXT, document_version INTEGER, stage TEXT, attempt INTEGER,
                    claimed_at TEXT, finished_at TEXT,
                    outcome TEXT CHECK (outcome IN ('running', 'lease_expired', 'superseded')),
                    PRIMARY KEY (task_id, document_version, stage, attempt))"""
            )
            self.store.connection.execute(
                "INSERT INTO processing_attempts VALUES (?, 1, 'parse', 1, ?, NULL, 'running')",
                (task_id, datetime.now(timezone.utc).isoformat()),
            )
        self.tasks.initialize()
        self.assertEqual(self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ?", (task_id,)
        ).fetchone()[0], "running")
        self.assertIn("'completed'", self.store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'processing_attempts'"
        ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
