"""High-risk intake checks: ownership, persistence, and immutable input evidence."""

import hashlib
import io
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app
from backend.mock_pending import MOCK_PENDING_ID, synthetic_attachment
from backend.tasks import MAX_UPLOAD_BYTES, TaskStore, identify_document
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

    def replace_document(
        self,
        task_id: str,
        name: str = "business1",
        base_version: int = 1,
        filename: str = "revision.pdf",
        content: bytes = b"%PDF-1.4\nrevised synthetic contract\n%%EOF",
    ):
        return self.client.post(
            f"/api/v1/tasks/{task_id}/documents",
            headers=self.headers(name),
            data={"base_document_version": base_version},
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

    def test_mock_pending_import_creates_persistent_owned_task(self) -> None:
        listing = self.client.get("/api/v1/mock-pending", headers=self.headers("business1"))
        self.assertEqual(listing.status_code, 200)
        pending = listing.json()["items"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], MOCK_PENDING_ID)
        self.assertTrue(pending[0]["synthetic"])

        # Pin the fetched bytes: separate DOCX builds may have different ZIP timestamps.
        content = synthetic_attachment()
        with patch("backend.main.fetch_pending_attachment", return_value=content):
            response = self.client.post(
                f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import",
                headers=self.headers("business1"),
            )
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task["source"], "mock_pending")
        self.assertEqual(task["mock_approval_id"], MOCK_PENDING_ID)
        self.assertEqual(task["document_version"], 1)
        self.assertEqual(
            (task["machine_status"], task["legal_status"], task["writeback_status"]),
            ("pending", "pending", "not_written"),
        )
        self.assertEqual(task["submission"]["department"], pending[0]["department"])
        self.assertEqual(task["submission"]["applicant"], pending[0]["applicant"])
        self.assertEqual(task["submission"]["sha256"], hashlib.sha256(content).hexdigest())
        row = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task["task_id"],)
        ).fetchone()
        self.assertEqual(Path(row["file_path"]).read_bytes(), content)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            document_xml = ElementTree.fromstring(archive.read("word/document.xml"))
            ElementTree.fromstring(archive.read("[Content_Types].xml"))
            ElementTree.fromstring(archive.read("_rels/.rels"))
            self.assertIn("合成软件采购合同", "".join(document_xml.itertext()))
        audit = self.store.connection.execute(
            "SELECT action, document_version FROM audit_events WHERE task_id = ? ORDER BY id",
            (task["task_id"],),
        ).fetchall()
        self.assertEqual(
            [(row["action"], row["document_version"]) for row in audit],
            [("attachment_fetch_started", 1), ("mock_pending_imported", 1)],
        )

        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{task['task_id']}", headers=self.headers("business2")).status_code,
            404,
        )
        admin = self.client.get(f"/api/v1/tasks/{task['task_id']}", headers=self.headers("admin1"))
        self.assertEqual(admin.status_code, 200)
        self.assertNotIn("submission", admin.json())
        self.assertNotIn("mock_approval_id", admin.json())
        second = self.client.post(
            f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import",
            headers=self.headers("business1"),
        )
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(second.json()["task_id"], task["task_id"])
        self.assertEqual(
            self.client.get("/api/v1/tasks", headers=self.headers("business1")).json()["total"],
            2,
        )

        self.client.__exit__(None, None, None)
        self.store.close()
        self.store = AuthStore(self.database)
        self.client = TestClient(create_app(auth_store=self.store, upload_root=self.upload_root))
        self.client.__enter__()
        relogin = self.client.post(
            "/api/v1/sessions",
            json={"username": "business1", "password": "sample-test-password"},
        ).json()
        reloaded = self.client.get(
            f"/api/v1/tasks/{task['task_id']}",
            headers={"Authorization": f"Bearer {relogin['access_token']}"},
        )
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["mock_approval_id"], MOCK_PENDING_ID)

    def test_mock_pending_rejects_other_roles_and_unknown_item(self) -> None:
        self.assertEqual(self.client.get("/api/v1/mock-pending").status_code, 401)
        self.assertEqual(
            self.client.post(f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import").status_code,
            401,
        )
        for role in ("legal1", "admin1"):
            self.assertEqual(
                self.client.get("/api/v1/mock-pending", headers=self.headers(role)).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import",
                    headers=self.headers(role),
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/mock-pending/unknown/import", headers=self.headers("business1")
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/v1/tasks", headers=self.headers("business1")).json()["total"],
            0,
        )

    def test_blocked_task_replacement_preserves_old_evidence_and_resets_current_state(self) -> None:
        original = b"%PDF-1.4\nold synthetic contract\n%%EOF"
        task_id = self.upload(content=original).json()["task_id"]
        with self.store.connection:
            self.store.connection.execute(
                """UPDATE tasks SET machine_status = 'blocked', blocked_code = 'EMPTY_TEXT',
                    blocked_reason = '正文为空', recovery_action = 'replace_attachment',
                    attempt_count = 2 WHERE id = ?""",
                (task_id,),
            )
        replacement = b"%PDF-1.4\nnew synthetic contract\n%%EOF"
        response = self.replace_document(task_id, filename="修订.pdf", content=replacement)
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task["document_version"], 2)
        self.assertIsNone(task["review_version"])
        self.assertEqual(
            (task["machine_status"], task["legal_status"], task["writeback_status"]),
            ("pending", "pending", "not_written"),
        )
        self.assertIsNone(task["blocked_code"])
        self.assertIsNone(task["recovery_action"])
        self.assertEqual(task["attempt_count"], 0)
        self.assertEqual(task["submission"]["filename"], "修订.pdf")
        self.assertEqual(task["submission"]["sha256"], hashlib.sha256(replacement).hexdigest())
        versions = self.store.connection.execute(
            "SELECT version, file_path, sha256 FROM document_versions WHERE task_id = ? ORDER BY version",
            (task_id,),
        ).fetchall()
        self.assertEqual([row["version"] for row in versions], [1, 2])
        self.assertEqual(Path(versions[0]["file_path"]).read_bytes(), original)
        self.assertEqual(Path(versions[1]["file_path"]).read_bytes(), replacement)
        self.assertEqual(versions[0]["sha256"], hashlib.sha256(original).hexdigest())
        history = self.store.connection.execute(
            """SELECT machine_status, blocked_code, blocked_reason, recovery_action, attempt_count
            FROM document_state_history WHERE task_id = ? AND version = 1""",
            (task_id,),
        ).fetchone()
        self.assertEqual(
            tuple(history),
            ("blocked", "EMPTY_TEXT", "正文为空", "replace_attachment", 2),
        )
        audit = self.store.connection.execute(
            "SELECT action, actor_user_id, document_version FROM audit_events WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        owner_id = self.store.connection.execute(
            "SELECT id FROM users WHERE username = 'business1'"
        ).fetchone()[0]
        self.assertEqual(tuple(audit), ("document_version_created", owner_id, 2))
        self.assertEqual(self.replace_document(task_id).status_code, 409)

        self.client.__exit__(None, None, None)
        self.store.close()
        self.store = AuthStore(self.database)
        self.client = TestClient(create_app(auth_store=self.store, upload_root=self.upload_root))
        self.client.__enter__()
        relogin = self.client.post(
            "/api/v1/sessions",
            json={"username": "business1", "password": "sample-test-password"},
        ).json()
        reloaded = self.client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {relogin['access_token']}"},
        )
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["document_version"], 2)
        self.assertEqual(reloaded.json()["machine_status"], "pending")

    def test_document_replacement_rejects_wrong_role_owner_state_and_version(self) -> None:
        task_id = self.upload().json()["task_id"]
        pending = self.replace_document(task_id)
        self.assertEqual((pending.status_code, pending.json()["code"]), (409, "TASK_STATE_CONFLICT"))
        self.assertEqual(pending.json()["task_id"], task_id)
        self.assertEqual(pending.json()["current_status"]["document_version"], 1)
        self.assertEqual(pending.json()["current_status"]["machine_status"], "pending")
        other = self.replace_document(task_id, name="business2")
        self.assertEqual(other.status_code, 404)
        self.assertNotIn("current_status", other.json())
        self.assertNotIn("task_id", other.json())
        self.assertEqual(self.replace_document(task_id, name="legal1").status_code, 403)
        self.assertEqual(self.replace_document(task_id, name="admin1").status_code, 403)
        self.assertEqual(
            self.client.post(f"/api/v1/tasks/{task_id}/documents").status_code, 401
        )
        with self.store.connection:
            self.store.connection.execute(
                """UPDATE tasks SET machine_status = 'blocked',
                    recovery_action = 'admin_retry' WHERE id = ?""",
                (task_id,),
            )
        self.assertEqual(self.replace_document(task_id).status_code, 409)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET recovery_action = 'replace_attachment' WHERE id = ?",
                (task_id,),
            )
        stale = self.replace_document(task_id, base_version=2)
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "DOCUMENT_VERSION_CONFLICT"))
        self.assertEqual(stale.json()["task_id"], task_id)
        self.assertEqual(stale.json()["current_status"]["document_version"], 1)
        self.assertEqual(stale.json()["current_status"]["machine_status"], "blocked")
        self.assertEqual(stale.json()["current_status"]["recovery_action"], "replace_attachment")
        invalid = self.replace_document(task_id, filename="bad.exe", content=b"invalid")
        self.assertEqual(invalid.status_code, 415)
        self.assertEqual(self.replace_document("missing").status_code, 404)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM document_versions WHERE task_id = ?", (task_id,)
            ).fetchone()[0],
            1,
        )

    def test_failed_upload_removes_only_unregistered_attachment(self) -> None:
        self.store.connection.execute(
            "CREATE TRIGGER fail_new_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.upload()
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0], 0
        )
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0], 0
        )
        self.assertEqual(list(self.upload_root.iterdir()), [])

    def test_failed_replacement_preserves_old_evidence_and_state(self) -> None:
        task_id = self.upload().json()["task_id"]
        old_path = Path(self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (task_id,)
        ).fetchone()["file_path"])
        old_content = old_path.read_bytes()
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', recovery_action = 'replace_attachment' "
                "WHERE id = ?", (task_id,),
            )
        self.store.connection.execute(
            "CREATE TRIGGER fail_new_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.replace_document(task_id)
        self.assertEqual(list(old_path.parent.iterdir()), [old_path])
        self.assertEqual(old_path.read_bytes(), old_content)
        row = self.store.connection.execute(
            "SELECT current_document_version, machine_status, recovery_action FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        self.assertEqual(tuple(row), (1, "blocked", "replace_attachment"))
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM document_versions WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM document_state_history WHERE task_id = ?", (task_id,)
        ).fetchone()[0], 0)
        self.assertEqual(self.store.connection.execute(
            "SELECT document_version, status FROM processing_jobs WHERE task_id = ?", (task_id,)
        ).fetchall()[0]["status"], "pending")

    def test_confirmed_mock_task_can_start_new_document_version(self) -> None:
        imported = self.client.post(
            f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import",
            headers=self.headers("business1"),
        ).json()
        task_id = imported["task_id"]
        with self.store.connection:
            self.store.connection.execute(
                """UPDATE tasks SET machine_status = 'completed', legal_status = 'confirmed',
                    writeback_status = 'success', current_review_version = 3 WHERE id = ?""",
                (task_id,),
            )
        response = self.replace_document(task_id)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["source"], "mock_pending")
        self.assertEqual(result["mock_approval_id"], MOCK_PENDING_ID)
        self.assertEqual(result["document_version"], 2)
        self.assertIsNone(result["review_version"])
        history = self.store.connection.execute(
            """SELECT review_version, legal_status, writeback_status
            FROM document_state_history WHERE task_id = ? AND version = 1""",
            (task_id,),
        ).fetchone()
        self.assertEqual(tuple(history), (3, "confirmed", "success"))

    def test_existing_task_database_gains_mock_id_without_losing_rows(self) -> None:
        legacy = AuthStore(self.root / "legacy.sqlite3")
        try:
            legacy.initialize()
            legacy.create_user("legacy_business", "business", "sample-test-password")
            legacy.connection.execute(
                """CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL REFERENCES users(id),
                    source TEXT NOT NULL,
                    department TEXT NOT NULL,
                    applicant TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    current_document_version INTEGER NOT NULL,
                    current_review_version INTEGER,
                    machine_status TEXT NOT NULL,
                    legal_status TEXT NOT NULL,
                    writeback_status TEXT NOT NULL,
                    blocked_code TEXT,
                    blocked_reason TEXT,
                    recovery_action TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0
                )"""
            )
            legacy.connection.execute(
                """INSERT INTO tasks
                (id, owner_user_id, source, department, applicant, created_at,
                 current_document_version, machine_status, legal_status, writeback_status)
                VALUES ('legacy-task', 1, 'upload', '采购部', '张三', '2026-09-23',
                        1, 'pending', 'pending', 'not_written')"""
            )
            TaskStore(legacy, self.root / "legacy-uploads").initialize()
            row = legacy.connection.execute(
                "SELECT id, mock_approval_id FROM tasks WHERE id = 'legacy-task'"
            ).fetchone()
            self.assertEqual((row["id"], row["mock_approval_id"]), ("legacy-task", None))
        finally:
            legacy.close()


if __name__ == "__main__":
    unittest.main()
