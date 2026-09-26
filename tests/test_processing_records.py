"""Admin-only F1 worker record smoke with synthetic data and no network call."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.docx_job import run_docx_once
from tests import test_reviews


class ProcessingRecordsSmoke(unittest.TestCase):
    setUp = test_reviews.ReviewTests.setUp
    tearDown = test_reviews.ReviewTests.tearDown
    payload = test_reviews.ReviewTests.payload

    def test_f1_processing_records_and_permissions(self):
        source = Path(__file__).resolve().parents[1] / 'samples' / 'f1-software-purchase.docx'
        task = self.tasks.create_task(self.users['owner'], source.name, source.read_bytes(), '采购部', '张三')['task_id']
        url = f'/api/v1/tasks/{task}/processing-records'
        admin = self.headers['admin']
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        self.assertEqual(self.tasks.rule_snapshots.run_next()['status'], 'completed')
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        response = {key: snapshot[key] for key in ('document_version', 'evidence_sha256', 'rule_version')}
        response['suggestions'] = [{'rule_id': risk['rule_id'], 'suggestion': '合成建议'} for risk in snapshot['risks']]
        output = {'choices': [{'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': json.dumps(response)}}]}
        with patch('backend.model_jobs._post_json', side_effect=AssertionError('network forbidden')):
            self.assertEqual(self.tasks.model_jobs.run_once(task, 1, send=lambda _: output,
                authorization_key='processing-smoke')['state'], 'completed')
        review = self.client.put(f'/api/v1/tasks/{task}/review', json=self.payload(task), headers=self.headers['legal'])
        self.assertEqual(review.status_code, 200, review.text[:200])
        confirmed = self.client.post(f'/api/v1/tasks/{task}/confirm', json={
            'document_version': 1, 'review_version': 1, 'conclusion': '合成结论'}, headers=self.headers['legal'])
        self.assertEqual(confirmed.status_code, 200, confirmed.text[:200])
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')

        page = self.client.get(url, headers=admin)
        self.assertEqual(page.status_code, 200, page.text[:200])
        body = page.json()
        self.assertEqual(body['task_id'], task)
        self.assertEqual([(item['stage'], item['status']) for item in body['items']], [
            ('parse', 'completed'), ('rules', 'completed'), ('model', 'completed'),
            ('report_markdown', 'ready'), ('report_pdf', 'ready')])
        self.assertTrue(all(item['document_version'] == 1 for item in body['items']))
        self.assertEqual([item['review_version'] for item in body['items'][-2:]], [1, 1])
        self.assertTrue(all(item['finished_at'] for item in body['items']))
        self.assertEqual(self.client.get(url+'?document_version=1&limit=2&offset=2', headers=admin).json()['items'][0]['stage'], 'model')
        self.assertEqual(self.client.get(url+'?document_version=2', headers=admin).json()['total'], 0)
        self.assertEqual(set(body), {'task_id', 'total', 'items'})
        for record in body['items']:
            self.assertEqual(set(record), {'stage', 'document_version', 'review_version', 'attempt',
                                           'status', 'code', 'started_at', 'finished_at'})
        for role in ('owner', 'legal', 'other'):
            self.assertEqual(self.client.get(url, headers=self.headers[role]).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/tasks/missing/processing-records', headers=admin).status_code, 404)
        self.assertEqual(self.client.get(url+'?limit=101', headers=admin).status_code, 422)
