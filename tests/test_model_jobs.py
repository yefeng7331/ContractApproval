"""Durable model workflow smoke. Temporary SQLite, synthetic files, mocked sends."""

import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.errors import ApiError
from backend.main import create_app
from backend.tasks import TaskStore


class ModelJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.auth = AuthStore(self.root / 'test.sqlite3')
        self.auth.initialize()
        self.users = {name: self.auth.create_user(name, role, 'synthetic-password')
            for name, role in [('owner', 'business'), ('other', 'business'), ('legal', 'legal'), ('admin', 'admin')]}
        self.tasks = TaskStore(self.auth, self.root / 'uploads')
        self.tasks.initialize()
        self.jobs = self.tasks.model_jobs

    def tearDown(self):
        self.auth.close()
        self.temp.cleanup()

    def ready(self, f4=False):
        name = 'f4-revised-software-purchase.docx' if f4 else 'f1-software-purchase.docx'
        content = (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes()
        task = self.tasks.create_task(self.users['owner'], name, content, 'test', 'test')['task_id']
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        self.tasks.rule_snapshots.persist(task, 1)
        return task

    def response(self, task):
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        content = {k: snapshot[k] for k in ('document_version', 'evidence_sha256', 'rule_version')}
        content['suggestions'] = [{'rule_id': r['rule_id'], 'suggestion': 'Synthetic legal draft.'} for r in snapshot['risks']]
        return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(content)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}

    def send(self, task, grant='test-grant'):
        return self.jobs.run_once(task, 1, send=lambda _: self.response(task), authorization_key=grant)

    def test_free_completion_and_paid_wait(self):
        paid, free = self.ready(), self.ready(True)
        with patch('backend.model_jobs._post_json', side_effect=AssertionError), patch('backend.model_config.load_api_key', side_effect=AssertionError):
            self.assertEqual(self.jobs.run_next()['code'], 'MODEL_NOT_REQUIRED')
            self.assertEqual(self.jobs.run_once(paid, 1)['code'], 'MODEL_AUTHORIZATION_REQUIRED')
        result = self.jobs.read(free, self.users['legal'])
        self.assertEqual(result['suggestions'], [])
        self.assertFalse(result['requires_legal_supplement'])
        self.assertEqual(self.tasks.model_budget.summary()['held_microyuan'], 0)
        row = self.auth.connection.execute('SELECT machine_status,legal_status FROM tasks WHERE id=?', (free,)).fetchone()
        self.assertEqual(tuple(row), ('completed', 'pending'))
        with patch('backend.model_config.load_api_key', side_effect=AssertionError):
            with self.assertRaises(ApiError) as error:
                self.jobs.run_authorized_f1(free, 1)
        self.assertEqual(error.exception.code, 'MODEL_SYNTHETIC_F1_ONLY')

    def test_saved_result_api_restart_versions_and_integrity(self):
        task = self.ready()
        self.assertEqual(self.send(task)['state'], 'completed')
        self.assertEqual(self.tasks.model_budget.summary()['estimated_microyuan'], 60)
        result = self.jobs.read(task, self.users['legal'])
        self.assertEqual(len(result['suggestions']), 2)
        self.assertIsNone(result['review_version'])
        self.auth.close()
        self.auth = AuthStore(self.root / 'test.sqlite3')
        self.auth.initialize()
        self.tasks = TaskStore(self.auth, self.root / 'uploads')
        self.tasks.initialize()
        self.jobs = self.tasks.model_jobs
        self.assertEqual(self.jobs.read(task, self.users['legal']), result)
        with TestClient(create_app(auth_store=self.auth, upload_root=self.root / 'uploads')) as client:
            url = f'/api/v1/tasks/{task}/model-result'
            self.assertEqual(client.get(url).status_code, 401)
            for name, expected in [('owner', 403), ('other', 404), ('admin', 403), ('legal', 200)]:
                token = client.post('/api/v1/sessions', json={'username': name, 'password': 'synthetic-password'}).json()['access_token']
                headers = {'Authorization': 'Bearer ' + token}
                self.assertEqual(client.get(url, headers=headers).status_code, expected)
            self.assertEqual(client.get(url + '?document_version=0', headers=headers).status_code, 422)
            with self.auth.connection:
                self.auth.connection.execute("UPDATE tasks SET legal_status='confirmed' WHERE id=?", (task,))
            name = 'f4-revised-software-purchase.docx'
            self.tasks.add_document_version(task, self.users['owner'], 1, name,
                (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes())
            self.assertEqual(client.get(url, headers=headers).status_code, 409)
            self.assertEqual(client.get(url + '?document_version=1', headers=headers).json(), result)
            with self.auth.connection:
                self.auth.connection.execute("UPDATE model_jobs SET result_json='[]' WHERE task_id=?", (task,))
            self.assertEqual(client.get(url + '?document_version=1', headers=headers).json()['code'], 'MODEL_RESULT_INVALID')

    def test_invalid_advice_and_transport_failure(self):
        task = self.ready()
        self.assertEqual(self.jobs.run_once(task, 1, send=lambda _: {'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}, authorization_key='invalid')['state'], 'completed')
        self.assertTrue(self.jobs.read(task, self.users['legal'])['requires_legal_supplement'])
        self.assertEqual(self.tasks.model_budget.summary()['estimated_microyuan'], 60)
        failed = self.ready()
        def fail(_):
            raise RuntimeError('secret-sentinel')
        output = self.jobs.run_once(failed, 1, send=fail, authorization_key='failed')
        self.assertEqual(output, {'state': 'blocked', 'code': 'MODEL_TRANSPORT_FAILED'})
        self.assertEqual(self.tasks.model_budget.summary()['held_microyuan'], 100000)
        self.assertNotIn('secret-sentinel', str(self.auth.connection.execute('SELECT * FROM model_jobs').fetchall()))

    def test_crash_recovery_no_resend(self):
        task = self.ready()
        def crash(_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.jobs.run_once(task, 1, send=crash, authorization_key='crash')
        with self.auth.connection:
            self.auth.connection.execute("UPDATE model_jobs SET deadline='2000-01-01' WHERE task_id=?", (task,))
        self.auth.close()
        self.auth = AuthStore(self.root / 'test.sqlite3')
        self.auth.initialize()
        self.tasks = TaskStore(self.auth, self.root / 'uploads')
        self.tasks.initialize()
        self.jobs = self.tasks.model_jobs
        self.jobs.refresh()
        self.assertEqual(self.jobs.run_once(task, 1, send=crash, authorization_key='crash')['code'], 'MODEL_OUTCOME_UNKNOWN')
        self.assertEqual(self.tasks.model_budget.summary()['held_microyuan'], 100000)

    def test_concurrent_dispatch_and_late_result(self):
        task = self.ready()
        response = self.response(task)
        entered, release = Event(), Event()
        def send(_):
            entered.set()
            if not release.wait(10):
                raise TimeoutError
            return response
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.jobs.run_once, task, 1, send=send, authorization_key='one')
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.jobs.run_once(task, 1, send=send, authorization_key='two')['state'], 'running')
                with self.auth.lock, self.auth.connection:
                    self.auth.connection.execute("UPDATE model_jobs SET deadline='2000-01-01' WHERE task_id=?", (task,))
                self.jobs.refresh()
            finally:
                release.set()
            self.assertEqual(first.result()['code'], 'MODEL_LATE_RESULT')
        self.assertEqual(self.tasks.model_budget.summary()['estimated_microyuan'], 60)
        self.assertEqual(self.auth.connection.execute('SELECT machine_status FROM tasks WHERE id=?', (task,)).fetchone()[0], 'blocked')
        another = self.ready()
        with self.assertRaises(ApiError) as used:
            self.send(another, 'one')
        self.assertEqual(used.exception.code, 'MODEL_AUTHORIZATION_USED')

    def test_background_worker_finishes_only_free_version(self):
        paid, free = self.ready(), self.ready(True)
        with patch('backend.model_jobs._post_json', side_effect=AssertionError), TestClient(
                create_app(auth_store=self.auth, upload_root=self.root / 'uploads', auto_process_models=True)):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with self.auth.lock:
                    row = self.auth.connection.execute('SELECT machine_status FROM tasks WHERE id=?', (free,)).fetchone()
                if row[0] == 'completed':
                    break
                time.sleep(.05)
            self.assertEqual(row[0], 'completed')
            self.assertEqual(self.jobs.run_once(paid, 1)['code'], 'MODEL_AUTHORIZATION_REQUIRED')

    def test_late_old_version_never_completes_new_version(self):
        task = self.ready()
        response = self.response(task)
        def replace(_):
            # Simulate a concurrent administrative recovery and attachment replacement.
            with self.auth.connection:
                self.auth.connection.execute("UPDATE tasks SET machine_status='blocked', recovery_action='replace_attachment' WHERE id=?", (task,))
            name = 'f4-revised-software-purchase.docx'
            self.tasks.add_document_version(task, self.users['owner'], 1, name,
                (Path(__file__).resolve().parents[1] / 'samples' / name).read_bytes())
            return response
        self.assertEqual(self.jobs.run_once(task, 1, send=replace, authorization_key='old')['state'], 'superseded')
        self.assertEqual(tuple(self.auth.connection.execute('SELECT current_document_version,machine_status FROM tasks WHERE id=?', (task,)).fetchone()), (2, 'pending'))
        self.assertEqual(self.jobs.read(task, self.users['legal'], 1)['document_version'], 1)

    def test_budget_rejection_does_not_send(self):
        task = self.ready()
        with patch.object(self.tasks.model_budget, 'summary', return_value={'estimated_microyuan': 49950000, 'held_microyuan': 0}):
            self.assertEqual(self.jobs.run_once(task, 1, send=lambda _: self.fail('must not send'), authorization_key='no-budget')['code'], 'BUDGET_LIMIT')
        self.assertEqual(tuple(self.auth.connection.execute('SELECT machine_status,recovery_action FROM tasks WHERE id=?', (task,)).fetchone()), ('blocked', 'budget_decision'))

    def test_atomic_reservation_and_changed_evidence(self):
        task = self.ready()
        self.jobs.refresh()
        with self.auth.connection:
            self.auth.connection.execute("CREATE TRIGGER fail_dispatch BEFORE UPDATE ON model_jobs WHEN NEW.state='running' BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.send(task)
        self.assertEqual(self.tasks.model_budget.summary()['held_microyuan'], 0)
        self.assertEqual(self.auth.connection.execute('SELECT state FROM model_jobs WHERE task_id=?', (task,)).fetchone()[0], 'pending')
        # A changed rule version cannot consume the saved authorization.
        with patch('backend.rule_snapshot.RULE_VERSION', 'future-version'):
            self.assertEqual(self.send(task)['code'], 'RULE_VERSION_CHANGED')


if __name__ == '__main__':
    unittest.main()
