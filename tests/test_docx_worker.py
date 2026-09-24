"""Automatic DOCX processing against a temporary API database."""

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import _renew_lease
from backend.main import create_app
from backend.mock_pending import synthetic_attachment
from backend.tasks import TaskStore
from tests.test_docx_job import empty_docx


class DocxWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = AuthStore(self.root / "worker.sqlite3")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.actor = self.store.create_user("business1", "business", "synthetic-password")
        self.store.create_user("business2", "business", "other-synthetic-password")

    def wait_for(self, task_id: str, expected: str) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.store.connection.execute(
                "SELECT machine_status, blocked_code, recovery_action, attempt_count "
                "FROM tasks WHERE id = ?", (task_id,),
            ).fetchone()
            if row["machine_status"] == expected:
                return dict(row)
            time.sleep(0.02)
        self.fail(f"task {task_id} did not reach {expected}")

    def test_uploads_advance_and_empty_docx_blocks(self) -> None:
        with TestClient(create_app(auth_store=self.store, upload_root=self.root / "uploads",
                                   auto_process_docx=True)) as client:
            session = client.post("/api/v1/sessions", json={
                "username": "business1", "password": "synthetic-password",
            })
            headers = {"Authorization": f"Bearer {session.json()['access_token']}"}
            created = []
            for content, expected in ((synthetic_attachment(), "reviewing"),
                                      (empty_docx(), "blocked")):
                response = client.post(
                    "/api/v1/tasks", headers=headers,
                    data={"department": "采购部", "applicant": "演示用户"},
                    files={"file": ("synthetic.docx", content,
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                )
                self.assertEqual(response.status_code, 201, response.text)
                task_id = response.json()["task_id"]
                created.append(task_id)
                state = self.wait_for(task_id, expected)
                self.assertEqual(state["attempt_count"], 1)
                self.assertEqual(self.store.connection.execute(
                    "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,),
                ).fetchone()[0], int(expected == "reviewing"))
                if expected == "blocked":
                    self.assertTrue(state["blocked_code"])
                    self.assertEqual(state["recovery_action"], "replace_attachment")
                else:
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=headers)
                                     .json()["machine_status"], "reviewing")
            other = client.post("/api/v1/sessions", json={
                "username": "business2", "password": "other-synthetic-password",
            })
            other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
            for task_id in created:
                self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other_headers).status_code,
                                 404)

    def test_startup_recovers_expired_attempt_and_keeps_history(self) -> None:
        tasks = TaskStore(self.store, self.root / "uploads")
        tasks.initialize()
        task_id = tasks.create_task(self.actor, "synthetic.docx", synthetic_attachment(),
                                    "采购部", "演示用户")["task_id"]
        old_lease = tasks.jobs.claim_next(file_format="docx")
        self.assertEqual(old_lease.task_id, task_id)
        with self.store.lock, self.store.connection:
            self.store.connection.execute(
                "UPDATE processing_jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' "
                "WHERE task_id = ?", (task_id,),
            )
        with TestClient(create_app(auth_store=self.store, upload_root=self.root / "uploads",
                                   auto_process_docx=True)):
            state = self.wait_for(task_id, "reviewing")
        self.assertEqual(state["attempt_count"], 2)
        outcomes = [row[0] for row in self.store.connection.execute(
            "SELECT outcome FROM processing_attempts WHERE task_id = ? ORDER BY attempt", (task_id,),
        )]
        self.assertEqual(outcomes, ["lease_expired", "completed"])

    def test_worker_leaves_pdf_pending(self) -> None:
        tasks = TaskStore(self.store, self.root / "uploads")
        tasks.initialize()
        task_id = tasks.create_task(self.actor, "synthetic.pdf",
                                    b"%PDF-1.4\nsynthetic\n%%EOF", "采购部", "演示用户")["task_id"]
        with TestClient(create_app(auth_store=self.store, upload_root=self.root / "uploads",
                                   auto_process_docx=True)):
            time.sleep(0.6)
        self.assertEqual(tasks.get_task(task_id, self.actor)["machine_status"], "pending")

    def test_heartbeat_extends_active_lease(self) -> None:
        tasks = TaskStore(self.store, self.root / "uploads")
        tasks.initialize()
        task_id = tasks.create_task(self.actor, "synthetic.docx", synthetic_attachment(),
                                    "采购部", "演示用户")["task_id"]
        lease = tasks.jobs.claim_next(file_format="docx")
        before = self.store.connection.execute(
            "SELECT lease_expires_at FROM processing_jobs WHERE task_id = ?", (task_id,),
        ).fetchone()[0]
        with _renew_lease(tasks.jobs, lease, interval_seconds=0.02):
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                after = self.store.connection.execute(
                    "SELECT lease_expires_at FROM processing_jobs WHERE task_id = ?", (task_id,),
                ).fetchone()[0]
                if after > before:
                    break
                time.sleep(0.01)
        self.assertGreater(after, before)
        self.assertEqual(self.store.connection.execute(
            "SELECT status FROM processing_jobs WHERE task_id = ?", (task_id,),
        ).fetchone()[0], "running")
