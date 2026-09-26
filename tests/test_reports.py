"""Report smoke: temporary database, synthetic source, mocked model, real LibreOffice."""

import io
import unittest
from datetime import timedelta
from unittest.mock import patch

import pdfplumber

from tests.test_reviews import ReviewTests as ReviewFixture
from backend.reviews import ConfirmRequest, ReviewRequest
from backend.tasks import TaskStore
from backend.reports import render_report


class ReportTests(unittest.TestCase):
    setUp = ReviewFixture.setUp
    tearDown = ReviewFixture.tearDown
    ready = ReviewFixture.ready
    payload = ReviewFixture.payload

    def confirmed(self):
        task = self.ready()
        payload = self.payload(task)
        payload['annotation'] = '中文法务批注 <script>alert(1)</script> [链接](https://example.invalid)'
        self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**payload))
        self.tasks.reviews.confirm(task, self.users['legal'], ConfirmRequest(
            document_version=1, review_version=1, conclusion='整改后复核，待法务核定'))
        return task

    def test_real_formats_permissions_and_history(self):
        task = self.confirmed()
        base = f'/api/v1/tasks/{task}/reports/'
        legal, owner = self.headers['legal'], self.headers['owner']
        self.assertEqual(self.client.get(base+'pdf?review_version=1', headers=legal).status_code, 409)
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertIsNone(self.tasks.reports.run_next())
        md = self.client.get(base+'markdown?review_version=1', headers=owner)
        pdf = self.client.get(base+'pdf?review_version=1', headers=owner)
        self.assertEqual(pdf.status_code, 200, pdf.text[:100] if pdf.status_code != 200 else '')
        self.assertIn('中文法务批注', md.text)
        self.assertNotIn('<script>', md.text)
        self.assertNotIn('[链接](', md.text)
        with pdfplumber.open(io.BytesIO(pdf.content)) as document:
            text = '\n'.join(page.extract_text() or '' for page in document.pages)
            for expected in ('合同审查报告', '中文法务批注', '整改后复核', '最终建议', '待法务核定', '模拟回写'):
                self.assertIn(expected, text)
        for role, code in [('admin', 403), ('other', 404)]:
            for suffix in ('status', 'pdf', 'markdown'):
                self.assertEqual(self.client.get(base+suffix+'?review_version=1', headers=self.headers[role]).status_code, code)
        self.assertEqual(self.client.get(base+'pdf?review_version=1').status_code, 401)
        self.assertEqual(self.client.get(base+'status', headers=owner).status_code, 422)
        self.assertEqual(self.client.get(base+'html?review_version=1', headers=legal).status_code, 422)
        status = self.client.get(base+'status?review_version=1', headers=owner).json()
        self.assertTrue(all('error' not in r and r['attempts'] == 1 for r in status['reports']))
        payload = self.payload(task)
        payload.update(base_review_version=1, annotation='new draft must not leak')
        self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**payload))
        self.assertEqual(self.client.get(base+'pdf?review_version=1', headers=owner).content, pdf.content)
        self.assertEqual(self.client.get(base+'pdf?review_version=2', headers=owner).status_code, 409)
        restarted = TaskStore(self.auth, self.root/'uploads')
        restarted.initialize()
        self.assertIsNone(restarted.reports.run_next())
        self.assertEqual(restarted.reports.download(task, self.users['owner'], 1, 'pdf'), pdf.content)
        with self.auth.connection:
            self.auth.connection.execute("UPDATE reports SET content=? WHERE task_id=? AND format='pdf'", (b'corrupt', task))
        self.assertEqual(self.client.get(base+'pdf?review_version=1', headers=owner).status_code, 409)

    def test_independent_failure_retry_and_lease_recovery(self):
        task = self.confirmed()
        reports = self.tasks.reports
        self.assertEqual(reports.run_next(), 'ready')  # markdown
        original = reports.download(task, self.users['owner'], 1, 'markdown')
        with patch('backend.reports.render_report', side_effect=RuntimeError('secret local path')):
            self.assertEqual(reports.run_next(), 'failed')
        base = f'/api/v1/tasks/{task}/reports/'
        status = reports.status(task, self.users['legal'], 1)
        self.assertEqual(status['reports'][1]['error'], 'REPORT_GENERATION_FAILED')
        self.assertEqual(self.tasks.reviews.read(task, self.users['legal'])['status'], 'confirmed')
        for role in ('owner', 'admin'):
            self.assertEqual(self.client.post(base+'pdf/retry', json={'review_version': 1}, headers=self.headers[role]).status_code, 403)
        self.assertEqual(self.client.post(base+'pdf/retry', json={'review_version': 1}, headers=self.headers['legal']).status_code, 200)
        self.assertEqual(self.client.post(base+'pdf/retry', json={'review_version': 1}, headers=self.headers['legal']).status_code, 409)
        # An active claim survives another store initialization; expired work is reclaimable.
        future = (self.auth._clock()+timedelta(minutes=2)).isoformat()
        with self.auth.connection:
            self.auth.connection.execute("UPDATE reports SET lease_token='crashed',lease_until=? WHERE format='pdf'", (future,))
        restarted = TaskStore(self.auth, self.root/'uploads')
        restarted.initialize()
        self.assertIsNone(restarted.reports.run_next())
        with self.auth.connection:
            self.auth.connection.execute("UPDATE reports SET lease_until='2000-01-01' WHERE format='pdf'")
        self.assertEqual(restarted.reports.run_next(), 'ready')
        self.assertEqual(reports.download(task, self.users['owner'], 1, 'markdown'), original)
        self.assertEqual(reports.status(task, self.users['legal'], 1)['reports'][1]['attempts'], 2)

    def test_confirmation_rollback(self):
        task = self.ready()
        self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**self.payload(task)))
        with patch.object(self.tasks.reports, 'enqueue', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.tasks.reviews.confirm(task, self.users['legal'], ConfirmRequest(
                    document_version=1, review_version=1, conclusion='test'))
        self.assertEqual(self.tasks.reviews.read(task, self.users['legal'])['status'], 'in_review')
        self.assertEqual(self.auth.connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 0)

    def test_stale_worker_cannot_overwrite_recovered_artifact(self):
        task = self.confirmed()
        calls = []

        def displaced(payload, format):
            # A second worker cannot reclaim this format until its lease expires.
            current = self.auth.connection.execute(
                'SELECT attempts FROM reports WHERE task_id=? AND format=?', (task, format)).fetchone()[0]
            self.assertEqual(current, 1)
            with self.auth.connection:
                self.auth.connection.execute("UPDATE reports SET lease_until='2000-01-01' WHERE task_id=? AND format=?", (task, format))
            with patch('backend.reports.render_report', side_effect=lambda p, f: render_report(p, f)):
                calls.append(self.tasks.reports.run_next())
            return b'stale worker output'

        with patch('backend.reports.render_report', side_effect=displaced):
            self.assertEqual(self.tasks.reports.run_next(), 'stale_lease')
        self.assertEqual(calls, ['ready'])
        self.assertNotEqual(self.tasks.reports.download(task, self.users['owner'], 1, 'markdown'), b'stale worker output')


# Imported TestCase is a fixture provider, not an additional suite to run here.
del ReviewFixture

if __name__ == '__main__':
    unittest.main()
