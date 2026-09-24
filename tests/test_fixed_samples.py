"""Standalone smoke for the checked-in F1/F4 synthetic sample oracle."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.clause_extractor import extract_clauses
from backend.demo_rules import evaluate_demo_rules
from backend.docx_job import run_docx_once
from backend.docx_parser import DocxParseError, parse_docx
from backend.main import create_app
from backend.metadata_extractor import extract_metadata
from backend.mock_pending import synthetic_attachment, synthetic_revised_attachment


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class FixedSampleSmokeTests(unittest.TestCase):
    def test_f1_f4_fixed_sample_smoke(self) -> None:
        expected = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))
        self.assertEqual(expected["schema_version"], 1)
        self.assertEqual(expected["preview_status"], "UNVERIFIED")
        self.assertEqual(set(expected["samples"]), {"F1", "F4"})

        for sample_id, source in (
            ("F1", synthetic_attachment()),
            ("F4", synthetic_revised_attachment()),
        ):
            with self.subTest(sample=sample_id):
                oracle = expected["samples"][sample_id]
                content = (SAMPLES / oracle["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
                parsed = parse_docx(content, oracle["document_version"])
                # The generator writes ZIP timestamps, so compare contract text, not archive bytes.
                self.assertEqual(
                    parse_docx(source, oracle["document_version"]).normalized_text,
                    parsed.normalized_text,
                )
                paragraphs = [
                    [item.paragraph_index, item.start, item.end, item.quote]
                    for item in parsed.paragraphs
                ]
                self.assertEqual(paragraphs, oracle["paragraphs"])
                self.assertEqual(
                    parsed.normalized_text,
                    "\n".join(item[3] for item in oracle["paragraphs"]),
                )
                for paragraph in parsed.paragraphs:
                    self.assertEqual(parsed.normalized_text[paragraph.start:paragraph.end], paragraph.quote)
                    self.assertIsNone(paragraph.page)
                    self.assertFalse(paragraph.locatable)
                    self.assertEqual(paragraph.reason, "PREVIEW_NOT_AVAILABLE")

                metadata = extract_metadata(parsed)
                self.assertEqual({field.name for field in metadata.fields}, set(oracle["fields"]))
                for field in metadata.fields:
                    target = oracle["fields"][field.name]
                    if target is None:
                        self.assertEqual(field.status, "unrecognized")
                        self.assertIsNone(field.anchor)
                        self.assertIsNone(field.value)
                    else:
                        quote, paragraph_index, start, end = target
                        self.assertEqual(field.status, "identified")
                        self.assertEqual(field.value, quote)
                        self.assertEqual(
                            [field.anchor.paragraph_index, field.anchor.start, field.anchor.end],
                            [paragraph_index, start, end],
                        )
                        self.assertEqual(parsed.normalized_text[start:end], quote)
                        self.assertIsNone(field.anchor.page)
                        self.assertFalse(field.anchor.locatable)

                clauses = extract_clauses(parsed)
                self.assertEqual(
                    [
                        [item.clause_type, item.paragraph_index, item.start, item.end, item.quote]
                        for item in clauses.clauses
                    ],
                    oracle["clauses"],
                )
                self.assertEqual(list(clauses.missing_types), oracle["missing_clause_types"])
                for clause in clauses.clauses:
                    self.assertEqual(parsed.normalized_text[clause.start:clause.end], clause.quote)
                    self.assertIsNone(clause.page)
                    self.assertFalse(clause.locatable)
                    self.assertEqual(clause.reason, "PREVIEW_NOT_AVAILABLE")

                rules = evaluate_demo_rules(parsed, clauses)
                self.assertEqual(rules["document_version"], oracle["document_version"])
                self.assertEqual(rules["enabled_rule_risk_summary"], oracle["enabled_rule_risk_summary"])
                self.assertEqual(rules["machine_suggestion"], oracle["machine_suggestion"])
                self.assertEqual(len(rules["risks"]), len(oracle["risks"]))
                for risk, target in zip(rules["risks"], oracle["risks"]):
                    for key in ("rule_id", "rule_version", "risk_level", "suggestion"):
                        self.assertEqual(risk[key], target[key])
                    self.assertEqual(risk["source"], "rule")
                    self.assertEqual(risk["status"], "machine_draft")
                    self.assertEqual(risk["legal_basis_status"], "pending_legal_verification")
                    self.assertEqual(
                        [anchor["clause_type"] for anchor in risk["anchors"]],
                        target["anchor_clause_types"],
                    )
                    for anchor in risk["anchors"]:
                        self.assertEqual(anchor["document_version"], oracle["document_version"])
                        self.assertEqual(parsed.normalized_text[anchor["start"]:anchor["end"]], anchor["quote"])
                        self.assertIsNone(anchor["page"])
                        self.assertFalse(anchor["locatable"])
                        self.assertEqual(anchor["reason"], "PREVIEW_NOT_AVAILABLE")

        f1 = expected["samples"]["F1"]["paragraphs"]
        f4 = expected["samples"]["F4"]["paragraphs"]
        self.assertEqual([index for index, (left, right) in enumerate(zip(f1, f4))
                          if left[3] != right[3]], [6, 7, 8])
        self.assertNotEqual(expected["samples"]["F1"]["sha256"],
                            expected["samples"]["F4"]["sha256"])

    def test_f5_empty_docx_fixed_sample_smoke(self) -> None:
        """A fixed F5 empty document blocks without evidence and can be replaced."""
        oracle = json.loads((SAMPLES / "f5_empty_expected.json").read_text(encoding="utf-8"))
        self.assertEqual(oracle["schema_version"], 1)
        self.assertEqual(oracle["sample_id"], "F5-empty-docx")
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        with self.assertRaises(DocxParseError) as caught:
            parse_docx(content, oracle["document_version"])
        self.assertEqual(caught.exception.code, oracle["expected_parse_code"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f5-smoke.sqlite3")
            store.initialize()
            try:
                store.create_user("f5-owner", "business", "synthetic-password")
                store.create_user("f5-other", "business", "synthetic-password")
                store.create_user("f5-legal", "legal", "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(username: str) -> dict[str, str]:
                        response = client.post(
                            "/api/v1/sessions",
                            json={"username": username, "password": "synthetic-password"},
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}

                    owner = login("f5-owner")
                    other = login("f5-other")
                    legal = login("f5-legal")
                    create = client.post(
                        "/api/v1/tasks", headers=owner,
                        data={"department": "采购部", "applicant": "合成用户"},
                        files={"file": (oracle["file"], content)},
                    )
                    self.assertEqual(create.status_code, 201, create.text)
                    task_id = create.json()["task_id"]
                    self.assertEqual(create.json()["document_version"], oracle["document_version"])
                    blocked = run_docx_once(client.app.state.task_store.jobs)
                    self.assertEqual(blocked["status"], oracle["machine_status"])
                    self.assertEqual(blocked["code"], oracle["expected_parse_code"])
                    state_response = client.get(f"/api/v1/tasks/{task_id}", headers=owner)
                    self.assertEqual(state_response.status_code, 200, state_response.text)
                    state = state_response.json()
                    for key in ("machine_status", "legal_status", "writeback_status", "recovery_action"):
                        self.assertEqual(state[key], oracle[key])
                    self.assertEqual(state["blocked_code"], oracle["expected_parse_code"])
                    self.assertTrue(state["blocked_reason"])
                    self.assertIsNone(state["review_version"])
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code, 404)
                    document = client.get(f"/api/v1/tasks/{task_id}/document", headers=legal)
                    self.assertEqual(document.status_code, 409)
                    self.assertEqual(document.json()["code"], "DOCUMENT_NOT_READY")
                    risks = client.get(f"/api/v1/tasks/{task_id}/risks", headers=legal)
                    self.assertEqual(risks.status_code, 409)
                    self.assertEqual(risks.json()["code"], "DOCUMENT_NOT_READY")
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], oracle["parsed_document_count"])
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM rule_draft_snapshots WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], oracle["risk_draft_count"])
                    self.assertEqual(run_docx_once(client.app.state.task_store.jobs),
                                     {"status": "no_pending_docx"})

                    revision = client.post(
                        f"/api/v1/tasks/{task_id}/documents", headers=owner,
                        data={"base_document_version": 1},
                        files={"file": ("f1-software-purchase.docx",
                                        (SAMPLES / "f1-software-purchase.docx").read_bytes())},
                    )
                    self.assertEqual(revision.status_code, 201, revision.text)
                    self.assertEqual(revision.json()["document_version"], 2)
                    self.assertEqual(tuple(store.connection.execute(
                        "SELECT machine_status, blocked_code FROM document_state_history "
                        "WHERE task_id = ? AND version = 1", (task_id,)
                    ).fetchone()), ("blocked", oracle["expected_parse_code"]))
                    self.assertEqual(run_docx_once(client.app.state.task_store.jobs)["status"], "reviewing")
                    self.assertEqual(store.connection.execute(
                        "SELECT document_version FROM parsed_documents WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
