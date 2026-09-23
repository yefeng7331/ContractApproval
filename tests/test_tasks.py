"""High-risk intake checks: ownership, persistence, and immutable input evidence."""

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app
from backend.tasks import MAX_UPLOAD_BYTES, identify_document
from backend.errors import ApiError


def docx_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return stream.getvalue()


class TaskIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "demo.sqlite3"
        self.upload_root = self.root / "uploads"
        self.store = AuthStore(self.database)
        self.store.initialize()
        for name, role in (
            ("business1", "business"),
            ("business2", "business"),
            ("legal1", "legal"),
            ("admin1", "admin"),
        ):
            self.store.create_user(name, role, "sample-test-password")
        self.client = TestClient(
            create_app(auth_store=self.store, upload_root=self.upload_root)
        )
        self.client.__enter__()
        self.tokens = {
            name: self.client.post(
                "/api/v1/sessions",
                json={"username": name, "password": "sample-test-password"},
            ).json()["access_token"]
            for name in ("business1", "business2", "legal1", "admin1")
        }

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.store.close()
        self.temporary.cleanup()

    def headers(self, name: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[name]}"}

    def upload(self, name: str = "business1", filename: str = "sample.pdf", content: bytes = b"%PDF-1.4\n%%EOF"):
        return self.client.post(
            "/api/v1/tasks",
            headers=self.headers(name),
            data={"department": "采购部", "applicant": "张三"},
            files={"file": (filename, content, "application/octet-stream")},
        )

    def test_upload_creates_pending_task_file_hash_and_audit(self) -> None:
        content = b"%PDF-1.4\nsynthetic contract\n%%EOF"
        response = self.upload(filename="合同.pdf", content=content)
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task["document_version"], 1)
        self.assertIsNone(task["review_version"])
        self.assertEqual(
            (task["machine_status"], task["legal_status"], task["writeback_status"]),
            ("pending", "pending", "not_written"),
        )
        self.assertEqual(task["submission"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(task["submission"]["filename"], "合同.pdf")
        row = self.store.connection.execute(
            "SELECT file_path, sha256 FROM document_versions WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()
        self.assertEqual(Path(row["file_path"]).read_bytes(), content)
        self.assertFalse(Path(str(row["file_path"]) + ".part").exists())
        self.assertEqual(row["sha256"], task["submission"]["sha256"])
        audit = self.store.connection.execute(
            "SELECT action, actor_user_id, document_version, created_at FROM audit_events WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()
        self.assertEqual(audit["action"], "task_created")
        self.assertEqual(audit["document_version"], 1)
        owner_id = self.store.connection.execute(
            "SELECT id FROM users WHERE username = 'business1'"
        ).fetchone()[0]
        self.assertEqual(audit["actor_user_id"], owner_id)
        self.assertTrue(audit["created_at"])

    def test_ownership_and_admin_visibility(self) -> None:
        task_id = self.upload().json()["task_id"]
        own = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers("business1"))
        self.assertEqual(own.status_code, 200)
        other = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers("business2"))
        self.assertEqual(other.status_code, 404)
        own_list = self.client.get("/api/v1/tasks", headers=self.headers("business1")).json()
        other_list = self.client.get("/api/v1/tasks", headers=self.headers("business2")).json()
        self.assertEqual(own_list["total"], 1)
        self.assertEqual(other_list, {"items": [], "total": 0})
        legal = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers("legal1"))
        self.assertEqual(legal.status_code, 200)
        admin = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers("admin1"))
        self.assertEqual(admin.status_code, 200)
        self.assertNotIn("submission", admin.json())
        for role in ("legal1", "admin1"):
            self.assertEqual(self.upload(role).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/tasks").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/tasks").status_code, 401)

    def test_bad_inputs_do_not_create_tasks(self) -> None:
        for filename, content, expected in (
            ("bad.exe", b"executable", 415),
            ("bad.pdf", b"not a pdf", 422),
            ("empty.pdf", b"", 422),
            ("bad.docx", b"PKnotzip", 422),
        ):
            with self.subTest(filename=filename):
                response = self.upload(filename=filename, content=content)
                self.assertEqual(response.status_code, expected, response.text)
        self.assertEqual(
            self.client.get("/api/v1/tasks", headers=self.headers("business1")).json()["total"],
            0,
        )
        with self.assertRaises(ApiError) as caught:
            identify_document("large.pdf", b"%PDF-" + b"x" * MAX_UPLOAD_BYTES)
        self.assertEqual(caught.exception.status_code, 413)

    def test_docx_and_filename_cannot_choose_storage_path(self) -> None:
        response = self.upload(filename="../../agreement.docx", content=docx_bytes())
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task["submission"]["filename"], "agreement.docx")
        row = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task["task_id"],)
        ).fetchone()
        self.assertEqual(Path(row["file_path"]).parent, self.upload_root / task["task_id"])

    def test_task_survives_store_restart_and_list_filter(self) -> None:
        task_id = self.upload().json()["task_id"]
        self.assertEqual(
            self.client.get(
                "/api/v1/tasks?machine_status=blocked", headers=self.headers("business1")
            ).json()["total"],
            0,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/tasks?machine_status=pending&legal_status=pending&writeback_status=not_written",
                headers=self.headers("business1"),
            ).json()["total"],
            1,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/tasks?limit=1&offset=1", headers=self.headers("business1")
            ).json(),
            {"items": [], "total": 1},
        )
        self.client.__exit__(None, None, None)
        self.store.close()
        reopened = AuthStore(self.database)
        try:
            reopened.initialize()
            row = reopened.connection.execute(
                "SELECT machine_status, current_document_version FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual((row["machine_status"], row["current_document_version"]), ("pending", 1))
        finally:
            reopened.close()
        self.store = AuthStore(self.database)
        self.client = TestClient(create_app(auth_store=self.store, upload_root=self.upload_root))
        self.client.__enter__()
        relogin = self.client.post(
            "/api/v1/sessions",
            json={"username": "business1", "password": "sample-test-password"},
        )
        self.assertEqual(relogin.status_code, 200)
        reloaded = self.client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {relogin.json()['access_token']}"},
        )
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["document_version"], 1)


if __name__ == "__main__":
    unittest.main()
