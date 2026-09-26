"""Standalone smoke for same-version PDF rule snapshots using temporary data."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.auth import AuthStore
from backend.pdf_job import run_pdf_once
from backend.tasks import TaskStore


class PdfSnapshotTests(unittest.TestCase):
    def test_pdf_snapshot_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "test.sqlite3"
            store = AuthStore(database)
            try:
                store.initialize()
                owner = store.create_user("owner", "business", "synthetic-password")
                tasks = TaskStore(store, root / "uploads")
                tasks.initialize()
                content = (Path(__file__).resolve().parents[1] / "samples/f2-text-software-purchase.pdf").read_bytes()
                task_id = tasks.create_task(owner, "f2.pdf", content, "test", "test")["task_id"]
                snapshots = tasks.rule_snapshots
                self.assertEqual(snapshots.persist(task_id, 1)["status"], "document_not_ready")
                self.assertEqual(run_pdf_once(tasks.jobs)["status"], "reviewing")
                with store.connection:
                    store.connection.execute("UPDATE parsed_documents SET structured_extraction_status = 'not_implemented' WHERE task_id = ?", (task_id,))
                self.assertEqual(snapshots.persist(task_id, 1)["code"], "RULE_EVIDENCE_NOT_READY")
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM rule_draft_snapshots").fetchone()[0], 0)
                with store.connection:
                    store.connection.execute("UPDATE parsed_documents SET structured_extraction_status = 'available' WHERE task_id = ?", (task_id,))
                command = subprocess.run([sys.executable, "-X", "utf8", "-m", "backend.rule_snapshot",
                    task_id, "1", "--database", str(database), "--uploads", str(root / "uploads")],
                    capture_output=True, text=True, encoding="utf-8", check=True)
                result = json.loads(command.stdout)
                self.assertEqual(result["operation"], "created")
                self.assertTrue(result["persisted"])
                self.assertIsNone(result["review_version"])
                self.assertEqual({r["rule_id"]: [a["page"] for a in r["anchors"]] for r in result["risks"]},
                                 {"DEMO-IP-01": [3], "DEMO-PAY-01": [2, 2]})
                original = tuple(store.connection.execute("SELECT * FROM rule_draft_snapshots").fetchone())
                second = snapshots.persist(task_id, 1)
                self.assertEqual(second["operation"], "already_exists")
                self.assertEqual(second["risks"], result["risks"])
                self.assertEqual(tuple(store.connection.execute("SELECT * FROM rule_draft_snapshots").fetchone()), original)
                self.assertEqual(tasks.get_task(task_id, owner)["machine_status"], "reviewing")
                self.assertEqual(snapshots.persist(task_id, 2)["status"], "stale_document_version")
                source = store.connection.execute("SELECT paragraphs_json, clauses_json, page_count FROM parsed_documents WHERE task_id = ?", (task_id,)).fetchone()
                for column, value in (("paragraphs_json", "[]"), ("clauses_json", "[]"), ("page_count", 4)):
                    with store.connection:
                        store.connection.execute(f"UPDATE parsed_documents SET {column} = ? WHERE task_id = ?", (value, task_id))
                    self.assertEqual(snapshots.persist(task_id, 1)["code"], "RULE_EVIDENCE_CHANGED")
                    self.assertEqual(tuple(store.connection.execute("SELECT * FROM rule_draft_snapshots").fetchone()), original)
                    with store.connection:
                        store.connection.execute(f"UPDATE parsed_documents SET {column} = ? WHERE task_id = ?", (source[column], task_id))
                # New connection verifies durable idempotence, not only in-memory reuse.
                reopened = AuthStore(database)
                try:
                    reopened.initialize()
                    restored = TaskStore(reopened, root / "uploads")
                    restored.initialize()
                    self.assertEqual(restored.rule_snapshots.persist(task_id, 1)["operation"], "already_exists")
                finally:
                    reopened.close()
                with store.connection:
                    store.connection.execute("UPDATE rule_draft_snapshots SET rule_version = 'old-rule'")
                self.assertEqual(snapshots.persist(task_id, 1)["code"], "RULE_VERSION_CHANGED")
            finally:
                store.close()
