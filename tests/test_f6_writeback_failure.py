"""Standalone F6 mock comment dependency fixture smoke, not API evidence."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from samples import f6_writeback_failure as fixture


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class WritebackFailureFixtureSmokeTests(unittest.TestCase):
    def test_f6_writeback_failure_fixture_smoke(self) -> None:
        oracle = json.loads((SAMPLES / "f6_writeback_expected.json").read_text(encoding="utf-8"))
        self.assertEqual((oracle["schema_version"], oracle["scenario_id"], oracle["synthetic"]),
                         (1, "F6-writeback-failure-and-duplicate", True))
        self.assertIn("模拟回写", oracle["comment_markdown"])
        self.assertEqual(oracle["application_api_and_persistence_status"], "NOT_IMPLEMENTED")
        sink = fixture.MockCommentSink()
        key = (oracle["task_id"], 1, oracle["mock_approval_id"])
        with self.assertRaises(TimeoutError):
            sink.submit(*key, oracle["comment_markdown"])
        self.assertEqual(sink.comment_count, 0)
        first_id, created = sink.submit(*key, oracle["comment_markdown"])
        self.assertEqual((first_id, created, sink.comment_count),
                         ("synthetic-comment-001", True, 1))
        self.assertEqual(sink.submit(*key, oracle["comment_markdown"]), (first_id, False))
        self.assertEqual(sink.comment_count, 1)
        with self.assertRaises(ValueError):
            sink.submit(*key, "different confirmed comment")
        self.assertEqual(sink.comment_count, 1)
        second_id, created = sink.submit(key[0], 2, key[2], oracle["comment_markdown"])
        self.assertEqual((second_id, created, sink.comment_count),
                         ("synthetic-comment-002", True, 2))
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(sink.submit(*key, oracle["comment_markdown"]), (first_id, False))
        for bad in (0, -1, True, "1"):
            with self.subTest(version=bad), self.assertRaises(ValueError):
                sink.submit(key[0], bad, key[2], oracle["comment_markdown"])
        self.assertEqual(sink.comment_count, 2)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            fixture.main()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(records), 4)
        for actual, expected in zip(records, oracle["dependency_attempts"], strict=True):
            self.assertEqual(actual["scenario_id"], oracle["scenario_id"])
            self.assertEqual(actual["scope"], "in_memory_dependency_fixture_only")
            for field in ("attempt_number", "confirmed_review_version", "comment_id",
                          "created", "comment_count"):
                self.assertEqual(actual[field], expected[field])
            self.assertEqual(actual["dependency_outcome"], expected["outcome"])
            self.assertNotIn("writeback_status", actual)
        self.assertEqual(oracle["future_application_expectations"], {
            "before_legal_confirmation": "REJECT", "after_first_failure": "failed",
            "after_retry": "success", "same_key_comment_limit": 1,
            "history_preserved_across_restart": True,
        })
