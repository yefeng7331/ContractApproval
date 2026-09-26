"""Persistent mock comments: temporary SQLite, synthetic F1/F6, no network."""

import sqlite3
import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.main import create_app

from backend.auth import AuthStore
from backend.tasks import TaskStore
from backend.reviews import ReviewRequest, ConfirmRequest
from backend.writeback import WritebackRequest, render_comment
from backend.mock_pending import MOCK_PENDING_ID
from samples.f6_writeback_failure import MockCommentSink
from tests.test_reviews import ReviewTests as Fixture


class WritebackTests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    ready = Fixture.ready
    payload = Fixture.payload

    def confirmed(self):
        task = self.ready()
        payload = self.payload(task)
        payload['annotation'] = '<script>test</script> [link](https://example.invalid)'
        self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**payload))
        self.tasks.reviews.confirm(task, self.users['legal'], ConfirmRequest(
            document_version=1, review_version=1, conclusion='整改后复核'))
        return task

    def post(self, task, version=1, role='legal', target=MOCK_PENDING_ID):
        return self.client.post(f'/api/v1/tasks/{task}/mock-writeback', headers=self.headers[role],
                                json={'review_version': version, 'mock_approval_id': target})

    def read(self, task, role='legal', version=1):
        return self.client.get(f'/api/v1/tasks/{task}/mock-writeback?review_version={version}',
                               headers=self.headers[role])

    def test_http_binding_permissions_and_f6_retry(self):
        task = self.ready()
        self.assertEqual(self.post(task).status_code, 409)
        self.assertIsNone(self.auth.connection.execute('SELECT mock_approval_id FROM tasks WHERE id=?', (task,)).fetchone()[0])
        self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**self.payload(task)))
        self.assertEqual(self.post(task).status_code, 409)
        self.tasks.reviews.confirm(task, self.users['legal'], ConfirmRequest(document_version=1, review_version=1, conclusion='整改后复核'))
        self.assertEqual(self.post(task, target='missing').status_code, 404)
        self.assertEqual(self.read(task).json()['state'], 'not_written')
        self.assertEqual(self.client.get('/api/v1/mock-writeback-targets', headers=self.headers['legal']).json()['items'][0]['id'], MOCK_PENDING_ID)
        for role in ('owner', 'other', 'admin'):
            self.assertEqual(self.post(task, role=role).status_code, 403)
            self.assertEqual(self.client.get('/api/v1/mock-writeback-targets', headers=self.headers[role]).status_code, 403)
        self.assertEqual(self.read(task, 'other').status_code, 404)
        url = f'/api/v1/tasks/{task}/mock-writeback'
        self.assertEqual(self.client.get(url+'?review_version=1').status_code, 401)
        self.assertEqual(self.client.post(url, json={}).status_code, 401)
        self.assertEqual(self.client.post(url, headers=self.headers['legal'], json={'review_version': True, 'mock_approval_id': MOCK_PENDING_ID}).status_code, 422)
        self.assertEqual(self.post(task).json()['state'], 'writing')
        self.assertEqual(len(self.post(task).json()['attempts']), 1)
        sink = MockCommentSink()
        def f6(payload):
            text = render_comment(payload)
            sink.submit(task, payload['review_version'], MOCK_PENDING_ID, text)
            return text
        with patch('backend.writeback.render_comment', side_effect=f6):
            self.assertEqual(self.tasks.writebacks.run_next(), 'failed')
            failed = self.read(task).json()
            self.assertEqual((failed['comment_id'], failed['error']), (None, 'MOCK_WRITEBACK_FAILED'))
            self.assertEqual(sink.comment_count, 0)
            self.assertEqual(self.post(task).json()['state'], 'writing')
            self.assertEqual(self.tasks.writebacks.run_next(), 'success')
        success = self.read(task).json()
        self.assertEqual([a['state'] for a in success['attempts']], ['failed', 'success'])
        self.assertTrue(all(a['finished_at'] for a in success['attempts']))
        self.assertEqual(self.post(task).json()['comment_id'], success['comment_id'])
        self.assertEqual(len(self.post(task).json()['attempts']), 2)
        self.assertEqual(self.post(task, target='other-target').status_code, 409)
        self.assertIn('模拟回写', success['markdown'])
        self.assertNotIn('markdown', self.read(task, 'admin').json())
        self.assertNotIn('attempts', self.read(task, 'owner').json())
        self.assertNotIn('error', self.read(task, 'owner').json())
        self.assertEqual(self.read(task, 'owner').json()['markdown'], success['markdown'])
        self.assertEqual(self.auth.connection.execute('SELECT writeback_status FROM tasks WHERE id=?', (task,)).fetchone()[0], 'success')
        self.assertTrue(all(r['state'] == 'pending' for r in self.tasks.reports.status(task, self.users['legal'], 1)['reports']))

    def test_history_restart_and_concurrent_connections(self):
        task = self.confirmed()
        request = WritebackRequest(review_version=1, mock_approval_id=MOCK_PENDING_ID)
        other_auth = AuthStore(self.root/'test.sqlite3')
        other_auth.initialize()
        restarted = TaskStore(other_auth, self.root/'uploads')
        restarted.initialize()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda store: store.submit(task, self.users['legal'], request),
                                        [self.tasks.writebacks, restarted.writebacks]))
            self.assertTrue(all(r['state'] == 'writing' and len(r['attempts']) == 1 for r in results))
            payload = self.payload(task)
            payload.update(base_review_version=1, annotation='new draft must not leak')
            self.tasks.reviews.save(task, self.users['legal'], ReviewRequest(**payload))
            self.assertEqual(restarted.writebacks.run_next(), 'success')
            old = self.read(task).json()
            self.assertNotIn('new draft', old['markdown'])
            self.assertNotIn('<script>', old['markdown'])
            self.assertNotIn('[link](', old['markdown'])
            self.assertEqual(self.auth.connection.execute('SELECT writeback_status FROM tasks WHERE id=?', (task,)).fetchone()[0], 'not_written')
            self.assertEqual(self.read(task, version=2).status_code, 409)
            self.tasks.reviews.confirm(task, self.users['legal'], ConfirmRequest(document_version=1, review_version=2, conclusion='新版结论'))
            self.assertEqual(self.post(task, version=2).json()['state'], 'writing')
            with ThreadPoolExecutor(max_workers=2) as pool:
                states = list(pool.map(lambda store: store.run_next(), [self.tasks.writebacks, restarted.writebacks]))
            self.assertEqual(states.count('success'), 1)
            self.assertNotEqual(old['comment_id'], self.read(task, version=2).json()['comment_id'])
            self.assertEqual(self.post(task).json()['comment_id'], old['comment_id'])
        finally:
            other_auth.close()
        # Reopen the database, not merely another store on an existing connection.
        reopened = AuthStore(self.root/'test.sqlite3')
        try:
            store = TaskStore(reopened, self.root/'uploads')
            store.initialize()
            self.assertIsNone(store.writebacks.run_next())
            self.assertEqual(store.writebacks.read(task, self.users['legal'], 1)['comment_id'], old['comment_id'])
        finally:
            reopened.close()

    def test_expired_worker_cannot_overwrite_and_publication_rolls_back(self):
        task = self.confirmed()
        self.post(task)
        db = self.auth.connection
        # A failed transaction cannot publish a comment without its attempt and task state.
        db.execute("CREATE TRIGGER reject_attempt BEFORE UPDATE OF finished_at ON writeback_attempts BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.tasks.writebacks.run_next()
        self.assertEqual(self.read(task).json()['state'], 'writing')
        self.assertIsNone(self.read(task).json()['comment_id'])
        db.execute('DROP TRIGGER reject_attempt')
        db.execute("UPDATE mock_writebacks SET lease_until='2000-01-01'")
        db.commit()
        def expired(payload):
            db.execute("UPDATE mock_writebacks SET lease_until='2000-01-01'")
            db.commit()
            with patch('backend.writeback.render_comment', side_effect=render_comment):
                self.assertEqual(self.tasks.writebacks.run_next(), 'success')
            return 'stale worker must not publish'
        with patch('backend.writeback.render_comment', side_effect=expired):
            self.assertEqual(self.tasks.writebacks.run_next(), 'stale_lease')
        result = self.read(task).json()
        self.assertNotIn('stale worker', result['markdown'])
        self.assertEqual([a['error'] for a in result['attempts']], ['WRITEBACK_INTERRUPTED', 'WRITEBACK_INTERRUPTED', None])

    def test_service_worker_and_attachment_isolation(self):
        task = self.confirmed()
        self.post(task)
        # Upload a replacement before the old confirmed comment is processed.
        from pathlib import Path
        attachment = (Path(__file__).resolve().parents[1]/'samples/f4-revised-software-purchase.docx').read_bytes()
        response = self.client.post(f'/api/v1/tasks/{task}/documents', headers=self.headers['owner'],
                                    data={'base_document_version': '1'},
                                    files={'file': ('revision.docx', attachment)})
        self.assertEqual(response.status_code, 201, response.text)
        service_auth = AuthStore(self.root/'test.sqlite3')
        try:
            with TestClient(create_app(auth_store=service_auth, upload_root=self.root/'uploads',
                                      auto_process_writebacks=True)):
                deadline = time.monotonic()+8
                while time.monotonic() < deadline:
                    if self.read(task).json()['state'] == 'success':
                        break
                    time.sleep(0.05)
                self.assertEqual(self.read(task).json()['state'], 'success')
                self.assertEqual(self.read(task).json()['document_version'], 1)
                current = self.auth.connection.execute('SELECT current_document_version,writeback_status,mock_approval_id FROM tasks WHERE id=?', (task,)).fetchone()
                self.assertEqual(tuple(current), (2, 'not_written', MOCK_PENDING_ID))
        finally:
            service_auth.close()


del Fixture

if __name__ == '__main__':
    unittest.main()
