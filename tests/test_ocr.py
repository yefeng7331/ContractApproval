"""Real F3/F5 HTTP smoke plus isolated failure/version boundary checks."""

import io
from contextlib import ExitStack
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.auth import AuthStore
from backend.main import create_app
from backend.ocr import OcrError, parse_image, run_ocr_once
from backend.tasks import TaskStore
from backend.pdf_job import run_pdf_once

SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


class OcrTests(unittest.TestCase):
    def test_scanned_pdf_real_and_recovery(self):
        with ExitStack() as stack:
            root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            store, tasks, users = self.setup_store(root)
            stack.callback(store.close)
            def pdf_image(name):
                output = io.BytesIO()
                with Image.open(SAMPLES / name) as image:
                    image.convert('RGB').save(output, format='PDF', resolution=150)
                return output.getvalue()
            clear = pdf_image('f3-clear-scan.png')
            task_id = tasks.create_task(users['business'], 'scan.pdf', clear, 'test', 'test')['task_id']
            self.assertEqual(run_pdf_once(tasks.jobs)['status'], 'reviewing')
            document = tasks.get_parsed_document(task_id, users['legal'])
            self.assertEqual(document['extraction_method'], 'ocr')
            self.assertTrue(document['extraction_warning'])
            self.assertEqual(len(document['paragraphs']), 12)
            self.assertEqual(document['page_count'], 1)
            self.assertEqual(tasks.get_pdf_preview(task_id, users['legal']), clear)
            tasks.rule_snapshots.run_next()
            self.assertEqual(len(tasks.get_rule_snapshot(task_id, users['legal'])['risks']), 2)
            with TestClient(create_app(auth_store=store, upload_root=root / 'uploads')) as client:
                headers = {name: {'Authorization': 'Bearer ' + client.post('/api/v1/sessions',
                    json={'username': name, 'password': 'synthetic-password'}).json()['access_token']}
                    for name in ('owner', 'legal', 'admin', 'other')}
                base = f'/api/v1/tasks/{task_id}'
                for endpoint in ('/document', '/document/preview', '/risks/snapshot'):
                    self.assertEqual(client.get(base + endpoint, headers=headers['legal']).status_code, 200)
                    self.assertEqual(client.get(base + endpoint).status_code, 401)
                    for role, status in (('owner', 403), ('other', 404), ('admin', 403)):
                        self.assertEqual(client.get(base + endpoint, headers=headers[role]).status_code, status)
                self.assertEqual(client.get(base + '/document', headers=headers['legal']).json(), document)
            for p in document['paragraphs']:
                self.assertEqual(document['normalized_text'][p['start']:p['end']], p['quote'])
                self.assertEqual(p['page'], 1)
                self.assertTrue(p['locatable'])
            blurred = pdf_image('f5-blurred-scan.png')
            bad = tasks.create_task(users['business'], 'blur.pdf', blurred, 'test', 'test')['task_id']
            self.assertEqual(run_pdf_once(tasks.jobs)['code'], 'OCR_UNREADABLE')
            tasks.add_document_version(bad, users['business'], 1, 'clear.pdf', clear)
            with patch('backend.ocr.recognize', side_effect=OcrError('OCR_TIMEOUT', 'timeout', 'admin_retry')):
                self.assertEqual(run_pdf_once(tasks.jobs)['code'], 'OCR_TIMEOUT')
            self.assertEqual(tasks.jobs.retry_ocr(bad, 2, users['admin'])['attempt'], 2)
            page = {'width': 2048, 'height': 2800, 'texts': ['clear'], 'scores': [.99], 'boxes': [[1, 1, 100, 50]]}
            with patch('backend.ocr.recognize', return_value=[page]):
                self.assertEqual(run_pdf_once(tasks.jobs)['status'], 'reviewing')
            self.assertEqual(tasks.get_parsed_document(bad, users['legal'])['document_version'], 2)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_budget_entries').fetchone()[0], 0)

    def test_mixed_pdf_all_pages_and_encryption(self):
        import pypdfium2 as pdfium
        from backend.ocr import parse_scanned_pdf
        from backend.pdf_parser import parse_pdf, PdfParseError

        scan = io.BytesIO()
        Image.new('RGB', (600, 800), 'white').save(scan, format='PDF', resolution=150)
        with pdfium.PdfDocument((SAMPLES / 'f2-text-software-purchase.pdf').read_bytes()) as text_pdf:
            with pdfium.PdfDocument(scan.getvalue()) as image_pdf:
                with pdfium.PdfDocument.new() as mixed:
                    mixed.import_pages(text_pdf, [0])
                    mixed.import_pages(image_pdf)
                    output = io.BytesIO()
                    mixed.save(output)
        content = output.getvalue()
        with self.assertRaises(PdfParseError) as caught:
            parse_pdf(content, 1)
        self.assertEqual(caught.exception.code, 'PDF_OCR_REQUIRED')
        def fake_recognize(content):
            from backend.ocr import image_pages
            return [{'width': im.width, 'height': im.height, 'texts': ['page'], 'scores': [.99],
                'boxes': [[1, 1, 100, 50]]} for im in image_pages(content)]
        with patch('backend.ocr.recognize', side_effect=fake_recognize):
            parsed = parse_scanned_pdf(content, 3)
        self.assertEqual([p.page for p in parsed.paragraphs], [1, 2])
        self.assertEqual(parsed.normalized_text, 'page\npage')
        with ExitStack() as stack:
            root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            store, tasks, users = self.setup_store(root)
            stack.callback(store.close)
            tasks.create_task(users['business'], 'locked.pdf', (SAMPLES / 'f5-encrypted.pdf').read_bytes(), 'test', 'test')
            with patch('backend.pdf_job.parse_scanned_pdf') as ocr:
                self.assertEqual(run_pdf_once(tasks.jobs)['code'], 'PDF_ENCRYPTED')
                ocr.assert_not_called()

    def test_text_page_with_image_requests_ocr(self):
        import pypdfium2 as pdfium
        from backend.pdf_parser import parse_pdf, PdfParseError

        with pdfium.PdfDocument((SAMPLES / 'f2-text-software-purchase.pdf').read_bytes()) as pdf:
            page = pdf[0]
            bitmap = pdfium.PdfBitmap.from_pil(Image.new('RGB', (30, 30), 'white'))
            try:
                obj = pdfium.PdfImage.new(pdf)
                obj.set_bitmap(bitmap)
                obj.set_matrix(pdfium.PdfMatrix(30, 0, 0, 30, 0, 0))
                page.insert_obj(obj)
                page.gen_content()
                output = io.BytesIO()
                pdf.save(output)
            finally:
                page.close()
                bitmap.close()
        self.assertEqual(parse_pdf(output.getvalue(), 1).page_count, 3)
        with self.assertRaises(PdfParseError) as raised:
            parse_pdf(output.getvalue(), 1, detect_images=True)
        self.assertEqual(raised.exception.code, 'PDF_OCR_REQUIRED')

    def setup_store(self, root):
        store = AuthStore(root / 'test.sqlite3')
        store.initialize()
        self.addCleanup(store.close)
        users = {role: store.create_user(name, role, 'synthetic-password')
            for name, role in (('owner', 'business'), ('legal', 'legal'), ('admin', 'admin'))}
        store.create_user('other', 'business', 'synthetic-password')
        tasks = TaskStore(store, root / 'uploads')
        tasks.initialize()
        return store, tasks, users

    def test_real_images_http_smoke(self):
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            root = Path(directory)
            store, tasks, users = self.setup_store(root)
            stack.callback(store.close)
            app = create_app(auth_store=store, upload_root=root / 'uploads',
                auto_process_ocr=True, auto_process_rules=True, auto_process_models=True,
                auto_process_previews=True)
            with TestClient(app) as client:
                headers = {name: {'Authorization': 'Bearer ' + client.post('/api/v1/sessions',
                    json={'username': name, 'password': 'synthetic-password'}).json()['access_token']}
                    for name in ('owner', 'other', 'legal', 'admin')}

                def upload(filename):
                    response = client.post('/api/v1/tasks', headers=headers['owner'],
                        data={'department': 'synthetic', 'applicant': 'synthetic'},
                        files={'file': (filename, (SAMPLES / filename).read_bytes())})
                    self.assertEqual(response.status_code, 201, response.text)
                    return response.json()['task_id']

                def wait(task_id, status):
                    deadline = time.monotonic() + 100
                    while time.monotonic() < deadline:
                        state = client.get(f'/api/v1/tasks/{task_id}', headers=headers['owner']).json()
                        if state['machine_status'] == status:
                            if status == 'blocked' or client.get(f'/api/v1/tasks/{task_id}/document/preview', headers=headers['legal']).status_code == 200:
                                return state
                        time.sleep(.1)
                    self.fail(f'OCR did not reach {status}: {state}')

                task_id = upload('f3-clear-scan.png')
                wait(task_id, 'reviewing')
                base = f'/api/v1/tasks/{task_id}'
                document = client.get(base + '/document', headers=headers['legal']).json()
                self.assertEqual(document['page_count'], 1)
                self.assertEqual(len(document['paragraphs']), 12)
                self.assertTrue(document['preview_available'])
                for paragraph in document['paragraphs']:
                    self.assertEqual(document['normalized_text'][paragraph['start']:paragraph['end']], paragraph['quote'])
                    self.assertEqual(paragraph['document_version'], 1)
                    self.assertEqual(paragraph['page'], 1)
                    self.assertTrue(paragraph['locatable'])
                fields = {field['name']: field for field in document['fields']}
                self.assertEqual(fields['contract_number']['value'], 'SYN-2026-001')
                self.assertFalse(fields['amount']['anchor']['locatable'])
                self.assertEqual(fields['amount']['anchor']['reason'], 'OCR_FIELD_REGION_UNVERIFIED')
                snapshot = client.get(base + '/risks/snapshot', headers=headers['legal'])
                self.assertEqual(snapshot.status_code, 200, snapshot.text)
                self.assertEqual(len(snapshot.json()['risks']), 2)
                for risk in snapshot.json()['risks']:
                    self.assertTrue(all(anchor['locatable'] for anchor in risk['anchors']))
                pdf = client.get(base + '/document/preview', headers=headers['legal']).content
                self.assertTrue(pdf.startswith(b'%PDF-'))
                mapping = client.get(base + '/document/preview-map', headers=headers['legal']).json()
                self.assertEqual(mapping['mapping_scope'], 'ocr_line_regions')
                self.assertEqual(mapping['paragraphs'], document['paragraphs'])
                for endpoint in ('/document', '/document/preview', '/document/preview-map', '/risks/snapshot'):
                    self.assertEqual(client.get(base + endpoint).status_code, 401)
                    for name, status in (('owner', 403), ('other', 404), ('admin', 403)):
                        self.assertEqual(client.get(base + endpoint, headers=headers[name]).status_code, status)
                self.assertEqual(client.get(base + '/document?document_version=2', headers=headers['legal']).status_code, 404)

                blurred = upload('f5-blurred-scan.png')
                state = wait(blurred, 'blocked')
                self.assertEqual(state['blocked_code'], 'OCR_UNREADABLE')
                self.assertEqual(state['recovery_action'], 'replace_attachment')
                self.assertEqual(client.get(f'/api/v1/tasks/{blurred}/document', headers=headers['legal']).status_code, 409)
                self.assertEqual(client.post(f'/api/v1/tasks/{blurred}/retry', headers=headers['admin'], json={'document_version': 1}).status_code, 409)
                revised = client.post(f'/api/v1/tasks/{blurred}/documents', headers=headers['owner'],
                    data={'base_document_version': 1}, files={'file': ('clear.png', (SAMPLES / 'f3-clear-scan.png').read_bytes())})
                self.assertEqual(revised.status_code, 201, revised.text)
                wait(blurred, 'reviewing')
                self.assertEqual(client.get(f'/api/v1/tasks/{blurred}/document', headers=headers['legal']).json()['document_version'], 2)
                self.assertEqual(client.get(f'/api/v1/tasks/{blurred}/document?document_version=1', headers=headers['legal']).status_code, 409)
                # No OCR path may reserve or send a paid model request.
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_jobs WHERE state='running'").fetchone()[0], 0)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_budget_entries').fetchone()[0], 0)
            with TestClient(create_app(auth_store=store, upload_root=root / 'uploads')) as client:
                self.assertEqual(client.get(base + '/document', headers=headers['legal']).json(), document)
                self.assertEqual(client.get(base + '/document/preview', headers=headers['legal']).content, pdf)
                row = store.connection.execute('SELECT preview_path FROM docx_previews WHERE task_id=?', (task_id,)).fetchone()
                Path(row[0]).write_bytes(b'%PDF-tampered')
                self.assertEqual(client.get(base + '/document/preview', headers=headers['legal']).status_code, 409)
            store.close()

    def test_failure_retry_and_stale_version(self):
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            store, tasks, users = self.setup_store(Path(directory))
            stack.callback(store.close)
            content = (SAMPLES / 'f3-clear-scan.png').read_bytes()
            task_id = tasks.create_task(users['business'], 'scan.png', content, 'test', 'test')['task_id']
            with patch('backend.ocr.recognize', side_effect=OcrError('OCR_TIMEOUT', 'timeout', 'admin_retry')):
                self.assertEqual(run_ocr_once(tasks.jobs)['code'], 'OCR_TIMEOUT')
            self.assertEqual(run_ocr_once(tasks.jobs)['status'], 'no_pending_image')
            self.assertEqual(store.connection.execute('SELECT error_code FROM processing_attempts').fetchone()[0], 'OCR_TIMEOUT')
            for role in ('business', 'legal'):
                with self.assertRaises(Exception) as raised:
                    tasks.jobs.retry_ocr(task_id, 1, users[role])
                self.assertEqual(raised.exception.code, 'FORBIDDEN')
            self.assertEqual(tasks.jobs.retry_ocr(task_id, 1, users['admin'])['attempt'], 2)
            lease = tasks.jobs.claim_next(file_format='png')
            self.assertEqual(lease.attempt, 2)
            tasks.jobs.block_parse(lease, 'OCR_UNREADABLE', 'unreadable')
            tasks.add_document_version(task_id, users['business'], 1, 'new.png', content)
            self.assertFalse(tasks.jobs.block_parse(lease, 'OLD', 'old'))
            with patch('backend.ocr.recognize', return_value=[{'width': 2048, 'height': 2800,
                    'texts': [], 'boxes': [], 'scores': []}]):
                self.assertEqual(run_ocr_once(tasks.jobs)['code'], 'OCR_UNREADABLE')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM parsed_documents').fetchone()[0], 0)
            store.close()

    def test_low_confidence_blocks_without_partial_drafts(self):
        with ExitStack() as stack:
            root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            store, tasks, users = self.setup_store(root)
            stack.callback(store.close)
            content = (SAMPLES / 'f3-clear-scan.png').read_bytes()
            task_id = tasks.create_task(users['business'], 'scan.png', content, 'test', 'test')['task_id']
            page = {'width': 2048, 'height': 2800, 'texts': ['clear line', 'uncertain line'],
                'boxes': [[1, 2, 100, 50], [1, 60, 100, 100]], 'scores': [.99, .8999]}
            with patch('backend.ocr.recognize', return_value=[page]):
                self.assertEqual(run_ocr_once(tasks.jobs)['code'], 'OCR_LOW_CONFIDENCE')
            row = store.connection.execute('SELECT machine_status,recovery_action FROM tasks WHERE id=?', (task_id,)).fetchone()
            self.assertEqual(tuple(row), ('blocked', 'replace_attachment'))
            for table in ('parsed_documents', 'rule_draft_snapshots', 'model_budget_entries'):
                self.assertEqual(store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            with self.assertRaises(Exception) as raised:
                tasks.jobs.retry_ocr(task_id, 1, users['admin'])
            self.assertEqual(raised.exception.status_code, 409)
            tasks.add_document_version(task_id, users['business'], 1, 'clear.png', content)
            page['scores'] = [.99, .9]
            with patch('backend.ocr.recognize', return_value=[page]):
                self.assertEqual(run_ocr_once(tasks.jobs)['status'], 'reviewing')
            versions = store.connection.execute('SELECT document_version FROM parsed_documents').fetchall()
            self.assertEqual([row[0] for row in versions], [2])

    def test_invalid_results_and_multipage(self):
        content = (SAMPLES / 'f3-clear-scan.png').read_bytes()
        base = {'width': 2048, 'height': 2800, 'texts': ['sample'], 'boxes': [[1, 2, 100, 50]], 'scores': [.99]}
        for data, code in (({**base, 'boxes': [[-1, 0, 10, 10]]}, 'OCR_RESULT_INVALID'),
                ({**base, 'scores': [float('nan')]}, 'OCR_RESULT_INVALID'),
                ({**base, 'scores': [.5]}, 'OCR_LOW_CONFIDENCE')):
            with patch('backend.ocr.recognize', return_value=[data]):
                with self.assertRaises(OcrError) as raised:
                    parse_image(content, 1)
                self.assertEqual(raised.exception.code, code)
        output = io.BytesIO()
        image = Image.new('RGB', (2048, 2800), 'white')
        image.save(output, format='TIFF', save_all=True, append_images=[image], compression='tiff_lzw')
        with patch('backend.ocr.recognize', return_value=[base, base]):
            parsed = parse_image(output.getvalue(), 2)
            self.assertEqual([p.page for p in parsed.paragraphs], [1, 2])
            self.assertEqual(parsed.normalized_text, 'sample\nsample')


if __name__ == '__main__':
    unittest.main()
