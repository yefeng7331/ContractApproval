"""Standalone live HTTP smoke for the opt-in, no-paid-call local processing mode."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn

from backend.auth import AuthStore
from backend.local_runtime import create_local_app
from backend.mock_pending import MOCK_PENDING_ID


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'samples'


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class LocalProcessingLauncherTests(unittest.TestCase):
    def wait_for(self, check, timeout=45):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            self.assertIsNone(self.vite.poll(), 'Vite exited unexpectedly')
            self.assertTrue(self.server_thread.is_alive(), 'Local API exited unexpectedly')
            try:
                last = check()
                if last:
                    return last
            except httpx.TransportError:
                pass
            time.sleep(0.25)
        self.fail(f'Local processing timed out; last result: {last!r}')

    def request(self, method, path, role='legal', code=200, **kwargs):
        response = self.http.request(method, '/api/v1' + path, headers=self.headers[role], **kwargs)
        self.assertEqual(response.status_code, code, response.text[:300])
        return response

    def test_f4_live_processing_through_local_runtime_without_paid_model(self):
        with tempfile.TemporaryDirectory(prefix='contract-local-processing-') as temp:
            data = Path(temp)
            store = AuthStore(data / 'contract_approval.sqlite3')
            store.initialize()
            try:
                for username, role in [('owner', 'business'), ('legal', 'legal'),
                                       ('admin', 'admin'), ('other', 'business')]:
                    store.create_user(username, role, 'synthetic-password')
            finally:
                store.close()
            api_port = free_port()
            front_port = free_port()
            while front_port == api_port:
                front_port = free_port()
            with patch.dict(os.environ, {'CONTRACT_LOCAL_DATA_ROOT': str(data),
                                         'CONTRACT_LOCAL_PROCESSING': '1'}):
                app = create_local_app()
            self.server = uvicorn.Server(uvicorn.Config(
                app, host='127.0.0.1', port=api_port, log_level='error', access_log=False))
            self.server_thread = threading.Thread(target=self.server.run, daemon=True)
            self.server_thread.start()
            vite = ROOT / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'
            self.vite = subprocess.Popen([
                'node', str(vite), '--host', '127.0.0.1', '--port', str(front_port), '--strictPort',
            ], cwd=ROOT / 'frontend',
                env={**os.environ, 'CONTRACT_API_PROXY_TARGET': f'http://127.0.0.1:{api_port}'},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{front_port}', timeout=15) as self.http:
                    self.wait_for(lambda: self.http.get('/').status_code == 200
                                  and self.http.get('/api/v1/tasks').status_code == 401, timeout=25)
                    self.headers = {}
                    for username in ('owner', 'legal', 'admin', 'other'):
                        login = self.http.post('/api/v1/sessions', json={
                            'username': username, 'password': 'synthetic-password'})
                        self.assertEqual(login.status_code, 200, login.text[:300])
                        self.headers[username] = {'Authorization': 'Bearer ' + login.json()['access_token']}

                    task = self.request('POST', '/tasks', 'owner', 201,
                        data={'department': '采购部', 'applicant': '合成用户'},
                        files={'file': ('f4-revised-software-purchase.docx',
                                        (SAMPLES / 'f4-revised-software-purchase.docx').read_bytes())}).json()['task_id']
                    base = f'/tasks/{task}'
                    self.request('GET', base, 'other', 404)
                    self.request('GET', base + '/document', 'owner', 403)
                    self.request('POST', base + '/confirm', code=409, json={
                        'document_version': 1, 'review_version': 1, 'conclusion': '过早确认'})
                    self.wait_for(lambda: self.request('GET', base).json()['machine_status'] == 'completed')
                    self.assertEqual(self.request('GET', base + '/risks/snapshot').json()['risks'], [])
                    self.assertEqual(self.request('GET', base + '/model-result').json()['code'], 'MODEL_NOT_REQUIRED')
                    self.request('PUT', base + '/review', json={
                        'document_version': 1, 'base_review_version': None,
                        'risks': [], 'annotation': '合成无命中复核'})
                    self.request('POST', base + '/confirm', json={
                        'document_version': 1, 'review_version': 1,
                        'conclusion': '已人工核对演示规则，仍需正式法务判断'})
                    self.wait_for(lambda: len(reports := self.request(
                        'GET', base + '/reports/status?review_version=1').json()['reports']) == 2
                        and all(item['state'] == 'ready' for item in reports))
                    self.assertIn('不代表合同不存在其他法律风险',
                                  self.request('GET', base + '/reports/markdown?review_version=1', 'owner').text)
                    self.assertTrue(self.request('GET', base + '/reports/pdf?review_version=1', 'owner').content.startswith(b'%PDF'))
                    payload = {'review_version': 1, 'mock_approval_id': MOCK_PENDING_ID}
                    self.request('POST', base + '/mock-writeback', 'owner', 403, json=payload)
                    self.request('POST', base + '/mock-writeback', json=payload)
                    success = self.wait_for(lambda: (value if value['state'] == 'success' else None)
                                            if (value := self.request('GET', base + '/mock-writeback?review_version=1').json())
                                            else None)
                    self.assertEqual(self.request('POST', base + '/mock-writeback', json=payload).json()['comment_id'],
                                     success['comment_id'])
                    self.assertEqual(len(success['attempts']), 1)
                    self.assertNotIn('markdown', self.request('GET', base + '/mock-writeback?review_version=1',
                                                             'admin').json())

                    paid_task = self.request('POST', '/tasks', 'owner', 201,
                        data={'department': '采购部', 'applicant': '合成用户'},
                        files={'file': ('f1-software-purchase.docx',
                                        (SAMPLES / 'f1-software-purchase.docx').read_bytes())}).json()['task_id']
                    paid_base = f'/tasks/{paid_task}'
                    def risks_ready():
                        result = self.http.get('/api/v1' + paid_base + '/risks/snapshot',
                                               headers=self.headers['legal'])
                        return result.status_code == 200 and len(result.json()['risks']) == 2

                    self.wait_for(risks_ready)
                    self.assertEqual(self.request('GET', paid_base).json()['machine_status'], 'reviewing')
                    self.request('GET', paid_base + '/model-result', code=409)
                    self.request('POST', paid_base + '/confirm', code=409, json={
                        'document_version': 1, 'review_version': 1, 'conclusion': '不可跳过模型授权'})
            finally:
                if self.vite.poll() is None:
                    self.vite.terminate()
                    try:
                        self.vite.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        self.vite.kill()
                        self.vite.wait(timeout=8)
                self.server.should_exit = True
                self.server_thread.join(timeout=8)
                self.assertFalse(self.server_thread.is_alive(), 'Local API did not shut down')


if __name__ == '__main__':
    unittest.main()
