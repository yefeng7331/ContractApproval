"""Legal review HTTP smoke: temporary SQLite, synthetic contracts, no network."""

import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.main import create_app
from backend.reviews import ReviewRequest
from backend.tasks import TaskStore


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.auth = AuthStore(self.root / 'test.sqlite3')
        self.auth.initialize()
        self.users = {name: self.auth.create_user(name, role, 'synthetic-password')
            for name, role in [('owner', 'business'), ('other', 'business'), ('legal', 'legal'), ('admin', 'admin')]}
        self.tasks = TaskStore(self.auth, self.root / 'uploads')
        self.tasks.initialize()
        self.client = TestClient(create_app(auth_store=self.auth, upload_root=self.root / 'uploads'))
        self.client.__enter__()
        self.headers = {name: {'Authorization': 'Bearer ' + self.auth.create_session(name, 'synthetic-password').token}
                        for name in self.users}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.auth.close()
        self.temp.cleanup()

    def ready(self, f4=False, valid_model=False):
        name = 'f4-revised-software-purchase.docx' if f4 else 'f1-software-purchase.docx'
        content = (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes()
        task = self.tasks.create_task(self.users['owner'], name, content, 'test', 'test')['task_id']
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        self.tasks.rule_snapshots.persist(task, 1)
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        response = {key: snapshot[key] for key in ('document_version', 'evidence_sha256', 'rule_version')}
        response['suggestions'] = [{'rule_id': r['rule_id'], 'suggestion': 'Synthetic model advice'} for r in snapshot['risks']]
        output = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(response)}}]}
        # Empty responses exercise supplementation; valid responses exercise exact adoption.
        with patch('backend.model_jobs._post_json', side_effect=AssertionError('No network')):
            self.tasks.model_jobs.run_once(task, 1, send=lambda _: output if valid_model else {}, authorization_key='mock-only')
        return task

    def payload(self, task):
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        return {'document_version': 1, 'base_review_version': None, 'annotation': 'Synthetic annotation',
                'risks': [{'rule_id': r['rule_id'], 'retained': True, 'risk_level': 'high',
                           'suggestion_source': 'manual', 'final_suggestion': 'Negotiated synthetic suggestion'}
                          for r in snapshot['risks']]}

    def test_edit_confirm_history_and_permissions(self):
        task = self.ready(valid_model=True)
        url = '/api/v1/tasks/' + task
        payload = self.payload(task)
        payload['risks'][0].update(suggestion_source='model', final_suggestion='')
        for role in ('owner', 'admin', 'other'):
            expected = 404 if role == 'other' else 403
            self.assertEqual(self.client.put(url + '/review', json=payload, headers=self.headers[role]).status_code, expected)
            self.assertEqual(self.client.get(url + '/review', headers=self.headers[role]).status_code, expected)
        self.assertEqual(self.client.put(url + '/review', json=payload).status_code, 401)
        legal = self.headers['legal']
        owner = self.headers['owner']
        result = self.client.put(url + '/review', json=payload, headers=legal)
        self.assertEqual(result.status_code, 200, result.text)
        draft = result.json()
        self.assertEqual(draft['risks'][0]['final_suggestion'], 'Synthetic model advice')
        self.assertEqual((draft['review_version'], draft['status'], draft['risk_level']), (1, 'in_review', 'high'))
        self.assertEqual(self.client.put(url + '/review', json=payload, headers=legal).status_code, 409)
        confirm = {'document_version': 1, 'review_version': 1, 'conclusion': '整改后复核'}
        for role in ('owner', 'admin', 'other'):
            self.assertEqual(self.client.post(url + '/confirm', json=confirm, headers=self.headers[role]).status_code,
                             404 if role == 'other' else 403)
        confirmed = self.client.post(url + '/confirm', json=confirm, headers=legal)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()['confirmed_by'], 'legal')
        self.assertEqual(self.client.post(url + '/confirm', json=confirm, headers=legal).json(), confirmed.json())
        self.assertEqual(self.client.post(url + '/confirm', json={**confirm, 'conclusion': 'changed'}, headers=legal).status_code, 409)
        visible = self.client.get(url + '/review', headers=owner).json()
        self.assertNotIn('source', visible)
        self.assertNotIn('suggestion', visible['risks'][0])
        document = self.client.get(url + '/document', headers=owner).json()
        self.assertEqual(document['review_version'], 1)
        for suffix in ('/risks/snapshot', '/model-result'):
            self.assertEqual(self.client.get(url + suffix, headers=owner).status_code, 403)
        self.assertEqual(self.client.get(url, headers=owner).json()['risk_level'], 'high')
        self.assertEqual(self.client.get('/api/v1/tasks?risk_level=high', headers=owner).json()['total'], 1)
        self.assertEqual(self.client.get('/api/v1/tasks?risk_level=high', headers=self.headers['admin']).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/tasks?risk_level=high', headers=self.headers['other']).json()['total'], 0)

        payload['base_review_version'] = 1
        payload['risks'][0]['retained'] = False
        payload['risks'][1]['risk_level'] = 'low'
        draft2 = self.client.put(url + '/review', json=payload, headers=legal).json()
        self.assertEqual((draft2['review_version'], draft2['risk_level']), (2, 'low'))
        self.assertEqual(self.client.get(url + '/review', headers=owner).json(), visible)
        self.assertEqual(self.client.get(url + '/risks', headers=owner).json(), visible)
        self.assertEqual(self.client.get(url + '/review?review_version=2', headers=owner).status_code, 403)
        summary = self.client.get(url, headers=owner).json()
        self.assertEqual((summary['legal_status'], summary['writeback_status'], summary['risk_level']), ('in_review', 'not_written', None))
        self.assertEqual(summary['latest_confirmed_version'], {'document_version': 1, 'review_version': 1})
        self.assertEqual(self.client.get('/api/v1/tasks?risk_level=high', headers=owner).json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/tasks?risk_level=low', headers=owner).json()['total'], 0)
        self.assertEqual(self.client.post(url + '/confirm', json=confirm, headers=legal).status_code, 409)
        self.assertEqual(self.client.post(url + '/confirm', json={**confirm, 'review_version': 2}, headers=legal).status_code, 200)
        old = self.client.get(url + '/review?review_version=1', headers=owner).json()
        self.assertEqual(old, visible)
        name = 'f4-revised-software-purchase.docx'
        self.tasks.add_document_version(task, self.users['owner'], 1, name,
            (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes())
        self.assertEqual(self.client.get(url + '/document', headers=owner).json()['document_version'], 1)
        self.assertEqual(self.client.get(url + '/document?document_version=2', headers=owner).status_code, 403)
        self.assertIsNone(self.client.get(url, headers=owner).json()['risk_level'])
        # A new store/connection reads the exact confirmed history, with no machine rerun.
        other_auth = AuthStore(self.root / 'test.sqlite3')
        try:
            other_tasks = TaskStore(other_auth, self.root / 'uploads')
            other_tasks.initialize()
            self.assertEqual(other_tasks.reviews.read(task, self.users['owner'], review_version=1), visible)
        finally:
            other_auth.close()

    def test_validation_evidence_and_atomicity(self):
        task = self.ready()
        url = '/api/v1/tasks/' + task
        legal = self.headers['legal']
        payload = self.payload(task)
        for bad in ({**payload, 'risks': []}, {**payload, 'document_version': 2},
                    {**payload, 'extra': 'not accepted'}):
            self.assertIn(self.client.put(url + '/review', json=bad, headers=legal).status_code, (409, 422))
        bad = copy.deepcopy(payload)
        bad['risks'][0]['suggestion_source'] = 'model'
        bad['risks'][0]['final_suggestion'] = ''
        self.assertEqual(self.client.put(url + '/review', json=bad, headers=legal).status_code, 422)
        self.assertIsNone(self.tasks.get_task(task, self.users['legal'])['review_version'])
        payload['risks'][0]['suggestion_source'] = 'rule'
        payload['risks'][0]['final_suggestion'] = ''
        saved = self.client.put(url + '/review', json=payload, headers=legal).json()
        self.assertEqual(saved['risks'][0]['final_suggestion'], saved['source']['rules']['risks'][0]['suggestion'])
        with self.auth.connection:
            self.auth.connection.execute("UPDATE parsed_documents SET fields_json='[]' WHERE task_id=?", (task,))
        confirm = {'document_version': 1, 'review_version': 1, 'conclusion': 'Synthetic conclusion'}
        self.assertEqual(self.client.post(url + '/confirm', json=confirm, headers=legal).status_code, 409)
        self.assertEqual(self.tasks.get_task(task, self.users['legal'])['legal_status'], 'in_review')
        self.assertEqual(self.client.get(url + '/review', headers=self.headers['owner']).status_code, 403)
        with self.auth.connection:
            self.auth.connection.execute("UPDATE review_versions SET payload_json='{}' WHERE task_id=?", (task,))
        self.assertEqual(self.client.get(url + '/review', headers=legal).json()['code'], 'REVIEW_EVIDENCE_INVALID')

    def test_no_risk_and_cross_connection_conflict(self):
        task = self.ready(True)
        payload = ReviewRequest(**self.payload(task))
        second = AuthStore(self.root / 'test.sqlite3')
        try:
            second_tasks = TaskStore(second, self.root / 'uploads')
            second_tasks.initialize()
            def save(tasks):
                try:
                    return tasks.reviews.save(task, self.users['legal'], payload)['review_version']
                except Exception as error:
                    return getattr(error, 'code', str(error))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, (self.tasks, second_tasks)))
            self.assertCountEqual(results, [1, 'REVIEW_VERSION_CONFLICT'])
            url = '/api/v1/tasks/' + task
            review = self.client.get(url + '/review', headers=self.headers['legal']).json()
            self.assertIsNone(review['risk_level'])
            self.assertEqual(review['risk_summary'], '未发现已启用规则风险')
            response = self.client.post(url + '/confirm', headers=self.headers['legal'], json={
                'document_version': 1, 'review_version': 1, 'conclusion': '演示复核完成'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get(url + '/review', headers=self.headers['owner']).json()['risks'], [])
        finally:
            second.close()

    def test_atomic_failure_and_unfinished_machine(self):
        task = self.ready()
        payload = ReviewRequest(**self.payload(task))
        with self.auth.connection:
            self.auth.connection.execute("""CREATE TRIGGER fail_review_update BEFORE UPDATE OF legal_status ON tasks
                BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.reviews.save(task, self.users['legal'], payload)
        self.assertEqual(self.auth.connection.execute('SELECT COUNT(*) FROM review_versions').fetchone()[0], 0)
        self.assertIsNone(self.tasks.get_task(task, self.users['legal'])['review_version'])
        with self.auth.connection:
            self.auth.connection.execute("UPDATE tasks SET machine_status='reviewing' WHERE id=?", (task,))
        response = self.client.put('/api/v1/tasks/' + task + '/review', headers=self.headers['legal'], json=payload.model_dump())
        self.assertEqual(response.json()['code'], 'REVIEW_NOT_READY')

    def test_confirmed_pdf_preview(self):
        from backend.pdf_job import run_pdf_once
        name = 'f2-text-software-purchase.pdf'
        content = (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes()
        task = self.tasks.create_task(self.users['owner'], name, content, 'test', 'test')['task_id']
        run_pdf_once(self.tasks.jobs)
        self.tasks.rule_snapshots.persist(task, 1)
        self.tasks.model_jobs.run_once(task, 1, send=lambda _: {}, authorization_key='mock-only')
        url = '/api/v1/tasks/' + task
        self.assertEqual(self.client.get(url + '/document/preview', headers=self.headers['owner']).status_code, 403)
        self.assertEqual(self.client.put(url + '/review', headers=self.headers['legal'], json=self.payload(task)).status_code, 200)
        self.assertEqual(self.client.post(url + '/confirm', headers=self.headers['legal'], json={
            'document_version': 1, 'review_version': 1, 'conclusion': '整改后复核'}).status_code, 200)
        self.assertEqual(self.client.get(url + '/document/preview', headers=self.headers['owner']).content, content)
        for role in ('admin', 'other'):
            self.assertEqual(self.client.get(url + '/document/preview', headers=self.headers[role]).status_code,
                             403 if role == 'admin' else 404)
        self.assertEqual(self.client.get(url + '/document/preview?document_version=2', headers=self.headers['owner']).status_code, 403)


if __name__ == '__main__':
    unittest.main()
