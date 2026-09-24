"""Fast, independent API smoke checks for each implemented backend feature."""

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.clause_extractor import extract_clauses
from backend.demo_rules import evaluate_demo_rules
from backend.docx_parser import DocxParseError, parse_docx
from backend.docx_job import run_docx_once
from backend.metadata_extractor import extract_metadata
from backend.main import create_app
from backend.mock_pending import (
    MOCK_PENDING_ID, _package_paragraphs, synthetic_attachment, synthetic_revised_attachment,
)
from tests.test_docx_job import empty_docx


PDF_V1 = b"%PDF-1.4\nsynthetic first version\n%%EOF"
PDF_V2 = b"%PDF-1.4\nsynthetic revision\n%%EOF"


class BackendSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = AuthStore(self.root / "smoke.sqlite3")
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.client = TestClient(
            create_app(auth_store=self.store, upload_root=self.root / "uploads")
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, username: str, role: str) -> dict[str, str]:
        self.store.create_user(username, role, "synthetic-password")
        response = self.client.post(
            "/api/v1/sessions",
            json={"username": username, "password": "synthetic-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def upload(self, headers: dict[str, str]) -> dict:
        response = self.client.post(
            "/api/v1/tasks",
            headers=headers,
            data={"department": "采购部", "applicant": "演示用户"},
            files={"file": ("synthetic.pdf", PDF_V1, "application/pdf")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_rule_evidence_repair_smoke(self) -> None:
        """Missing contract terms produce anchored drafts; malformed evidence fails closed."""
        owner = self.login("repair-owner", "business")
        legal = self.login("repair-legal", "legal")
        paragraphs = (
            "标的：乙方交付软件系统。",
            "知识产权：全部知识产权归乙方所有。",
            "付款：软件到货后，甲方一次性支付全部合同价款。",
        )
        response = self.client.post(
            "/api/v1/tasks", headers=owner,
            data={"department": "采购部", "applicant": "合成用户"},
            files={"file": ("missing-terms.docx", _package_paragraphs(paragraphs))},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"],
                         "reviewing")
        endpoint = f"/api/v1/tasks/{task_id}/risks"
        draft = self.client.get(endpoint, headers=legal)
        self.assertEqual(draft.status_code, 200, draft.text)
        risks = {risk["rule_id"]: risk for risk in draft.json()["risks"]}
        self.assertEqual(set(risks), {"DEMO-IP-01", "DEMO-PAY-01"})
        self.assertEqual(risks["DEMO-PAY-01"]["missing_clause_types"], ["验收"])
        snapshot = self.client.app.state.task_store.rule_snapshots.persist(task_id, 1)
        self.assertEqual(snapshot["operation"], "created")
        self.assertEqual(snapshot["risks"], draft.json()["risks"])
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE parsed_documents SET clauses_json = ? WHERE task_id = ?",
                ("not-json", task_id),
            )
        invalid = self.client.get(endpoint, headers=legal)
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(invalid.json()["code"], "RULE_EVIDENCE_INVALID")

    def test_docx_job_persistence_smoke(self) -> None:
        business = self.login("business1", "business")
        response = self.client.post(
            "/api/v1/tasks", headers=business,
            data={"department": "采购部", "applicant": "演示用户"},
            files={"file": ("synthetic.docx", synthetic_attachment(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"], "reviewing")
        row = self.store.connection.execute(
            "SELECT normalized_text, fields_json FROM parsed_documents WHERE task_id = ?", (task_id,)
        ).fetchone()
        self.assertIn("付款", row["normalized_text"])
        self.assertIn("amount", row["fields_json"])
        self.assertEqual(self.client.get(f"/api/v1/tasks/{task_id}", headers=business).json()["machine_status"],
                         "reviewing")
        damaged = self.client.post(
            "/api/v1/tasks", headers=business,
            data={"department": "采购部", "applicant": "演示用户"},
            files={"file": ("damaged.docx", synthetic_attachment(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        self.assertEqual(damaged.status_code, 201, damaged.text)
        damaged_id = damaged.json()["task_id"]
        original_path = self.store.connection.execute(
            "SELECT file_path FROM document_versions WHERE task_id = ?", (damaged_id,)
        ).fetchone()[0]
        Path(original_path).write_bytes(b"tampered synthetic attachment")
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["code"],
                         "ATTACHMENT_CHANGED")
        blocked = self.client.get(f"/api/v1/tasks/{damaged_id}", headers=business).json()
        self.assertEqual(blocked["machine_status"], "blocked")
        self.assertEqual(blocked["recovery_action"], "replace_attachment")
        self.assertIsNone(self.store.connection.execute(
            "SELECT 1 FROM parsed_documents WHERE task_id = ?", (damaged_id,)
        ).fetchone())
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs), {"status": "no_pending_docx"})

    def test_automatic_docx_processing_smoke(self) -> None:
        business = self.login("business1", "business")
        other = self.login("business2", "business")
        with TestClient(create_app(auth_store=self.store, upload_root=self.root / "uploads",
                                   auto_process_docx=True)) as automatic:
            for content, expected in ((synthetic_attachment(), "reviewing"),
                                      (empty_docx(), "blocked")):
                response = automatic.post(
                    "/api/v1/tasks", headers=business,
                    data={"department": "采购部", "applicant": "演示用户"},
                    files={"file": ("synthetic.docx", content,
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                )
                self.assertEqual(response.status_code, 201, response.text)
                task_id = response.json()["task_id"]
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = automatic.get(f"/api/v1/tasks/{task_id}", headers=business).json()
                    if state["machine_status"] == expected:
                        break
                    time.sleep(0.02)
                self.assertEqual(state["machine_status"], expected)
                self.assertEqual(automatic.get(f"/api/v1/tasks/{task_id}", headers=other).status_code,
                                 404)
                self.assertEqual(self.store.connection.execute(
                    "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,),
                ).fetchone()[0], int(expected == "reviewing"))
                if expected == "blocked":
                    self.assertEqual(state["recovery_action"], "replace_attachment")

    def test_parsed_document_api_smoke(self) -> None:
        owner = self.login("business1", "business")
        other = self.login("business2", "business")
        legal = self.login("legal1", "legal")
        admin = self.login("admin1", "admin")
        response = self.client.post(
            "/api/v1/tasks", headers=owner,
            data={"department": "采购部", "applicant": "演示用户"},
            files={"file": ("synthetic.docx", synthetic_attachment(),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task_id = response.json()["task_id"]
        endpoint = f"/api/v1/tasks/{task_id}/document"
        not_ready = self.client.get(endpoint, headers=legal)
        self.assertEqual(not_ready.status_code, 409)
        self.assertEqual(not_ready.json()["code"], "DOCUMENT_NOT_READY")
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"], "reviewing")

        result = self.client.get(endpoint, headers=legal)
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual((data["task_id"], data["document_version"]), (task_id, 1))
        self.assertIsNone(data["review_version"])
        self.assertIsNone(data["page_count"])
        self.assertFalse(data["preview_available"])
        self.assertTrue(data["paragraphs"] and data["fields"] and data["clauses"])
        self.assertIn("数据安全", data["missing_clause_types"])
        for anchor in data["paragraphs"] + data["clauses"]:
            self.assertEqual(anchor["document_version"], 1)
            self.assertEqual(data["normalized_text"][anchor["start"]:anchor["end"]],
                             anchor["quote"])
            self.assertFalse(anchor["locatable"])
        for field in data["fields"]:
            anchor = field["anchor"]
            if anchor is not None:
                self.assertEqual(anchor["document_version"], 1)
                self.assertEqual(data["normalized_text"][anchor["start"]:anchor["end"]],
                                 anchor["quote"])
        self.assertEqual(self.client.get(endpoint + "?document_version=1", headers=legal).json(), data)
        self.assertEqual(self.client.get(endpoint + "?document_version=2", headers=legal).json()["code"],
                         "DOCUMENT_VERSION_NOT_FOUND")
        self.assertEqual(self.client.get(endpoint + "?document_version=0", headers=legal).status_code,
                         422)
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(endpoint, headers=owner).json()["code"],
                         "DOCUMENT_NOT_CONFIRMED")
        self.assertEqual(self.client.get(endpoint, headers=other).status_code, 404)
        self.assertEqual(self.client.get(endpoint, headers=admin).status_code, 403)

        pending_id = self.upload(owner)["task_id"]
        self.assertEqual(self.client.get(f"/api/v1/tasks/{pending_id}/document", headers=legal).json()["code"],
                         "DOCUMENT_NOT_READY")


    def test_account_session_smoke(self) -> None:
        business = self.login("business1", "business")
        current = self.client.get("/api/v1/sessions/current", headers=business)
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["role"], "business")
        self.assertEqual(self.client.get("/api/v1/sessions/current").status_code, 401)
        self.assertEqual(
            self.client.delete("/api/v1/sessions/current", headers=business).status_code,
            204,
        )
        self.assertEqual(
            self.client.get("/api/v1/sessions/current", headers=business).status_code,
            401,
        )

    def test_local_upload_and_ownership_smoke(self) -> None:
        owner = self.login("business1", "business")
        other = self.login("business2", "business")
        task = self.upload(owner)
        self.assertEqual(task["document_version"], 1)
        self.assertEqual(task["submission"]["sha256"], hashlib.sha256(PDF_V1).hexdigest())
        self.assertEqual(
            self.client.get("/api/v1/tasks", headers=owner).json()["total"], 1
        )
        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{task['task_id']}", headers=other).status_code,
            404,
        )

    def test_mock_pending_import_smoke(self) -> None:
        business = self.login("business1", "business")
        legal = self.login("legal1", "legal")
        pending = self.client.get("/api/v1/mock-pending", headers=business)
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(pending.json()["items"][0]["id"], MOCK_PENDING_ID)
        endpoint = f"/api/v1/mock-pending/{MOCK_PENDING_ID}/import"
        self.assertEqual(self.client.post(endpoint, headers=legal).status_code, 403)
        imported = self.client.post(endpoint, headers=business)
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(imported.json()["source"], "mock_pending")
        self.assertEqual(imported.json()["mock_approval_id"], MOCK_PENDING_ID)
        self.assertEqual(
            self.client.get("/api/v1/tasks", headers=business).json()["total"], 1
        )

    def test_document_revision_smoke(self) -> None:
        business = self.login("business1", "business")
        task = self.upload(business)
        task_id = task["task_id"]
        endpoint = f"/api/v1/tasks/{task_id}/documents"

        def replace(base_version: int):
            return self.client.post(
                endpoint,
                headers=business,
                data={"base_document_version": base_version},
                files={"file": ("revision.pdf", PDF_V2, "application/pdf")},
            )

        pending = replace(1)
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["task_id"], task_id)
        self.assertEqual(pending.json()["current_status"]["machine_status"], "pending")
        # The parser has not been built, so this prerequisite is simulated in SQLite.
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE tasks SET machine_status = 'blocked', "
                "recovery_action = 'replace_attachment' WHERE id = ?",
                (task_id,),
            )
        revised = replace(1)
        self.assertEqual(revised.status_code, 201, revised.text)
        self.assertEqual(revised.json()["document_version"], 2)
        self.assertEqual(revised.json()["machine_status"], "pending")
        self.assertEqual(revised.json()["submission"]["sha256"], hashlib.sha256(PDF_V2).hexdigest())
        stale = replace(1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["current_status"]["document_version"], 2)
        versions = self.store.connection.execute(
            "SELECT version, file_path FROM document_versions WHERE task_id = ? ORDER BY version",
            (task_id,),
        ).fetchall()
        self.assertEqual([row["version"] for row in versions], [1, 2])
        self.assertEqual(Path(versions[0]["file_path"]).read_bytes(), PDF_V1)
        self.assertEqual(Path(versions[1]["file_path"]).read_bytes(), PDF_V2)

    def test_failed_intake_cleanup_smoke(self) -> None:
        business = self.login("business1", "business")
        self.store.connection.execute(
            "CREATE TRIGGER fail_new_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.upload(business)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertEqual(list((self.root / "uploads").iterdir()), [])

    def test_persistent_parse_job_smoke(self) -> None:
        business = self.login("business1", "business")
        task_id = self.upload(business)["task_id"]
        jobs = self.client.app.state.task_store.jobs
        queued = self.store.connection.execute(
            "SELECT status, attempt_count FROM processing_jobs WHERE task_id = ?", (task_id,)
        ).fetchone()
        self.assertEqual(tuple(queued), ("pending", 0))
        lease = jobs.claim_next()
        self.assertEqual((lease.task_id, lease.document_version, lease.attempt), (task_id, 1, 1))
        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{task_id}", headers=business).json()["machine_status"],
            "parsing",
        )
        self.assertIsNone(jobs.claim_next())
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE processing_jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' "
                "WHERE task_id = ?", (task_id,),
            )
        self.assertEqual(jobs.recover_expired(), 1)
        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{task_id}", headers=business).json()["machine_status"],
            "pending",
        )
        self.assertEqual(jobs.claim_next().attempt, 2)

    def test_docx_text_extraction_smoke(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 1)
        self.assertEqual(parsed.document_version, 1)
        self.assertEqual(len(parsed.paragraphs), 12)
        self.assertEqual(parsed.paragraphs[0].quote, "合成软件采购合同（仅供演示，非真实交易）")
        self.assertIn("知识产权：交付软件", parsed.normalized_text)
        for paragraph in parsed.paragraphs:
            self.assertEqual(
                parsed.normalized_text[paragraph.start:paragraph.end], paragraph.quote
            )
            self.assertFalse(paragraph.locatable)
            self.assertIsNone(paragraph.page)
        with self.assertRaises(DocxParseError) as caught:
            parse_docx(b"corrupt synthetic DOCX", 1)
        self.assertEqual(caught.exception.code, "DOCX_UNREADABLE")

    def test_docx_clause_extraction_smoke(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 1)
        result = extract_clauses(parsed)
        self.assertEqual(len(result.clauses), 7)
        self.assertEqual(result.missing_types, ("数据安全",))
        self.assertEqual(result.clauses[0].clause_type, "标的")
        self.assertEqual(result.clauses[-1].clause_type, "争议解决")
        for clause in result.clauses:
            self.assertEqual(parsed.normalized_text[clause.start:clause.end], clause.quote)
            self.assertFalse(clause.locatable)
        # A keyword in a plain sentence is not enough to claim a clause exists.
        from tests.test_docx_parser import package

        prose = parse_docx(
            package("<w:p><w:r><w:t>合同提到付款和保密，但未列条款。</w:t></w:r></w:p>"),
            1,
        )
        self.assertEqual(extract_clauses(prose).clauses, ())

    def test_docx_metadata_extraction_smoke(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 1)
        result = extract_metadata(parsed)
        self.assertEqual(result.get("contract_number").value, "SYN-2026-001")
        self.assertEqual(result.get("amount").value, "100000")
        self.assertEqual(result.get("currency").value, "人民币")
        self.assertEqual(result.get("buyer_credit_code").status, "unrecognized")
        self.assertEqual(result.get("supplier_credit_code").status, "unrecognized")
        self.assertEqual(result.get("effective_conditions").status, "unrecognized")
        for field in result.fields:
            if field.anchor:
                self.assertEqual(
                    parsed.normalized_text[field.anchor.start:field.anchor.end],
                    field.anchor.quote,
                )
        # A missing label in prose must not invent an applicant or a title.
        from tests.test_docx_parser import package

        prose = parse_docx(
            package("<w:p><w:r><w:t>本合同由张三提交，金额以后再议。</w:t></w:r></w:p>"),
            1,
        )
        self.assertEqual(extract_metadata(prose).get("applicant").status, "unrecognized")
        self.assertEqual(extract_metadata(prose).get("title").status, "unrecognized")

    def test_rule_drafts_api_smoke(self) -> None:
        owner = self.login("rules-owner", "business")
        other = self.login("rules-other", "business")
        legal = self.login("rules-legal", "legal")
        admin = self.login("rules-admin", "admin")
        for filename, content, expected in (
            ("f1.docx", synthetic_attachment(), {"DEMO-IP-01", "DEMO-PAY-01"}),
            ("f4.docx", synthetic_revised_attachment(), set()),
        ):
            response = self.client.post(
                "/api/v1/tasks", headers=owner,
                data={"department": "采购部", "applicant": "合成用户"},
                files={"file": (filename, content)},
            )
            self.assertEqual(response.status_code, 201, response.text)
            task_id = response.json()["task_id"]
            endpoint = f"/api/v1/tasks/{task_id}/risks"
            self.assertEqual(self.client.get(endpoint, headers=legal).status_code, 409)
            self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"], "reviewing")
            before = self.client.get(f"/api/v1/tasks/{task_id}", headers=owner).json()
            changes = self.store.connection.total_changes
            result = self.client.get(endpoint, headers=legal)
            self.assertEqual(result.status_code, 200, result.text)
            draft = result.json()
            self.assertEqual({r["rule_id"] for r in draft["risks"]}, expected)
            self.assertEqual(draft["document_version"], 1)
            self.assertIsNone(draft["review_version"])
            self.assertEqual(draft["evaluation_mode"], "on_demand_rules_only")
            self.assertFalse(draft["persisted"])
            original = self.client.get(f"/api/v1/tasks/{task_id}/document", headers=legal).json()
            for risk in draft["risks"]:
                for anchor in risk["anchors"]:
                    self.assertEqual(anchor["document_version"], 1)
                    self.assertEqual(original["normalized_text"][anchor["start"]:anchor["end"]], anchor["quote"])
            self.assertEqual(self.client.get(endpoint + "?document_version=1", headers=legal).json(), draft)
            self.assertEqual(self.store.connection.total_changes, changes)
            self.assertEqual(self.client.get(f"/api/v1/tasks/{task_id}", headers=owner).json(), before)
            for headers, status in (({}, 401), (owner, 403), (other, 404), (admin, 403)):
                for suffix in ("", "?review_version=1"):
                    self.assertEqual(self.client.get(endpoint + suffix, headers=headers).status_code, status)
            for suffix, status in (("?document_version=2", 404), ("?review_version=1", 404),
                                   ("?document_version=0", 422), ("?review_version=0", 422)):
                self.assertEqual(self.client.get(endpoint + suffix, headers=legal).status_code, status)
            # Simulate corrupted persisted evidence: fail closed, never return a draft.
            clauses = original["clauses"]
            clauses[0]["document_version"] = 99
            with self.store.connection:
                self.store.connection.execute(
                    "UPDATE parsed_documents SET clauses_json = ? WHERE task_id = ?",
                    (json.dumps(clauses), task_id),
                )
            invalid = self.client.get(endpoint, headers=legal)
            self.assertEqual(invalid.status_code, 409)
            self.assertEqual(invalid.json()["code"], "RULE_EVIDENCE_INVALID")
            with self.store.connection:
                self.store.connection.execute(
                    "UPDATE parsed_documents SET clauses_json = ? WHERE task_id = ?",
                    ("not-json", task_id),
                )
            malformed = self.client.get(endpoint, headers=legal)
            self.assertEqual(malformed.status_code, 409)
            self.assertEqual(malformed.json()["code"], "RULE_EVIDENCE_INVALID")

    def test_persisted_rule_draft_snapshot_smoke(self) -> None:
        """F1/F4 snapshots persist once; unready, stale and corrupt evidence fail closed."""
        business = self.login("snapshot-owner", "business")
        snapshots = self.client.app.state.task_store.rule_snapshots
        for filename, content, expected in (
            ("f1.docx", synthetic_attachment(), {"DEMO-IP-01", "DEMO-PAY-01"}),
            ("f4.docx", synthetic_revised_attachment(), set()),
        ):
            response = self.client.post(
                "/api/v1/tasks", headers=business,
                data={"department": "采购部", "applicant": "合成用户"},
                files={"file": (filename, content)},
            )
            self.assertEqual(response.status_code, 201, response.text)
            task_id = response.json()["task_id"]
            self.assertEqual(snapshots.persist(task_id, 1)["status"], "document_not_ready")
            self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"], "reviewing")
            self.assertEqual(snapshots.persist(task_id, 2)["status"], "stale_document_version")
            if filename == "f4.docx":
                command = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", "backend.rule_snapshot",
                     task_id, "1", "--database", str(self.root / "smoke.sqlite3"),
                     "--uploads", str(self.root / "uploads")],
                    capture_output=True, text=True, check=True,
                )
                first = json.loads(command.stdout)
            else:
                first = snapshots.persist(task_id, 1)
            self.assertEqual(first["operation"], "created")
            self.assertEqual({risk["rule_id"] for risk in first["risks"]}, expected)
            self.assertTrue(first["persisted"])
            self.assertIsNone(first["review_version"])
            row = self.store.connection.execute(
                """SELECT rule_version, evidence_sha256, snapshot_json, created_at
                FROM rule_draft_snapshots WHERE task_id = ? AND document_version = 1""",
                (task_id,),
            ).fetchone()
            self.assertEqual(row["rule_version"], "demo-v2")
            self.assertEqual(len(row["evidence_sha256"]), 64)
            self.assertEqual(json.loads(row["snapshot_json"])["risks"], first["risks"])
            second = snapshots.persist(task_id, 1)
            self.assertEqual(second["operation"], "already_exists")
            self.assertEqual(second["risks"], first["risks"])
            self.assertEqual(self.store.connection.execute(
                "SELECT created_at FROM rule_draft_snapshots WHERE task_id = ?", (task_id,)
            ).fetchone()[0], row["created_at"])
            summary = self.client.get(f"/api/v1/tasks/{task_id}", headers=business).json()
            self.assertEqual(summary["machine_status"], "reviewing")
            self.assertIsNone(summary["review_version"])
            with self.store.connection:
                self.store.connection.execute(
                    """UPDATE parsed_documents SET normalized_text = normalized_text || 'tampered'
                    WHERE task_id = ? AND document_version = 1""", (task_id,),
                )
            changed = snapshots.persist(task_id, 1)
            self.assertEqual(changed["code"], "RULE_EVIDENCE_CHANGED")
            self.assertEqual(json.loads(self.store.connection.execute(
                "SELECT snapshot_json FROM rule_draft_snapshots WHERE task_id = ?", (task_id,)
            ).fetchone()[0])["risks"], first["risks"])
            with self.store.connection:
                self.store.connection.execute(
                    """UPDATE rule_draft_snapshots SET rule_version = 'demo-v0'
                    WHERE task_id = ? AND document_version = 1""", (task_id,),
                )
            self.assertEqual(snapshots.persist(task_id, 1)["code"], "RULE_VERSION_CHANGED")

        response = self.client.post(
            "/api/v1/tasks", headers=business,
            data={"department": "采购部", "applicant": "合成用户"},
            files={"file": ("damaged-evidence.docx", synthetic_attachment())},
        )
        self.assertEqual(response.status_code, 201, response.text)
        damaged_id = response.json()["task_id"]
        self.assertEqual(run_docx_once(self.client.app.state.task_store.jobs)["status"], "reviewing")
        with self.store.connection:
            self.store.connection.execute(
                """UPDATE parsed_documents SET clauses_json = ?
                WHERE task_id = ? AND document_version = 1""",
                ("not-json", damaged_id),
            )
        invalid = snapshots.persist(damaged_id, 1)
        self.assertEqual(invalid["code"], "RULE_EVIDENCE_INVALID")
        self.assertIsNone(self.store.connection.execute(
            "SELECT 1 FROM rule_draft_snapshots WHERE task_id = ?", (damaged_id,)
        ).fetchone())
        pdf_id = self.upload(business)["task_id"]
        self.assertEqual(snapshots.persist(pdf_id, 1)["status"],
                         "unsupported_document_format")

    def test_demo_rule_drafts_smoke(self) -> None:
        """F1 yields two anchored drafts; F4 remains clear."""
        f1 = parse_docx(synthetic_attachment(), 1)
        extracted = extract_clauses(f1)
        result = evaluate_demo_rules(f1, extracted)
        self.assertEqual({r["rule_id"] for r in result["risks"]},
                         {"DEMO-IP-01", "DEMO-PAY-01"})
        self.assertEqual(result["machine_suggestion"], "建议拒绝并整改")
        for risk in result["risks"]:
            self.assertEqual(risk["risk_level"], "high")
            self.assertEqual(risk["source"], "rule")
            self.assertEqual(risk["legal_basis_status"], "pending_legal_verification")
            for anchor in risk["anchors"]:
                self.assertEqual(anchor["document_version"], 1)
                self.assertEqual(f1.normalized_text[anchor["start"]:anchor["end"]],
                                 anchor["quote"])
        f4 = parse_docx(synthetic_revised_attachment(), 2)
        revised = evaluate_demo_rules(f4, extract_clauses(f4))
        self.assertEqual(revised["risks"], [])
        self.assertEqual(revised["enabled_rule_risk_summary"], "未发现已启用规则风险")


if __name__ == "__main__":
    unittest.main()
