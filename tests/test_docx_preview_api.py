"""Standalone preview persistence/API smoke; temporary DB, no model calls."""

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.docx_parser import parse_docx
from backend.docx_preview import find_converter, map_preview
from backend.errors import ApiError
from backend.main import create_app
from backend.tasks import TaskStore

SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


class DocxPreviewApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = AuthStore(self.root / 'test.sqlite3')
        self.auth.initialize()
        self.addCleanup(self.auth.close)
        self.users = {name: self.auth.create_user(name, role, 'synthetic-password')
            for name, role in [('owner', 'business'), ('other', 'business'),
                               ('legal', 'legal'), ('admin', 'admin')]}
        self.tasks = TaskStore(self.auth, self.root / 'uploads')
        self.tasks.initialize()
        self.client = TestClient(create_app(auth_store=self.auth, upload_root=self.root / 'uploads'))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {name: {'Authorization': 'Bearer ' + self.client.post('/api/v1/sessions',
            json={'username': name, 'password': 'synthetic-password'}).json()['access_token']}
            for name in self.users}

    def upload(self, filename='f1-software-purchase.docx'):
        task = self.tasks.create_task(self.users['owner'], filename,
            (SAMPLES / filename).read_bytes(), 'test', 'test')['task_id']
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        return task

    def read(self, task, suffix='preview-map', **kwargs):
        return self.client.get(f'/api/v1/tasks/{task}/document/{suffix}',
            headers=self.headers['legal'], **kwargs)

    @staticmethod
    def fake_convert(content, version):
        # F2 is a mapping oracle only; this helper does not claim real conversion.
        pdf = (SAMPLES / 'f2-text-software-purchase.pdf').read_bytes()
        mapping = map_preview(parse_docx(content, version), pdf)
        mapping['source_sha256'] = hashlib.sha256(content).hexdigest()
        return pdf, mapping

    def test_permissions_persistence_versions_and_immutable_evidence(self):
        task = self.upload()
        self.tasks.rule_snapshots.persist(task, 1)
        snapshot = self.tasks.get_rule_snapshot(task, self.users['legal'])
        original = self.tasks.get_parsed_document(task, self.users['legal'])
        self.assertEqual(self.read(task).json()['code'], 'DOCX_PREVIEW_NOT_READY')
        with patch('backend.preview_store.convert_docx', side_effect=self.fake_convert) as convert:
            self.assertEqual(self.tasks.previews.build(task, 1)['state'], 'ready')
            self.assertEqual(self.tasks.previews.build(task, 1)['state'], 'ready')
            convert.assert_called_once()
        for suffix in ('preview', 'preview-map'):
            url = f'/api/v1/tasks/{task}/document/{suffix}'
            self.assertEqual(self.client.get(url).status_code, 401)
            for name, status in [('owner', 403), ('other', 404), ('admin', 403)]:
                self.assertEqual(self.client.get(url, headers=self.headers[name]).status_code, status)
            self.assertEqual(self.read(task, suffix, params={'document_version': 0}).status_code, 422)
            self.assertEqual(self.read(task, suffix, params={'document_version': 9}).status_code, 404)
        mapping = self.read(task).json()
        self.assertTrue(mapping['persisted'])
        self.assertTrue(all(p['locatable'] for p in mapping['paragraphs']))
        self.assertTrue(all(c['locatable'] for c in mapping['clauses']))
        self.assertEqual(snapshot, self.tasks.get_rule_snapshot(task, self.users['legal']))
        document = self.tasks.get_parsed_document(task, self.users['legal'])
        original['preview_available'] = True
        self.assertEqual(document, original)
        restarted = TaskStore(self.auth, self.root / 'uploads')
        restarted.initialize()
        with patch('backend.preview_store.convert_docx', side_effect=AssertionError):
            self.assertEqual(restarted.previews.read(task, self.users['legal'])[0], self.read(task, 'preview').content)
        with self.auth.connection:
            self.auth.connection.execute("UPDATE tasks SET machine_status='blocked',blocked_code='SYNTHETIC',recovery_action='replace_attachment' WHERE id=?", (task,))
        response = self.client.post(f'/api/v1/tasks/{task}/documents', headers=self.headers['owner'],
            data={'base_document_version': '1'}, files={'file': ('revised.docx',
                (SAMPLES / 'f4-revised-software-purchase.docx').read_bytes())})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.read(task).json()['code'], 'DOCUMENT_NOT_READY')
        self.assertEqual(self.read(task, params={'document_version': 1}).json(), mapping)

    def test_corrupted_artifacts_and_source_are_refused(self):
        task = self.upload()
        with patch('backend.preview_store.convert_docx', side_effect=self.fake_convert):
            self.assertEqual(self.tasks.previews.build(task, 1)['state'], 'ready')
        for table, column, value in [('docx_previews', 'mapping_json', '{}'),
                ('docx_previews', 'preview_path', str(self.root / 'outside.pdf')),
                ('parsed_documents', 'normalized_text', 'tampered')]:
            with self.subTest(column=column):
                old = self.auth.connection.execute(f'SELECT {column} FROM {table} WHERE task_id=?', (task,)).fetchone()[0]
                with self.auth.connection:
                    self.auth.connection.execute(f'UPDATE {table} SET {column}=? WHERE task_id=?', (value, task))
                self.assertEqual(self.read(task).json()['code'], 'PREVIEW_EVIDENCE_CHANGED')
                with self.auth.connection:
                    self.auth.connection.execute(f'UPDATE {table} SET {column}=? WHERE task_id=?', (old, task))
        for table, column in [('docx_previews', 'preview_path'), ('document_versions', 'file_path')]:
            path = Path(self.auth.connection.execute(f'SELECT {column} FROM {table} WHERE task_id=?', (task,)).fetchone()[0])
            old = path.read_bytes()
            path.write_bytes(b'tampered')
            self.assertEqual(self.read(task, 'preview').json()['code'], 'PREVIEW_EVIDENCE_CHANGED')
            path.write_bytes(old)

    def test_failure_duplicate_claim_and_expired_conversion(self):
        task = self.upload()
        def interrupted(content, version):
            self.assertEqual(self.tasks.previews.build(task, version)['state'], 'running')
            with self.auth.connection:
                self.auth.connection.execute("UPDATE docx_previews SET deadline='2000-01-01' WHERE task_id=?", (task,))
            self.tasks.previews.run_next()
            return self.fake_convert(content, version)
        with patch('backend.preview_store.convert_docx', side_effect=interrupted):
            self.assertEqual(self.tasks.previews.build(task, 1)['code'], 'DOCX_PREVIEW_INTERRUPTED')
        self.assertEqual(self.read(task).json()['code'], 'DOCX_PREVIEW_INTERRUPTED')
        second = self.upload()
        with patch('backend.preview_store.convert_docx', side_effect=ApiError(409, 'DOCX_PREVIEW_DEPENDENCY_MISSING', 'missing')) as convert:
            self.assertEqual(self.tasks.previews.run_next()['state'], 'failed')
            self.assertEqual(self.tasks.previews.run_next()['state'], 'idle')
            convert.assert_called_once()
        self.assertEqual(self.read(second).json()['code'], 'DOCX_PREVIEW_DEPENDENCY_MISSING')

    @unittest.skipUnless(find_converter(), 'LibreOffice not installed')
    def test_real_f1_f4_automatic_worker(self):
        tasks = [self.upload(filename) for filename in
                 ('f1-software-purchase.docx', 'f4-revised-software-purchase.docx')]
        with TestClient(create_app(auth_store=self.auth, upload_root=self.root / 'uploads',
                auto_process_previews=True)):
            deadline = time.monotonic() + 140
            for task in tasks:
                while time.monotonic() < deadline:
                    response = self.read(task)
                    if response.status_code == 200:
                        break
                    if response.json()['code'] != 'DOCX_PREVIEW_NOT_READY':
                        self.fail(response.text)
                    time.sleep(0.1)
                self.assertEqual(response.status_code, 200, response.text)
                mapping = response.json()
                self.assertTrue(mapping['text_matches'])
                self.assertEqual(mapping['page_count'], 1)
                self.assertEqual(len(mapping['paragraphs']), 12)
                self.assertTrue(all(p['locatable'] for p in mapping['paragraphs']))
                pdf = self.read(task, 'preview')
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(hashlib.sha256(pdf.content).hexdigest(), mapping['preview_sha256'])
                self.assertEqual(pdf.headers['content-type'], 'application/pdf')


if __name__ == '__main__':
    unittest.main()
