"""Real API contract used by the first frontend unit; isolated data, no workers/model calls."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.main import create_app


class FrontendDashboardTests(unittest.TestCase):
    def test_login_visibility_paging_and_logout_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(':memory:')
            store.initialize()
            password = 'frontend-smoke-password'
            for name, role in [('owner', 'business'), ('other', 'business'),
                               ('legal', 'legal'), ('admin', 'admin')]:
                store.create_user(name, role, password)
            try:
                with TestClient(create_app(auth_store=store, upload_root=Path(directory))) as client:
                    self.assertEqual(client.get('/api/v1/tasks').status_code, 401)
                    self.assertEqual(client.post('/api/v1/sessions', json={
                        'username': 'owner', 'password': 'wrong'}).status_code, 401)
                    headers = {}
                    for name in ['owner', 'other', 'legal', 'admin']:
                        response = client.post('/api/v1/sessions', json={
                            'username': name, 'password': password})
                        self.assertEqual(response.status_code, 200)
                        data = response.json()
                        self.assertIn('expires_at', data)
                        self.assertEqual(data['user']['username'], name)
                        headers[name] = {'Authorization': 'Bearer ' + data['access_token']}
                    for _ in range(2):
                        response = client.post('/api/v1/mock-pending/demo-f1-001/import', headers=headers['owner'])
                        self.assertEqual(response.status_code, 201, response.text)
                    pages = [client.get(f'/api/v1/tasks?limit=1&offset={offset}', headers=headers['owner']).json()
                             for offset in range(2)]
                    self.assertEqual(pages[0]['total'], 2)
                    self.assertNotEqual(pages[0]['items'][0]['task_id'], pages[1]['items'][0]['task_id'])
                    item = pages[0]['items'][0]
                    for field in ['document_version', 'review_version', 'machine_status', 'legal_status',
                                  'writeback_status', 'submission', 'recovery_action', 'latest_confirmed_version']:
                        self.assertIn(field, item)
                    self.assertIsNone(item['risk_level'])
                    self.assertEqual(client.get('/api/v1/tasks', headers=headers['other']).json()['total'], 0)
                    self.assertEqual(client.get('/api/v1/tasks', headers=headers['legal']).json()['total'], 2)
                    admin = client.get('/api/v1/tasks', headers=headers['admin']).json()['items'][0]
                    for field in ['submission', 'risk_level', 'latest_confirmed_version']:
                        self.assertNotIn(field, admin)
                    self.assertEqual(client.delete('/api/v1/sessions/current', headers=headers['owner']).status_code, 204)
                    self.assertEqual(client.get('/api/v1/tasks', headers=headers['owner']).status_code, 401)
            finally:
                store.close()
