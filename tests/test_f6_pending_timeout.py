"""Standalone evidence for the F6 dependency fixture, not API recovery."""

import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.docx_parser import parse_docx
from samples import f6_pending_timeout as fixture


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class PendingTimeoutFixtureSmokeTests(unittest.TestCase):
    def test_f6_pending_timeout_fixture_smoke(self) -> None:
        oracle = json.loads((SAMPLES / "f6_pending_timeout_expected.json").read_text(encoding="utf-8"))
        f1 = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        self.assertEqual((oracle["schema_version"], oracle["scenario_id"], oracle["synthetic"]),
                         (1, "F6-pending-attachment-timeout", True))
        self.assertEqual(oracle["source_sha256"], f1["sha256"])
        self.assertEqual(oracle["source_file"], f1["file"])
        self.assertEqual(oracle["dependency_attempts"], [
            {"attempt_number": 1, "outcome": "timeout", "attachment_returned": False},
            {"attempt_number": 2, "outcome": "attachment_available", "attachment_returned": True},
        ])
        # Replaying the sequence cannot consume a process-global failure flag.
        for _ in range(2):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("No attachment on timeout")):
                with self.assertRaises(TimeoutError):
                    fixture.fetch_attachment(1)
            content = fixture.fetch_attachment(2)
            self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["source_sha256"])
            parsed = parse_docx(content, oracle["document_version"])
            self.assertEqual(parsed.normalized_text, "\n".join(p[3] for p in f1["paragraphs"]))
            self.assertEqual(fixture.fetch_attachment(3), content)
        for invalid in (0, -1, True, 1.0, "1", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                fixture.fetch_attachment(invalid)
        with patch.object(Path, "read_bytes", return_value=b"changed-attachment"):
            with self.assertRaisesRegex(ValueError, "differs"):
                fixture.fetch_attachment(2)

        future = oracle["future_processor_expectations"]
        self.assertEqual(future["after_timeout"], {
            "machine_status": "blocked", "recovery_action": "admin_retry", "attempt_count": 1,
            "parsed_document_count": 0, "risk_draft_count": 0,
        })
        self.assertEqual(future["after_retry"], {
            "document_version": 1, "attempt_count": 2,
            "prior_timeout_attempt_preserved": True, "new_attachment_version_created": False,
        })
        # Business recovery is separately exercised by tests.test_pending_imports.
        self.assertEqual(oracle["processor_integration_status"], "IMPLEMENTED_PENDING_ACCEPTANCE")
        self.assertEqual(oracle["role_permissions_and_restart_status"], "VERIFIED_FAULT_INJECTION")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            fixture.main()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(records), 2)
        for record, expected in zip(records, oracle["dependency_attempts"], strict=True):
            self.assertEqual(record["scenario_id"], oracle["scenario_id"])
            self.assertEqual(record["scope"], "dependency_fixture_only")
            self.assertEqual(record["attempt_number"], expected["attempt_number"])
            self.assertEqual(record["dependency_outcome"], expected["outcome"])
            self.assertEqual(record["attachment_returned"], expected["attachment_returned"])
            self.assertNotIn("machine_status", record)
        self.assertNotIn("sha256", records[0])
        self.assertEqual(records[1]["sha256"], f1["sha256"])
