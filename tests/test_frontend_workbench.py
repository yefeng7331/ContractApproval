"""Real F1/F2 API -> frontend geometry -> PDF.js smoke, without model calls."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient
from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.main import create_app
from backend.pdf_job import run_pdf_once
from backend.tasks import TaskStore

ROOT = Path(__file__).resolve().parents[1]


class FrontendWorkbenchSmokeTests(unittest.TestCase):
    def test_real_api_geometry_and_pdfjs_rendering(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Install the approved frontend dependencies first')
        subprocess.run([node, 'frontend/scripts/prepare-pdfjs.mjs'], cwd=ROOT, check=True)
        with tempfile.TemporaryDirectory(prefix='contract-fe4-') as directory:
            root = Path(directory)
            store = AuthStore(root / 'test.sqlite3')
            try:
                store.initialize()
                users = {role: store.create_user(role, role, 'synthetic-password') for role in ('business', 'legal', 'admin')}
                tasks = TaskStore(store, root / 'uploads')
                tasks.initialize()
                with TestClient(create_app(auth_store=store, upload_root=root / 'uploads')) as client:
                    headers = {role: {'Authorization': 'Bearer ' + client.post('/api/v1/sessions', json={'username': role, 'password': 'synthetic-password'}).json()['access_token']} for role in users}
                    for name, worker in (('f1-software-purchase.docx', run_docx_once), ('f2-text-software-purchase.pdf', run_pdf_once)):
                        task = tasks.create_task(users['business'], name, (ROOT / 'samples' / name).read_bytes(), 'test', 'test')['task_id']
                        base = f'/api/v1/tasks/{task}'
                        self.assertEqual(client.get(base + '/document', headers=headers['legal']).status_code, 409)
                        self.assertEqual(worker(tasks.jobs)['status'], 'reviewing')
                        tasks.rule_snapshots.persist(task, 1)
                        if name.endswith('.docx'):
                            built = tasks.previews.build(task, 1)
                            self.assertEqual(built['state'], 'ready', built)

                        def read(suffix):
                            url = base + suffix + '?document_version=1'
                            self.assertEqual(client.get(url).status_code, 401)
                            for role in ('business', 'admin'):
                                self.assertEqual(client.get(url, headers=headers[role]).status_code, 403)
                            response = client.get(url, headers=headers['legal'])
                            self.assertEqual(response.status_code, 200, response.text[:100] if suffix != '/document/preview' else 'PDF unavailable')
                            self.assertEqual(client.get(base + suffix + '?document_version=99', headers=headers['legal']).status_code, 404)
                            return response

                        fixture = {'name': name, 'document': read('/document').json(), 'snapshot': read('/risks/snapshot').json(), 'mapping': read('/document/preview-map').json() if name.endswith('.docx') else None}
                        self.assertEqual(client.get(base + '/model-result?document_version=1', headers=headers['legal']).status_code, 409)
                        fixture_path, pdf_path = root / 'fixture.json', root / 'preview.pdf'
                        fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
                        pdf_path.write_bytes(read('/document/preview').content)
                        subprocess.run([node, '--experimental-strip-types', 'frontend/scripts/check-workbench.mjs', str(fixture_path), str(pdf_path)], cwd=ROOT, check=True, timeout=60)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
