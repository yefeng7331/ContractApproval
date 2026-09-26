"""Automatic local rule stage, rollback recovery and administrator retry smoke."""

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.errors import ApiError
from backend.main import create_app
from backend.tasks import TaskStore


class RuleProcessingTests(unittest.TestCase):
    def test_automatic_rules_and_recovery(self):
        samples = Path(__file__).resolve().parents[1] / "samples"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AuthStore(root / "test.sqlite3")
            try:
                store.initialize()
                users = {name: store.create_user(name, role, "synthetic-password") for name, role in (
                    ("owner", "business"), ("legal", "legal"), ("admin", "admin"))}
                tasks = TaskStore(store, root / "uploads")
                tasks.initialize()
                rules = tasks.rule_snapshots
                def new_task():
                    task_id = tasks.create_task(users["owner"], "f1.docx",
                        (samples / "f1-software-purchase.docx").read_bytes(), "test", "test")["task_id"]
                    self.assertEqual(run_docx_once(tasks.jobs)["status"], "reviewing")
                    return task_id

                task_id = new_task()
                original = rules._persist
                def interrupted(*args):
                    original(*args)
                    raise KeyboardInterrupt("synthetic interruption after snapshot insert")
                with patch.object(rules, "_persist", side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        rules.run_next()
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM rule_draft_snapshots").fetchone()[0], 0)
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM rule_processing_attempts").fetchone()[0], 0)
                second = AuthStore(root / "test.sqlite3")
                try:
                    second.initialize()
                    restored = TaskStore(second, root / "uploads")
                    restored.initialize()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(lambda processor: processor.run_next(), [rules, restored.rule_snapshots]))
                    self.assertEqual(sorted(r["status"] for r in results), ["completed", "no_pending_rules"])
                finally:
                    second.close()
                self.assertEqual(tasks.get_task(task_id, users["legal"])["machine_status"], "reviewing")
                self.assertEqual(len(tasks.get_rule_snapshot(task_id, users["legal"])["risks"]), 2)

                failure_id = new_task()
                with patch.object(rules, "_persist", side_effect=RuntimeError("synthetic failure")):
                    self.assertEqual(rules.run_next()["code"], "RULE_PROCESSING_FAILED")
                self.assertEqual(tasks.get_task(failure_id, users["owner"])["recovery_action"], "admin_retry")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    headers = {name: {"Authorization": "Bearer " + client.post("/api/v1/sessions", json={
                        "username": name, "password": "synthetic-password"}).json()["access_token"]} for name in users}
                    url = f"/api/v1/tasks/{failure_id}/retry"
                    self.assertEqual(client.post(url, json={"document_version": 1}).status_code, 401)
                    for role in ("owner", "legal"):
                        self.assertEqual(client.post(url, headers=headers[role], json={"document_version": 1}).status_code, 403)
                    self.assertEqual(client.post(url, headers=headers["admin"], json={"document_version": 0}).status_code, 422)
                    self.assertEqual(client.post(url, headers=headers["admin"], json={"document_version": 2}).status_code, 409)
                    response = client.post(url, headers=headers["admin"], json={"document_version": 1})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["attempt"], 2)
                    self.assertEqual(client.post(url, headers=headers["admin"], json={"document_version": 1}).status_code, 409)
                restarted = AuthStore(root / "test.sqlite3")
                try:
                    restarted.initialize()
                    resumed = TaskStore(restarted, root / "uploads")
                    resumed.initialize()
                    self.assertEqual(resumed.rule_snapshots.run_next()["status"], "completed")
                finally:
                    restarted.close()
                self.assertEqual([r[0] for r in store.connection.execute(
                    "SELECT outcome FROM rule_processing_attempts WHERE task_id = ? ORDER BY attempt", (failure_id,))],
                    ["blocked", "completed"])
                self.assertEqual(store.connection.execute(
                    "SELECT COUNT(*) FROM audit_events WHERE task_id = ? AND action = 'rule_retry_requested'", (failure_id,)).fetchone()[0], 1)

                damaged_id = new_task()
                with store.connection:
                    store.connection.execute("UPDATE parsed_documents SET clauses_json = 'invalid' WHERE task_id = ?", (damaged_id,))
                self.assertEqual(rules.run_next()["code"], "RULE_EVIDENCE_INVALID")
                self.assertEqual(tasks.get_task(damaged_id, users["owner"])["recovery_action"], "replace_attachment")
                with self.assertRaises(ApiError) as rejected:
                    rules.retry(damaged_id, 1, users["admin"])
                self.assertEqual(rejected.exception.code, "TASK_STATE_CONFLICT")
                self.assertEqual(store.connection.execute(
                    "SELECT COUNT(*) FROM rule_draft_snapshots WHERE task_id = ?", (damaged_id,)).fetchone()[0], 0)

                changed_id = new_task()
                rules.persist(changed_id, 1)
                with store.connection:
                    store.connection.execute("UPDATE parsed_documents SET normalized_text = normalized_text || 'changed' WHERE task_id = ?", (changed_id,))
                self.assertEqual(rules.run_next()["code"], "RULE_EVIDENCE_CHANGED")
                self.assertEqual(rules.run_next()["status"], "no_pending_rules")

                stale_id = new_task()
                with store.connection:
                    store.connection.execute("UPDATE tasks SET machine_status = 'blocked', recovery_action = 'replace_attachment' WHERE id = ?", (stale_id,))
                    store.connection.execute(
                        "INSERT INTO rule_processing_attempts VALUES (?, 1, 1, 'pending', NULL, 'synthetic', NULL)", (stale_id,))
                tasks.add_document_version(stale_id, users["owner"], 1, "f4.docx",
                    (samples / "f4-revised-software-purchase.docx").read_bytes())
                self.assertEqual(rules.run_next()["status"], "no_pending_rules")
                self.assertEqual(store.connection.execute(
                    "SELECT outcome FROM rule_processing_attempts WHERE task_id = ?", (stale_id,)).fetchone()[0], "superseded")
                self.assertEqual(store.connection.execute(
                    "SELECT COUNT(*) FROM rule_draft_snapshots WHERE task_id = ?", (stale_id,)).fetchone()[0], 0)

                # Actual service lifecycle: upload -> parse -> durable rules -> legal read.
                app = create_app(auth_store=store, upload_root=root / "uploads", auto_process_docx=True,
                                 auto_process_pdf=True, auto_process_rules=True)
                with TestClient(app) as client:
                    for filename, count in (("f1-software-purchase.docx", 2),
                                            ("f2-text-software-purchase.pdf", 2),
                                            ("f4-revised-software-purchase.docx", 0)):
                        uploaded = client.post("/api/v1/tasks", headers=headers["owner"],
                            data={"department": "test", "applicant": "test"},
                            files={"file": (filename, (samples / filename).read_bytes())})
                        self.assertEqual(uploaded.status_code, 201)
                        uploaded_id = uploaded.json()["task_id"]
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            response = client.get(f"/api/v1/tasks/{uploaded_id}/risks/snapshot", headers=headers["legal"])
                            if response.status_code == 200:
                                break
                            time.sleep(.03)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(len(response.json()["risks"]), count)
                        self.assertTrue(response.json()["persisted"])
                        state = client.get(f"/api/v1/tasks/{uploaded_id}", headers=headers["owner"]).json()
                        self.assertEqual(state["machine_status"], "reviewing")
                        self.assertEqual(state["legal_status"], "pending")
                        self.assertIsNone(state["review_version"])
            finally:
                store.close()
