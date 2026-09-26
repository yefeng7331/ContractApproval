"""Standalone legal snapshot API smoke; synthetic files and a temporary database."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.main import create_app
from backend.pdf_job import run_pdf_once
from backend.tasks import TaskStore


class RuleSnapshotApiTests(unittest.TestCase):
    def test_saved_drafts_permissions_versions_and_integrity(self):
        samples = Path(__file__).resolve().parents[1] / "samples"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AuthStore(root / "test.sqlite3")
            try:
                store.initialize()
                users = {name: store.create_user(name, role, "synthetic-password")
                         for name, role in (("owner", "business"), ("other", "business"),
                                            ("legal", "legal"), ("admin", "admin"))}
                tasks = TaskStore(store, root / "uploads")
                tasks.initialize()
                app = create_app(auth_store=store, upload_root=root / "uploads")
                with TestClient(app) as client:
                    headers = {name: {"Authorization": "Bearer " + client.post(
                        "/api/v1/sessions", json={"username": name, "password": "synthetic-password"}
                    ).json()["access_token"]} for name in users}
                    for filename, run_once in (("f1-software-purchase.docx", run_docx_once),
                                               ("f2-text-software-purchase.pdf", run_pdf_once)):
                        with self.subTest(filename=filename):
                            content = (samples / filename).read_bytes()
                            task_id = tasks.create_task(users["owner"], filename, content, "test", "test")["task_id"]
                            url = f"/api/v1/tasks/{task_id}/risks/snapshot"

                            def read(suffix=""):
                                return client.get(url + suffix, headers=headers["legal"])

                            self.assertEqual(client.get(url).status_code, 401)
                            for role, status in (("owner", 403), ("other", 404), ("admin", 403)):
                                self.assertEqual(client.get(url, headers=headers[role]).status_code, status)
                            self.assertEqual(read().status_code, 409)
                            self.assertEqual(read("?document_version=9").status_code, 404)
                            self.assertEqual(read("?document_version=0").status_code, 422)
                            self.assertEqual(run_once(tasks.jobs)["status"], "reviewing")
                            self.assertEqual(read().json()["code"], "RULE_SNAPSHOT_NOT_READY")
                            saved = tasks.rule_snapshots.persist(task_id, 1)
                            self.assertEqual(saved["operation"], "created")
                            changes = store.connection.total_changes
                            # A persisted read must not run current rules or invoke the writer.
                            with patch("backend.tasks.evaluate_persisted_rule_evidence", side_effect=AssertionError), \
                                 patch("backend.rule_snapshot.evaluate_persisted_rule_evidence", side_effect=AssertionError), \
                                 patch("backend.rule_snapshot.RuleSnapshotStore.persist", side_effect=AssertionError):
                                response = read()
                            self.assertEqual(response.status_code, 200, response.text)
                            result = response.json()
                            self.assertEqual(len(result["risks"]), 2)
                            self.assertEqual(result["risks"], saved["risks"])
                            self.assertTrue(result["persisted"])
                            self.assertIsNone(result["review_version"])
                            self.assertTrue(result["created_at"])
                            self.assertEqual(len(result["evidence_sha256"]), 64)
                            self.assertEqual(store.connection.total_changes, changes)
                            for role, status in (("owner", 403), ("other", 404), ("admin", 403)):
                                self.assertEqual(client.get(url, headers=headers[role]).status_code, status)
                            immediate = client.get(f"/api/v1/tasks/{task_id}/risks", headers=headers["legal"]).json()
                            self.assertFalse(immediate["persisted"])
                            with patch("backend.rule_snapshot.RULE_VERSION", "future-rule"):
                                historical = read().json()
                                self.assertFalse(historical["rule_version_current"])
                                self.assertEqual(historical["risks"], result["risks"])
                            # Legal confirmation is not implemented; seed the replacement prerequisite.
                            with store.connection:
                                store.connection.execute(
                                    "UPDATE tasks SET machine_status = 'completed', legal_status = 'confirmed' WHERE id = ?", (task_id,))
                            tasks.add_document_version(task_id, users["owner"], 1, filename, content)
                            self.assertEqual(read().status_code, 409)
                            self.assertEqual(read("?document_version=1").json(), result)
                            self.assertEqual(run_once(tasks.jobs)["status"], "reviewing")
                            self.assertEqual(read().json()["code"], "RULE_SNAPSHOT_NOT_READY")
                            self.assertEqual(tasks.rule_snapshots.persist(task_id, 2)["operation"], "created")
                            self.assertEqual(read().json()["document_version"], 2)
                            self.assertEqual(read("?document_version=1").json(), result)
                            row = store.connection.execute(
                                "SELECT snapshot_json FROM rule_draft_snapshots WHERE task_id = ? AND document_version = 1",
                                (task_id,),
                            ).fetchone()
                            wrong_version = json.loads(row[0])
                            wrong_version["document_version"] = 2
                            wrong_anchor = json.loads(row[0])
                            wrong_anchor["risks"][0]["anchors"][0]["quote"] = "wrong source"
                            for broken in ("{", "[]", "{}", json.dumps(wrong_version), json.dumps(wrong_anchor)):
                                with store.connection:
                                    store.connection.execute(
                                        "UPDATE rule_draft_snapshots SET snapshot_json = ? WHERE task_id = ? AND document_version = 1",
                                        (broken, task_id))
                                self.assertEqual(read("?document_version=1").json()["code"], "RULE_SNAPSHOT_INVALID")
                            with store.connection:
                                store.connection.execute(
                                    "UPDATE rule_draft_snapshots SET snapshot_json = ? WHERE task_id = ? AND document_version = 1",
                                    (row[0], task_id))
                                store.connection.execute(
                                    "UPDATE parsed_documents SET normalized_text = normalized_text || 'changed' WHERE task_id = ? AND document_version = 2",
                                    (task_id,))
                            self.assertEqual(read().json()["code"], "RULE_EVIDENCE_CHANGED")
                            self.assertEqual(read("?document_version=1").json(), result)
                            self.assertEqual(tasks.get_task(task_id, users["legal"])["machine_status"], "reviewing")
                    clean_id = tasks.create_task(users["owner"], "f4.docx",
                        (samples / "f4-revised-software-purchase.docx").read_bytes(), "test", "test")["task_id"]
                    self.assertEqual(run_docx_once(tasks.jobs)["status"], "reviewing")
                    self.assertEqual(tasks.rule_snapshots.persist(clean_id, 1)["operation"], "created")
                    clean = client.get(f"/api/v1/tasks/{clean_id}/risks/snapshot", headers=headers["legal"])
                    self.assertEqual(clean.status_code, 200, clean.text)
                    self.assertEqual(clean.json()["risks"], [])
                    self.assertEqual(client.get("/api/v1/tasks/missing/risks/snapshot",
                                                headers=headers["legal"]).status_code, 404)
                # A new application and connection read the identical durable historical result.
                reopened = AuthStore(root / "test.sqlite3")
                try:
                    with TestClient(create_app(auth_store=reopened, upload_root=root / "uploads")) as client:
                        self.assertEqual(client.get(url + "?document_version=1", headers=headers["legal"]).json(), result)
                finally:
                    reopened.close()
            finally:
                store.close()
