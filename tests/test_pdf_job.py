"""Text PDF automatic persistence, access isolation, and recovery smoke."""

import tempfile
import json
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app
from backend.pdf_job import run_pdf_once
from backend.tasks import TaskStore


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class PdfJobTests(unittest.TestCase):
    def test_expired_pdf_lease_recovers_and_changed_original_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(Path(directory) / "jobs.sqlite3")
            try:
                store.initialize()
                owner = store.create_user("owner", "business", "synthetic-password")
                tasks = TaskStore(store, Path(directory) / "uploads")
                tasks.initialize()
                task_id = tasks.create_task(owner, "f2.pdf",
                    (SAMPLES / "f2-text-software-purchase.pdf").read_bytes(), "test", "test")["task_id"]
                lease = tasks.jobs.claim_next(file_format="pdf")
                with store.connection:
                    store.connection.execute("UPDATE processing_jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE task_id = ?", (task_id,))
                tasks.jobs.recover_expired()
                self.assertFalse(tasks.jobs.block_parse(lease, "STALE", "stale"))
                self.assertEqual(run_pdf_once(tasks.jobs)["status"], "reviewing")
                self.assertEqual([r[0] for r in store.connection.execute(
                    "SELECT outcome FROM processing_attempts WHERE task_id = ? ORDER BY attempt", (task_id,))],
                    ["lease_expired", "completed"])
                task_id = tasks.create_task(owner, "changed.pdf",
                    (SAMPLES / "f2-text-software-purchase.pdf").read_bytes(), "test", "test")["task_id"]
                path = store.connection.execute("SELECT file_path FROM document_versions WHERE task_id = ?", (task_id,)).fetchone()[0]
                Path(path).write_bytes(b"%PDF-1.4 changed synthetic bytes")
                self.assertEqual(run_pdf_once(tasks.jobs)["code"], "ATTACHMENT_CHANGED")
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)).fetchone()[0], 0)
            finally:
                store.close()

    def test_pdf_processing_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AuthStore(root / "test.sqlite3")
            store.initialize()
            self.addCleanup(store.close)
            for name, role in (("owner", "business"), ("other", "business"),
                               ("legal", "legal"), ("admin", "admin")):
                store.create_user(name, role, "synthetic-password")
            app = create_app(auth_store=store, upload_root=root / "uploads",
                             auto_process_pdf=True)
            with TestClient(app) as client:
                headers = {}
                for name in ("owner", "other", "legal", "admin"):
                    token = client.post("/api/v1/sessions", json={
                        "username": name, "password": "synthetic-password",
                    }).json()["access_token"]
                    headers[name] = {"Authorization": f"Bearer {token}"}

                def wait(task_id, status):
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        state = client.get(f"/api/v1/tasks/{task_id}", headers=headers["owner"]).json()
                        if state["machine_status"] == status:
                            return state
                        time.sleep(.03)
                    self.fail(f"PDF did not reach {status}: {state}")

                ids = []
                for filename, expected in (("f2-text-software-purchase.pdf", "reviewing"),
                                           ("f5-encrypted.pdf", "blocked")):
                    response = client.post("/api/v1/tasks", headers=headers["owner"],
                        data={"department": "synthetic", "applicant": "synthetic"},
                        files={"file": (filename, (SAMPLES / filename).read_bytes())})
                    self.assertEqual(response.status_code, 201, response.text)
                    task_id = response.json()["task_id"]
                    ids.append(task_id)
                    state = wait(task_id, expected)
                    endpoint = f"/api/v1/tasks/{task_id}/document"
                    for name, status in (("owner", 403), ("other", 404), ("admin", 403)):
                        self.assertEqual(client.get(endpoint, headers=headers[name]).status_code, status)
                    self.assertEqual(client.get(endpoint).status_code, 401)
                    if expected == "blocked":
                        self.assertEqual(state["blocked_code"], "PDF_ENCRYPTED")
                        self.assertEqual(state["recovery_action"], "replace_attachment")
                        self.assertEqual(client.get(endpoint, headers=headers["legal"]).status_code, 409)
                        continue
                    result = client.get(endpoint, headers=headers["legal"])
                    self.assertEqual(result.status_code, 200, result.text)
                    document = result.json()
                    self.assertEqual(document["page_count"], 3)
                    self.assertTrue(document["preview_available"])
                    self.assertEqual(document["structured_extraction_status"], "available")
                    self.assertEqual(document["missing_clause_types"], ["数据安全"])
                    for paragraph in document["paragraphs"]:
                        self.assertEqual(document["normalized_text"][paragraph["start"]:paragraph["end"]], paragraph["quote"])
                        self.assertEqual(paragraph["document_version"], 1)
                        self.assertTrue(paragraph["rects"])
                    self.assertEqual(client.get(endpoint + "?document_version=2", headers=headers["legal"]).status_code, 404)
                    risk = client.get(f"/api/v1/tasks/{task_id}/risks", headers=headers["legal"])
                    self.assertEqual(risk.status_code, 200, risk.text)
                    oracle = json.loads((SAMPLES / "f2_expected.json").read_text(encoding="utf-8"))
                    for field in document["fields"]:
                        expected_page = oracle["field_pages"][field["name"]]
                        if expected_page is None:
                            self.assertIsNone(field["anchor"])
                        else:
                            anchor = field["anchor"]
                            self.assertEqual(anchor["page"], expected_page)
                            self.assertEqual(document["normalized_text"][anchor["start"]:anchor["end"]], anchor["quote"])
                            if not anchor["locatable"]:
                                self.assertEqual(anchor["rects"], [])
                    actual = risk.json()["risks"]
                    self.assertEqual(len(actual), 2)
                    for risk_item, expected_risk in zip(actual, oracle["risks"]):
                        self.assertEqual(risk_item["rule_id"], expected_risk["rule_id"])
                        self.assertEqual([a["page"] for a in risk_item["anchors"]], expected_risk["anchor_pages"])
                        for anchor in risk_item["anchors"]:
                            self.assertTrue(anchor["locatable"])
                            self.assertEqual(document["normalized_text"][anchor["start"]:anchor["end"]], anchor["quote"])
                    for name, status in (("owner", 403), ("other", 404), ("admin", 403)):
                        self.assertEqual(client.get(f"/api/v1/tasks/{task_id}/risks", headers=headers[name]).status_code, status)
                revised = client.post(f"/api/v1/tasks/{ids[1]}/documents", headers=headers["owner"],
                    data={"base_document_version": 1},
                    files={"file": ("replacement.pdf", (SAMPLES / "f2-text-software-purchase.pdf").read_bytes())})
                self.assertEqual(revised.status_code, 201, revised.text)
                wait(ids[1], "reviewing")
                self.assertEqual(client.get(f"/api/v1/tasks/{ids[1]}/document", headers=headers["legal"]).json()["document_version"], 2)
                self.assertEqual(client.get(f"/api/v1/tasks/{ids[1]}/document?document_version=1", headers=headers["legal"]).status_code, 409)
            with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                restored = client.get(f"/api/v1/tasks/{ids[0]}/document", headers=headers["legal"])
                self.assertEqual(restored.json(), document)
            store.close()
