"""Live local F1 HTTP smoke through Vite and Uvicorn, using only synthetic data."""

import os
import re
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path
import httpx
import uvicorn

from backend.main import create_app
from backend.docx_job import run_docx_once
from backend.pdf_job import run_pdf_once
from backend.ocr import run_ocr_once
from backend.mock_pending import MOCK_PENDING_ID
from tests import test_backend_integration as integration
from tests import test_reviews as reviews


ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LocalHttpAcceptanceTests(unittest.TestCase):
    upload = integration.BackendIntegrationTests.upload
    machine = integration.BackendIntegrationTests.machine
    assert_document = integration.BackendIntegrationTests.assert_document
    confirm = integration.BackendIntegrationTests.confirm

    def setUp(self):
        reviews.ReviewTests.setUp(self)
        self.addCleanup(reviews.ReviewTests.tearDown, self)
        self.api_port = free_port()
        self.front_port = free_port()
        while self.front_port == self.api_port:
            self.front_port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(auth_store=self.auth, upload_root=self.root / 'uploads'),
            host='127.0.0.1', port=self.api_port, log_level='error', access_log=False,
        ))
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        self.addCleanup(self._stop_server)
        vite = ROOT / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'
        if not vite.is_file():
            self.fail('Missing frontend/node_modules; run npm ci in frontend first')
        env = os.environ.copy()
        env['CONTRACT_API_PROXY_TARGET'] = f'http://127.0.0.1:{self.api_port}'
        self.vite = subprocess.Popen(
            ['node', str(vite), '--host', '127.0.0.1', '--port', str(self.front_port), '--strictPort'],
            cwd=ROOT / 'frontend', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self._stop_vite)
        self.http = httpx.Client(base_url=f'http://127.0.0.1:{self.front_port}', timeout=20)
        self.addCleanup(self.http.close)
        self._wait_ready()

    def _stop_vite(self):
        self.vite.terminate()
        try:
            self.vite.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.vite.kill()
            self.vite.wait(timeout=5)

    def _stop_server(self):
        self.server.should_exit = True
        self.server_thread.join(timeout=5)

    def _wait_ready(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.vite.poll() is not None:
                self.fail('Vite exited before ready')
            try:
                if self.http.get('/').status_code == 200 and self.http.get('/api/v1/sessions/current').status_code == 401:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        self.fail('Vite/API proxy did not become ready within 20 seconds')

    def request(self, method, path, role='legal', code=200, **kwargs):
        result = self.http.request(method, '/api/v1' + path, headers=self.headers[role], **kwargs)
        self.assertEqual(result.status_code, code, result.text[:300] if result.status_code != code else '')
        return result

    def test_f1_live_proxy_chain_and_permissions(self):
        page = self.http.get('/')
        self.assertIn('text/html', page.headers['content-type'])
        entry = re.search(r'<script[^>]+src="([^"]*src/main\.tsx)"', page.text)
        self.assertIsNotNone(entry)
        self.assertEqual(self.http.get(entry.group(1)).status_code, 200)

        for role in ('owner', 'legal', 'admin'):
            login = self.http.post('/api/v1/sessions', json={
                'username': role, 'password': 'synthetic-password',
            })
            self.assertEqual(login.status_code, 200, login.text[:300])
            self.headers[role] = {'Authorization': 'Bearer ' + login.json()['access_token']}
            self.assertEqual(self.request('GET', '/sessions/current', role).json()['role'], self.users[role].role)

        task = self.upload(integration.ORACLE['F1']['file'])
        base = f'/tasks/{task}'
        self.request('GET', base, 'other', 404)
        snapshot = self.machine(task, run_docx_once)
        self.assert_document(task, 'F1')
        self.assertEqual({risk['rule_id'] for risk in snapshot['risks']}, {'DEMO-IP-01', 'DEMO-PAY-01'})
        self.tasks.previews.build(task, 1)
        self.assertTrue(self.request('GET', base + '/document/preview').content.startswith(b'%PDF'))
        self.confirm(task, snapshot)
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertIn('集成确认结论', self.request('GET', base + '/reports/markdown?review_version=1', 'owner').text)
        self.assertTrue(self.request('GET', base + '/reports/pdf?review_version=1', 'owner').content.startswith(b'%PDF'))
        self.request('POST', base + '/mock-writeback', json={'review_version': 1, 'mock_approval_id': MOCK_PENDING_ID})
        self.assertEqual(self.tasks.writebacks.run_next(), 'success')
        self.assertEqual(self.request('GET', base + '/mock-writeback?review_version=1', 'owner').json()['state'], 'success')

        for suffix in ('/audit-events', '/processing-records'):
            self.assertGreater(self.request('GET', base + suffix, 'admin').json()['total'], 0)
            self.request('GET', base + suffix, 'owner', 403)
            self.request('GET', base + suffix, 'legal', 403)
            self.assertEqual(self.http.get('/api/v1' + base + suffix).status_code, 401)

    def test_f2_pdf_live_proxy_pages_review_and_permissions(self):
        filename = 'f2-text-software-purchase.pdf'
        task = self.upload(filename)
        base = f'/tasks/{task}'
        self.request('GET', base, 'other', 404)
        self.request('GET', base + '/document', 'owner', 403)
        self.request('GET', base + '/document/preview', 'owner', 403)
        self.request('POST', base + '/confirm', code=409, json={
            'document_version': 1, 'review_version': 1, 'conclusion': '不可提前确认',
        })

        snapshot = self.machine(task, run_pdf_once)
        document = self.assert_document(task, 'F1')
        self.assertEqual(document['extraction_method'], 'text')
        self.assertEqual({risk['rule_id'] for risk in snapshot['risks']}, {'DEMO-IP-01', 'DEMO-PAY-01'})
        for risk in snapshot['risks']:
            for anchor in risk['anchors']:
                self.assertEqual(anchor['document_version'], 1)
                self.assertEqual(document['normalized_text'][anchor['start']:anchor['end']], anchor['quote'])
                self.assertEqual(anchor['page'], 2 if anchor['paragraph_index'] in (6, 7) else 3)
        preview = self.request('GET', base + '/document/preview')
        self.assertEqual(preview.content, (integration.SAMPLES / filename).read_bytes())
        self.request('GET', base + '/document/preview', 'admin', 403)
        self.assertEqual(self.http.get('/api/v1' + base + '/document/preview').status_code, 401)

        self.confirm(task, snapshot)
        self.request('GET', base + '/review', 'other', 404)
        self.assertTrue(self.request('GET', base + '/document/preview', 'owner').content.startswith(b'%PDF'))
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertIn('集成确认结论', self.request('GET', base + '/reports/markdown?review_version=1', 'owner').text)
        self.assertTrue(self.request('GET', base + '/reports/pdf?review_version=1', 'owner').content.startswith(b'%PDF'))

    def test_f3_scan_live_proxy_ocr_regions_review_and_permissions(self):
        task = self.upload('f3-clear-scan.png')
        base = f'/tasks/{task}'
        self.request('GET', base, 'other', 404)
        self.request('GET', base + '/document/preview-map', 'owner', 403)
        self.request('GET', base + '/document/preview', code=409)
        self.request('POST', base + '/confirm', code=409, json={
            'document_version': 1, 'review_version': 1, 'conclusion': '不可提前确认',
        })

        snapshot = self.machine(task, run_ocr_once)
        self.tasks.previews.build(task, 1)
        document = self.assert_document(task, 'F1', scan=True)
        self.assertEqual(document['page_count'], 1)
        self.assertEqual(len(document['paragraphs']), 12)
        self.assertTrue(document['preview_available'])
        mapping = self.request('GET', base + '/document/preview-map').json()
        self.assertEqual(mapping['document_version'], 1)
        self.assertEqual(mapping['mapping_scope'], 'ocr_line_regions')
        self.assertEqual(mapping['paragraphs'], document['paragraphs'])
        for paragraph in mapping['paragraphs']:
            self.assertEqual(paragraph['page'], 1)
            self.assertTrue(paragraph['locatable'])
            self.assertEqual(document['normalized_text'][paragraph['start']:paragraph['end']], paragraph['quote'])
        self.assertTrue(self.request('GET', base + '/document/preview').content.startswith(b'%PDF-'))
        self.assertEqual({risk['rule_id'] for risk in snapshot['risks']}, {'DEMO-IP-01', 'DEMO-PAY-01'})
        for risk in snapshot['risks']:
            self.assertEqual(risk['risk_level'], 'high')
            for anchor in risk['anchors']:
                self.assertEqual(anchor['document_version'], 1)
                self.assertEqual(anchor['page'], 1)
                self.assertTrue(anchor['locatable'])
                self.assertEqual(document['normalized_text'][anchor['start']:anchor['end']], anchor['quote'])
        for suffix in ('/document', '/document/preview', '/document/preview-map', '/risks/snapshot'):
            for role, code in (('owner', 403), ('admin', 403), ('other', 404)):
                self.request('GET', base + suffix, role, code)
            self.assertEqual(self.http.get('/api/v1' + base + suffix).status_code, 401)
        self.request('GET', base + '/document?document_version=2', code=404)

        self.confirm(task, snapshot)
        self.request('GET', base + '/review', 'other', 404)
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertIn('集成确认结论', self.request('GET', base + '/reports/markdown?review_version=1', 'owner').text)
        self.assertTrue(self.request('GET', base + '/reports/pdf?review_version=1', 'owner').content.startswith(b'%PDF'))

    def test_f4_revised_docx_live_proxy_no_false_risks_and_permissions(self):
        task = self.upload(integration.ORACLE['F4']['file'])
        base = f'/tasks/{task}'
        self.request('GET', base, 'other', 404)
        self.request('GET', base + '/risks/snapshot', code=409)
        self.request('POST', base + '/confirm', code=409, json={
            'document_version': 1, 'review_version': 1, 'conclusion': '不可提前确认',
        })

        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        self.assertEqual(self.tasks.rule_snapshots.run_next()['status'], 'completed')
        snapshot = self.request('GET', base + '/risks/snapshot').json()
        self.assertEqual(snapshot['document_version'], 1)
        self.assertEqual(snapshot['risks'], [])
        model = self.tasks.model_jobs.run_once(task, 1)
        self.assertEqual(model, {'state': 'completed', 'code': 'MODEL_NOT_REQUIRED'})
        self.assertEqual(self.request('GET', base + '/model-result').json()['code'], 'MODEL_NOT_REQUIRED')
        document = self.assert_document(task, 'F4')
        self.tasks.previews.build(task, 1)
        mapping = self.request('GET', base + '/document/preview-map').json()
        self.assertEqual(mapping['document_version'], 1)
        self.assertTrue(all(paragraph['page'] == 1 and paragraph['locatable'] for paragraph in mapping['paragraphs']))
        self.assertTrue(self.request('GET', base + '/document/preview').content.startswith(b'%PDF-'))
        for suffix in ('/document', '/document/preview', '/document/preview-map', '/risks/snapshot', '/model-result'):
            for role, code in (('owner', 403), ('admin', 403), ('other', 404)):
                self.request('GET', base + suffix, role, code)
            self.assertEqual(self.http.get('/api/v1' + base + suffix).status_code, 401)

        self.confirm(task, snapshot)
        self.request('GET', base + '/review', 'other', 404)
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        report = self.request('GET', base + '/reports/markdown?review_version=1', 'owner').text
        self.assertIn('无保留风险；不代表合同不存在其他法律风险。', report)
        self.assertIn('集成确认结论', report)
        self.assertTrue(self.request('GET', base + '/reports/pdf?review_version=1', 'owner').content.startswith(b'%PDF'))

    def test_f5_empty_docx_live_proxy_block_replacement_and_permissions(self):
        task = self.upload('f5-empty.docx')
        base = f'/tasks/{task}'
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'blocked')
        blocked = self.request('GET', base, 'owner').json()
        self.assertEqual(blocked['document_version'], 1)
        self.assertEqual(blocked['machine_status'], 'blocked')
        self.assertEqual(blocked['blocked_code'], 'DOCX_EMPTY')
        self.assertTrue(blocked['blocked_reason'])
        self.assertEqual(blocked['recovery_action'], 'replace_attachment')
        self.assertIsNone(blocked['risk_level'])
        self.request('GET', base + '/document', code=409)
        self.request('GET', base + '/risks/snapshot', code=409)
        self.request('POST', base + '/confirm', code=409, json={
            'document_version': 1, 'review_version': 1, 'conclusion': 'cannot confirm empty document',
        })
        self.request('POST', base + '/retry', 'admin', 409, json={'document_version': 1})
        old_records = self.request('GET', base + '/processing-records?document_version=1', 'admin').json()
        self.assertEqual(old_records['total'], 1)
        self.assertEqual([(item['stage'], item['status'], item['code']) for item in old_records['items']],
                         [('parse', 'blocked', 'DOCX_EMPTY')])
        self.request('GET', base + '/processing-records', 'owner', 403)

        filename = integration.ORACLE['F4']['file']
        payload = (integration.SAMPLES / filename).read_bytes()
        def replacement(role, code, version):
            return self.request('POST', base + '/documents', role, code,
                data={'base_document_version': version}, files={'file': (filename, payload)})

        replacement('legal', 403, 1)
        replacement('admin', 403, 1)
        replacement('other', 404, 1)
        self.assertEqual(self.http.post('/api/v1' + base + '/documents',
            data={'base_document_version': 1}, files={'file': (filename, payload)}).status_code, 401)
        replacement('owner', 409, 2)
        revised = replacement('owner', 201, 1).json()
        self.assertEqual(revised['document_version'], 2)
        self.assertEqual(revised['machine_status'], 'pending')
        self.assertIsNone(revised['blocked_code'])
        replacement('owner', 409, 1)
        self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
        document = self.request('GET', base + '/document').json()
        self.assertEqual(document['document_version'], 2)
        self.assertTrue(document['normalized_text'])
        self.request('GET', base + '/document?document_version=1', code=409)
        self.request('GET', base + '/risks/snapshot', code=409)
        new_records = self.request('GET', base + '/processing-records?document_version=2', 'admin').json()
        self.assertEqual([(item['stage'], item['status']) for item in new_records['items']],
                         [('parse', 'completed')])
        self.assertEqual(self.request('GET', base + '/processing-records?document_version=1', 'admin').json(),
                         old_records)


if __name__ == '__main__':
    unittest.main()
