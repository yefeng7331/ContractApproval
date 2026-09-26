"""Independent HTTP smoke for same-version F2 PDF preview access."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app
from backend.mock_pending import synthetic_attachment


F2 = Path(__file__).resolve().parents[1] / "samples" / "f2-text-software-purchase.pdf"


class PdfPreviewSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = AuthStore(self.root / "smoke.sqlite3")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.client = TestClient(create_app(auth_store=self.store, upload_root=self.root / "uploads"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, name: str, role: str) -> dict[str, str]:
        self.store.create_user(name, role, "synthetic-password")
        response = self.client.post("/api/v1/sessions", json={
            "username": name, "password": "synthetic-password",
        })
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_f2_pdf_preview_smoke(self) -> None:
        owner = self.login("owner", "business")
        other = self.login("other", "business")
        legal = self.login("legal", "legal")
        admin = self.login("admin", "admin")
        original = F2.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         "1e57bd776b26e4b8529edecabb90fdf56c523d3bd77c530698df692b8842e98c")
        uploaded = self.client.post(
            "/api/v1/tasks", headers=owner,
            data={"department": "采购部", "applicant": "合成用户"},
            files={"file": ("f2.pdf", original, "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        task_id = uploaded.json()["task_id"]
        endpoint = f"/api/v1/tasks/{task_id}/document/preview"
        preview = self.client.get(endpoint, headers=legal)
        self.assertEqual(preview.status_code, 200, preview.text[:100])
        self.assertEqual(preview.content, original)
        self.assertEqual(preview.headers["content-type"], "application/pdf")
        self.assertEqual(preview.headers["cache-control"], "private, no-store")
        self.assertEqual(preview.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(endpoint, headers=owner).status_code, 403)
        self.assertEqual(self.client.get(endpoint, headers=other).status_code, 404)
        self.assertEqual(self.client.get(endpoint, headers=admin).status_code, 403)
        self.assertEqual(self.client.get(endpoint, headers=legal,
                                         params={"document_version": 2}).status_code, 404)
        self.assertEqual(self.client.get(endpoint, headers=legal,
                                         params={"document_version": 0}).status_code, 422)

        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', blocked_code = 'SYNTHETIC', "
                "recovery_action = 'replace_attachment' WHERE id = ?", (task_id,),
            )
        revised = original + b"\n%synthetic revision\n"
        replacement = self.client.post(
            f"/api/v1/tasks/{task_id}/documents", headers=owner,
            data={"base_document_version": "1"},
            files={"file": ("f2-revised.pdf", revised, "application/pdf")},
        )
        self.assertEqual(replacement.status_code, 201, replacement.text)
        self.assertEqual(self.client.get(endpoint, headers=legal).content, revised)
        self.assertEqual(self.client.get(endpoint, headers=legal,
                                         params={"document_version": 1}).content, original)

        path = Path(self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ? AND version = 2",
            (task_id,),
        ).fetchone()[0])
        path.write_bytes(b"%PDF-tampered")
        damaged = self.client.get(endpoint, headers=legal)
        self.assertEqual((damaged.status_code, damaged.json()["code"]),
                         (409, "PREVIEW_UNAVAILABLE"))
        self.assertEqual(self.client.get(endpoint, headers=legal,
                                         params={"document_version": 1}).content, original)
        outside = self.root / "outside.pdf"
        outside.write_bytes(revised)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE document_versions SET file_path = ? WHERE task_id = ? AND version = 2",
                (str(outside), task_id),
            )
        escaped = self.client.get(endpoint, headers=legal)
        self.assertEqual((escaped.status_code, escaped.json()["code"]),
                         (409, "PREVIEW_UNAVAILABLE"))

        docx = self.client.post(
            "/api/v1/tasks", headers=owner,
            data={"department": "采购部", "applicant": "合成用户"},
            files={"file": ("f1.docx", synthetic_attachment())},
        )
        self.assertEqual(docx.status_code, 201)
        unavailable = self.client.get(
            f"/api/v1/tasks/{docx.json()['task_id']}/document/preview", headers=legal,
        )
        self.assertEqual((unavailable.status_code, unavailable.json()["code"]),
                         (409, "DOCUMENT_NOT_READY"))


if __name__ == "__main__":
    unittest.main()
