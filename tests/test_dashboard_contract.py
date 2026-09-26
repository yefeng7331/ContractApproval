"""Dashboard contract fields: current version, role boundary, and missing values."""

import unittest
from pathlib import Path

from backend.docx_job import run_docx_once
from tests import test_reviews


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


class DashboardContractTests(unittest.TestCase):
    setUp = test_reviews.ReviewTests.setUp
    tearDown = test_reviews.ReviewTests.tearDown

    def summary(self, task_id, role):
        detail = self.client.get(f'/api/v1/tasks/{task_id}', headers=self.headers[role])
        self.assertEqual(detail.status_code, 200, detail.text)
        listing = self.client.get('/api/v1/tasks', headers=self.headers[role])
        self.assertEqual(listing.status_code, 200, listing.text)
        item = next(item for item in listing.json()['items'] if item['task_id'] == task_id)
        self.assertEqual(item.get('contract'), detail.json().get('contract'))
        return item

    def test_current_parsed_fields_and_confirmation_boundary(self):
        content = (SAMPLES / 'f1-software-purchase.docx').read_bytes()
        task_id = self.tasks.create_task(self.users['owner'], 'f1.docx', content, '采购部', '张三')['task_id']
        self.assertNotIn('contract', self.summary(task_id, 'owner'))
        self.assertNotIn('contract', self.summary(task_id, 'admin'))
        self.assertEqual(self.summary(task_id, 'legal')['contract'],
                         {'title': None, 'amount': None, 'currency': None})
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        legal = self.summary(task_id, 'legal')['contract']
        self.assertTrue(legal['title'])
        self.assertTrue(legal['amount'])
        self.assertNotEqual(legal['title'], 'f1.docx')
        self.assertNotIn('contract', self.summary(task_id, 'owner'))
        self.assertNotIn('contract', self.summary(task_id, 'admin'))
        self.assertEqual(self.client.get(f'/api/v1/tasks/{task_id}', headers=self.headers['other']).status_code, 404)

        # Drive a separate synthetic task through real review and confirmation.
        confirmed_id = test_reviews.ReviewTests.ready(self, valid_model=True)
        confirmed_fields = self.summary(confirmed_id, 'legal')['contract']
        saved = self.client.put(f'/api/v1/tasks/{confirmed_id}/review',
                                json=test_reviews.ReviewTests.payload(self, confirmed_id), headers=self.headers['legal'])
        self.assertEqual(saved.status_code, 200, saved.text)
        confirmed = self.client.post(f'/api/v1/tasks/{confirmed_id}/confirm',
                                     json={'document_version': 1, 'review_version': 1,
                                           'conclusion': '合成测试结论'}, headers=self.headers['legal'])
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(self.summary(confirmed_id, 'owner')['contract'], confirmed_fields)
        self.assertNotIn('contract', self.summary(task_id, 'admin'))

        # A newer document must never inherit the previous title or amount.
        next_content = (SAMPLES / 'f4-revised-software-purchase.docx').read_bytes()
        uploaded = self.client.post(
            f'/api/v1/tasks/{confirmed_id}/documents', headers=self.headers['owner'],
            data={'base_document_version': '1', 'confirm_new_version': 'true'},
            files={'file': ('f4.docx', next_content)},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.assertNotIn('contract', self.summary(confirmed_id, 'owner'))
        self.assertEqual(self.summary(confirmed_id, 'legal')['contract'],
                         {'title': None, 'amount': None, 'currency': None})
