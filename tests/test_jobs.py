"""Durable parse queue checks before parser execution is implemented."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.auth import AuthStore
from backend.jobs import JobStore
from backend.tasks import TaskStore


PDF = b"%PDF-1.4\nsynthetic queue sample\n%%EOF"


class JobStoreTests(unittest.TestCase):
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

    def upload(self) -> str:
        return self.tasks.create_task(
            self.actor, "synthetic.pdf", PDF, "采购部", "演示用户"
        )["task_id"]

    def test_upload_and_replacement_register_versioned_jobs(self) -> None:
        task_id = self.upload()
        first = self.store.connection.execute(
            "SELECT status, attempt_count FROM processing_jobs WHERE task_id = ? AND document_version = 1",
            (task_id,),
        ).fetchone()
        self.assertEqual(tuple(first), ("pending", 0))
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', recovery_action = 'replace_attachment' WHERE id = ?",
                (task_id,),
            )
        revised = self.tasks.add_document_version(
            task_id, self.actor, 1, "revision.pdf", PDF + b" revised"
        )
        self.assertEqual(revised["document_version"], 2)
        jobs = self.store.connection.execute(
            "SELECT document_version, status FROM processing_jobs WHERE task_id = ? ORDER BY document_version",
            (task_id,),
        ).fetchall()
        self.assertEqual([tuple(row) for row in jobs], [(1, "superseded"), (2, "pending")])

    def test_exclusive_claim_and_restart_recovery_keep_attempt_history(self) -> None:
        task_id = self.upload()
        second_task_id = self.upload()
        now = datetime(2030, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
        jobs = JobStore(self.store, clock=lambda: now)
        lease = jobs.claim_next(lease_seconds=60)
        self.assertIsNotNone(lease)
        self.assertIn(lease.task_id, (task_id, second_task_id))
        self.assertEqual(lease.attempt, 1)
        self.assertEqual(Path(lease.file_path).read_bytes(), PDF)
        self.assertIsNone(jobs.claim_next())
        self.assertTrue(jobs.renew(lease, lease_seconds=60))
        self.assertTrue(self.store.connection.execute(
            "SELECT lease_expires_at FROM processing_jobs WHERE task_id = ?", (lease.task_id,)
        ).fetchone()[0].endswith("+00:00"))
        second_connection = AuthStore(self.database)
        try:
            self.assertIsNone(JobStore(second_connection, clock=lambda: now).claim_next())
        finally:
            second_connection.close()
        active = self.store.connection.execute(
            "SELECT machine_status, attempt_count FROM tasks WHERE id = ?", (lease.task_id,)
        ).fetchone()
        self.assertEqual(tuple(active), ("parsing", 1))

        self.store.close()
        self.store = AuthStore(self.database)
        self.store.initialize()
        self.tasks = TaskStore(self.store, self.root / "uploads")
        self.tasks.initialize()
        recovered = JobStore(self.store, clock=lambda: now + timedelta(seconds=61))
        self.assertEqual(recovered.recover_expired(), 1)
        job = self.store.connection.execute(
            "SELECT status, attempt_count FROM processing_jobs WHERE task_id = ?",
            (lease.task_id,),
        ).fetchone()
        self.assertEqual(tuple(job), ("pending", 1))
        self.assertEqual(self.store.connection.execute(
            "SELECT machine_status FROM tasks WHERE id = ?", (lease.task_id,)
        ).fetchone()[0], "pending")
        self.assertEqual(self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ? AND attempt = 1",
            (lease.task_id,),
        ).fetchone()[0], "lease_expired")
        self.assertFalse(recovered.renew(lease))
        next_lease = recovered.claim_next()
        self.assertEqual(next_lease.task_id, lease.task_id)
        self.assertEqual(next_lease.attempt, 2)
        self.assertNotEqual(next_lease.lease_token, lease.lease_token)

    def test_existing_pending_task_is_backfilled_without_duplicate(self) -> None:
        task_id = self.upload()
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM processing_jobs WHERE task_id = ?", (task_id,)
            )
        self.tasks.initialize()
        self.tasks.initialize()
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 1)

    def test_replacement_marks_incomplete_attempt_as_superseded(self) -> None:
        task_id = self.upload()
        lease = self.tasks.jobs.claim_next()
        self.assertEqual(lease.task_id, task_id)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', recovery_action = 'replace_attachment' WHERE id = ?",
                (task_id,),
            )
        self.tasks.add_document_version(task_id, self.actor, 1, "revision.pdf", PDF + b" revised")
        self.assertEqual(self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ? AND attempt = 1",
            (task_id,),
        ).fetchone()[0], "superseded")
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM processing_jobs WHERE task_id = ? AND document_version = 1",
            (task_id,),
        ).fetchone()[0], "superseded")


if __name__ == "__main__":
    unittest.main()
