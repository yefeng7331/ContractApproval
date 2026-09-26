"""F6 through HTTP, durable attempts and real DOCX parsing; no network."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from backend.auth import AuthStore
from backend.tasks import TaskStore
from backend.docx_job import run_docx_once
from samples.f6_pending_timeout import fetch_attachment
from tests.test_reviews import ReviewTests as Fixture


class PendingImportTests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def import_task(self):
        return self.client.post('/api/v1/mock-pending/demo-f1-001/import', headers=self.headers['owner'])

    def retry(self, task, role='admin', version=1):
        return self.client.post(f'/api/v1/tasks/{task}/retry',
            json={'document_version': version}, headers=self.headers[role])

    def history(self, task):
        response = self.client.get(f'/api/v1/tasks/{task}/attachment-attempts', headers=self.headers['admin'])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['attempts']

    def test_http_timeout_permissions_retry_and_parse(self):
        with patch('backend.main.fetch_pending_attachment', side_effect=fetch_attachment) as fetch:
            response = self.import_task()
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json(); task = result['task_id']
            self.assertEqual((result['machine_status'], result['blocked_code'], result['recovery_action'], result['attempt_count']),
                ('blocked', 'ATTACHMENT_FETCH_TIMEOUT', 'admin_retry', 1))
            self.assertIsNone(result['submission']['sha256'])
            self.assertIsNone(result['risk_level'])
            for table in ('document_versions', 'processing_jobs', 'parsed_documents', 'review_versions'):
                self.assertEqual(self.auth.connection.execute(f'SELECT COUNT(*) FROM {table} WHERE task_id=?', (task,)).fetchone()[0], 0)
            self.assertEqual(self.client.get('/api/v1/tasks', headers=self.headers['owner']).json()['total'], 1)
            self.assertEqual(self.client.get(f'/api/v1/tasks/{task}', headers=self.headers['other']).status_code, 404)
            for role in ('owner', 'other', 'legal'):
                self.assertEqual(self.retry(task, role).status_code, 403)
                self.assertEqual(self.client.get(f'/api/v1/tasks/{task}/attachment-attempts', headers=self.headers[role]).status_code, 403)
            self.assertEqual(self.client.post(f'/api/v1/tasks/{task}/retry', json={'document_version': 1}).status_code, 401)
            self.assertEqual(self.retry(task, version=2).status_code, 409)
            self.assertEqual(len(self.history(task)), 1)
            response = self.retry(task)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((response.json()['document_version'],response.json()['attempt_count']), (1, 2))
            self.assertEqual([call.args[0] for call in fetch.call_args_list], [1, 2])
            self.assertEqual([r['state'] for r in self.history(task)], ['failed', 'completed'])
            self.assertEqual(self.history(task)[0]['error_code'], 'ATTACHMENT_FETCH_TIMEOUT')
            self.assertEqual(self.retry(task).status_code, 409)
            self.assertEqual(len(self.history(task)), 2)
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        self.tasks.rule_snapshots.run_next()
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        self.assertEqual(len(snapshot['risks']), 2)
        self.assertEqual(snapshot['document_version'], 1)
        events = self.auth.connection.execute('SELECT action FROM audit_events WHERE task_id=? ORDER BY id', (task,)).fetchall()
        self.assertEqual([r[0] for r in events[:4]], ['attachment_fetch_started', 'attachment_fetch_timeout',
            'attachment_fetch_started', 'mock_pending_imported'])

    def test_reopen_expired_attempt_and_late_result(self):
        store = self.tasks.pending_imports
        def interrupted(_):
            raise KeyboardInterrupt('simulate process stopping before download returns')
        with self.assertRaises(KeyboardInterrupt):
            store.create(self.users['owner'], interrupted)
        task = self.auth.connection.execute('SELECT id FROM tasks').fetchone()[0]
        old = self.auth.connection.execute('SELECT token FROM attachment_attempts').fetchone()[0]
        with self.auth.connection:
            self.auth.connection.execute("UPDATE attachment_attempts SET expires_at='2000-01-01T00:00:00+00:00'")
        second = AuthStore(self.root / 'test.sqlite3')
        try:
            reopened = TaskStore(second, self.root / 'uploads'); reopened.initialize()
            self.assertEqual(reopened.get_task(task, self.users['admin'])['blocked_code'], 'ATTACHMENT_FETCH_INTERRUPTED')
            reopened.pending_imports.retry(task, 1, self.users['admin'], fetch_attachment)
            store._fetch(task, old, 1, self.users['owner'], lambda _: fetch_attachment(2))
            self.assertEqual([r['state'] for r in self.history(task)], ['failed', 'completed'])
            self.assertEqual(self.auth.connection.execute('SELECT COUNT(*) FROM document_versions').fetchone()[0], 1)
            self.assertEqual(self.auth.connection.execute('SELECT COUNT(*) FROM processing_jobs').fetchone()[0], 1)
        finally:
            second.close()

    def test_concurrent_retry(self):
        store = self.tasks.pending_imports
        result = store.create(self.users['owner'], fetch_attachment); task = result['task_id']
        entered, release = Event(), Event()
        def delayed(attempt):
            entered.set()
            if not release.wait(10):
                raise TimeoutError()
            return fetch_attachment(attempt)
        second = AuthStore(self.root / 'test.sqlite3')
        try:
            other = TaskStore(second, self.root / 'uploads'); other.initialize()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(store.retry, task, 1, self.users['admin'], delayed)
                try:
                    self.assertTrue(entered.wait(5))
                    from backend.errors import ApiError
                    with self.assertRaises(ApiError) as error:
                        other.pending_imports.retry(task, 1, self.users['admin'], fetch_attachment)
                    self.assertEqual(error.exception.status_code, 409)
                finally:
                    release.set()
                future.result()
            self.assertEqual(len(self.history(task)), 2)
        finally:
            second.close()

    def test_storage_rollback_failure_history_and_invalid_attachment(self):
        import sqlite3
        with patch.object(self.tasks.jobs, 'enqueue_parse', side_effect=sqlite3.OperationalError('disk failure')):
            result = self.tasks.pending_imports.create(self.users['owner'], lambda _: fetch_attachment(2))
        task = result['task_id']
        self.assertEqual(result['blocked_code'], 'ATTACHMENT_STORE_FAILED')
        self.assertEqual(self.auth.connection.execute('SELECT COUNT(*) FROM document_versions').fetchone()[0], 0)
        self.assertEqual(list((self.root / 'uploads').rglob('*.docx')), [])
        self.assertEqual(self.history(task)[0]['error_code'], 'ATTACHMENT_STORE_FAILED')
        with patch('backend.main.fetch_pending_attachment', return_value=b'not docx'):
            response = self.retry(task)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['blocked_code'], 'ATTACHMENT_FETCH_FAILED')
        with patch('backend.main.fetch_pending_attachment', side_effect=fetch_attachment):
            self.assertEqual(self.retry(task).status_code, 200)
        self.assertEqual([r['state'] for r in self.history(task)], ['failed', 'failed', 'completed'])


del Fixture
