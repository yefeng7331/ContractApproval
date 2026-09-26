"""Business type intake smoke with isolated SQLite and synthetic attachments."""

import unittest
from pathlib import Path

from tests.test_reviews import ReviewTests as Fixture


SAMPLE = (Path(__file__).resolve().parents[1] / "samples" / "f4-revised-software-purchase.docx").read_bytes()


class BusinessTypeTests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def test_upload_visibility_and_invalid_type(self):
        def upload(data, role="owner"):
            return self.client.post(
                "/api/v1/tasks", headers=self.headers[role], data=data,
                files={"file": ("sample.docx", SAMPLE)},
            )

        data = {"department": "采购部", "applicant": "张三", "business_type": "软件采购"}
        created = upload(data)
        self.assertEqual(created.status_code, 201, created.text)
        task_id = created.json()["task_id"]
        for role in ("owner", "legal"):
            detail = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers[role])
            self.assertEqual(detail.json()["submission"]["business_type"], "软件采购")
            listing = self.client.get("/api/v1/tasks", headers=self.headers[role])
            self.assertEqual(listing.json()["items"][0]["submission"]["business_type"], "软件采购")
        admin = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers["admin"])
        self.assertNotIn("submission", admin.json())
        other = self.client.get(f"/api/v1/tasks/{task_id}", headers=self.headers["other"])
        self.assertEqual(other.status_code, 404)
        self.assertEqual(upload({**data, "business_type": "其他"}).status_code, 422)
        self.assertEqual(upload(data, "legal").status_code, 403)
        legacy = upload({"department": "采购部", "applicant": "张三"})
        self.assertEqual(legacy.status_code, 201)
        self.assertIsNone(legacy.json()["submission"]["business_type"])

    def test_mock_pending_sets_business_type(self):
        pending = self.client.get("/api/v1/mock-pending", headers=self.headers["owner"])
        self.assertEqual(pending.status_code, 200)
        item = pending.json()["items"][0]
        self.assertEqual(item["business_type"], "软件采购")
        imported = self.client.post(f"/api/v1/mock-pending/{item['id']}/import", headers=self.headers["owner"])
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(imported.json()["submission"]["business_type"], "软件采购")
