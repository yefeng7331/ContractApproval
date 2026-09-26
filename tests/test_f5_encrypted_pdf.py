"""Independent F5 password-protected fixture smoke; uses temporary API data."""

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


class EncryptedPdfSmokeTests(unittest.TestCase):
    def test_f5_encrypted_pdf_fixed_sample_smoke(self) -> None:
        # Missing fixture tooling fails explicitly, rather than skipping evidence.
        sys.path.insert(0, str(ROOT / ".tools" / "pdf-fixtures"))
        try:
            from pypdf import PdfReader
            from pypdf.errors import FileNotDecryptedError
        finally:
            sys.path.pop(0)
        oracle = json.loads((SAMPLES / "f5_encrypted_expected.json").read_text(encoding="utf-8"))
        self.assertEqual((oracle["schema_version"], oracle["sample_id"]), (1, "F5-encrypted-pdf"))
        content = (SAMPLES / oracle["file"]).read_bytes()
        source = (SAMPLES / oracle["source_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        self.assertEqual(hashlib.sha256(source).hexdigest(), oracle["source_sha256"])
        for password in ("", "wrong-password"):
            reader = PdfReader(io.BytesIO(content))
            self.assertTrue(reader.is_encrypted)
            self.assertEqual(reader.decrypt(password), 0)
            with self.assertRaises(FileNotDecryptedError):
                len(reader.pages)

        f1 = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        f2 = json.loads((SAMPLES / "f2_expected.json").read_text(encoding="utf-8"))
        original = PdfReader(io.BytesIO(source))
        self.assertEqual(oracle["page_count"], 3)
        self.assertEqual(oracle["encryption"], "RC4-128")
        for key in ("public_test_user_password", "public_test_owner_password"):
            reader = PdfReader(io.BytesIO(content))
            self.assertNotEqual(reader.decrypt(oracle[key]), 0)
            self.assertEqual(len(reader.pages), 3)
            for index, page in enumerate(reader.pages):
                self.assertEqual(page.get_contents().get_data(), original.pages[index].get_contents().get_data())
                self.assertEqual(page.mediabox, original.pages[index].mediabox)
                expected = [f1["paragraphs"][n][3] for n in f2["pages"][index]["paragraph_indexes"]]
                self.assertEqual(page.extract_text().strip().splitlines(), expected)
        self.assertEqual((oracle["expected_machine_status_after_pdf_processing"],
                          oracle["expected_recovery_action_after_pdf_processing"]),
                         ("blocked", "replace_attachment"))
        self.assertEqual((oracle["expected_parsed_document_count"], oracle["expected_risk_draft_count"]), (0, 0))
        self.assertEqual((oracle["current_machine_status"], oracle["pdf_processing_status"]),
                         ("pending", "NOT_IMPLEMENTED"))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f5.sqlite3")
            store.initialize()
            try:
                for name, role in (("owner", "business"), ("other", "business"), ("legal", "legal")):
                    store.create_user(name, role, "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(name: str) -> dict[str, str]:
                        response = client.post("/api/v1/sessions", json={
                            "username": name, "password": "synthetic-password"})
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}
                    owner, other, legal = (login(name) for name in ("owner", "other", "legal"))
                    created = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "Synthetic", "applicant": "F5"},
                                          files={"file": (oracle["file"], content, "application/pdf")})
                    self.assertEqual(created.status_code, 201, created.text)
                    task_id = created.json()["task_id"]
                    path = f"/api/v1/tasks/{task_id}"
                    state = client.get(path, headers=owner)
                    self.assertEqual(state.status_code, 200)
                    self.assertEqual((state.json()["document_version"], state.json()["machine_status"]), (1, "pending"))
                    self.assertEqual(client.get(path).status_code, 401)
                    self.assertEqual(client.get(path, headers=other).status_code, 404)
                    for endpoint in ("document", "risks"):
                        response = client.get(f"{path}/{endpoint}", headers=legal)
                        self.assertEqual((response.status_code, response.json()["code"]), (409, "DOCUMENT_NOT_READY"))
                    for table in ("parsed_documents", "rule_draft_snapshots"):
                        self.assertEqual(store.connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task_id,)
                        ).fetchone()[0], 0)
                    invalid = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "Synthetic", "applicant": "F5"},
                                          files={"file": ("invalid.pdf", b"not-a-pdf", "application/pdf")})
                    self.assertEqual((invalid.status_code, invalid.json()["code"]), (422, "INVALID_FILE"))
            finally:
                store.close()
