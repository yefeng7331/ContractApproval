"""HTTP integration with real local parsers/converters and a controlled model response.

F6 pending-attachment timeout and recovery are covered by test_pending_imports.
"""

import io
import json
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

import pdfplumber

from backend.docx_job import run_docx_once
from backend.pdf_job import run_pdf_once
from backend.ocr import run_ocr_once
from backend.mock_pending import MOCK_PENDING_ID
from tests.test_reviews import ReviewTests as Fixture


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
ORACLE = json.loads((SAMPLES/'f1_f4_expected.json').read_text(encoding='utf-8'))['samples']


def normalized(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


class BackendIntegrationTests(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def request(self, method, path, role='legal', code=200, **kwargs):
        result = self.client.request(method, '/api/v1'+path, headers=self.headers[role], **kwargs)
        self.assertEqual(result.status_code, code, result.text[:300] if result.status_code != code else '')
        return result

    def upload(self, filename):
        return self.request('POST', '/tasks', 'owner', 201,
            data={'department': '采购部', 'applicant': '张三'},
            files={'file': (filename, (SAMPLES/filename).read_bytes())}).json()['task_id']

    def machine(self, task, runner):
        self.assertEqual(runner(self.tasks.jobs)['status'], 'reviewing')
        self.tasks.rule_snapshots.run_next()
        snapshot = self.request('GET', f'/tasks/{task}/risks/snapshot').json()
        response = {key: snapshot[key] for key in ('document_version', 'evidence_sha256', 'rule_version')}
        response['suggestions'] = [{'rule_id': risk['rule_id'], 'suggestion': '合成集成建议，须法务核定'}
                                   for risk in snapshot['risks']]
        output = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(response)}}]}
        with patch('backend.model_jobs._post_json', side_effect=AssertionError('No network')):
            self.assertEqual(self.tasks.model_jobs.run_once(task, 1, send=lambda _: output,
                             authorization_key='integration-'+task)['state'], 'completed')
        return snapshot

    def assert_document(self, task, fixture, scan=False):
        document = self.request('GET', f'/tasks/{task}/document').json()
        expected = ORACLE[fixture]
        self.assertEqual(len(document['paragraphs']), len(expected['paragraphs']))
        for actual, oracle in zip(document['paragraphs'], expected['paragraphs'], strict=True):
            self.assertEqual(normalized(actual['quote']), normalized(oracle[3]))
            self.assertEqual(document['normalized_text'][actual['start']:actual['end']], actual['quote'])
        fields = {field['name']: field for field in document['fields']}
        for name, oracle in expected['fields'].items():
            self.assertEqual(normalized(fields[name]['value'] or ''), normalized(oracle[0] if oracle else ''))
        for clause, oracle in zip(document['clauses'], expected['clauses'], strict=True):
            self.assertEqual(normalized(clause['quote']), normalized(oracle[4]))
        self.assertEqual(document['missing_clause_types'], expected['missing_clause_types'])
        if scan:
            self.assertEqual(document['extraction_method'], 'ocr')
        return document

    def confirm(self, task, snapshot):
        base = f'/tasks/{task}'
        for suffix in ('/document', '/risks/snapshot', '/model-result'):
            for role, code in [('owner', 403), ('admin', 403), ('other', 404)]:
                self.request('GET', base+suffix, role, code)
        payload = {'document_version': 1, 'base_review_version': None,
                   'annotation': '集成复核批注', 'risks': [
                       {'rule_id': r['rule_id'], 'retained': True, 'risk_level': 'high',
                        'suggestion_source': 'manual', 'final_suggestion': '法务集成最终建议'}
                       for r in snapshot['risks']]}
        self.request('PUT', base+'/review', json=payload)
        self.request('POST', base+'/mock-writeback', code=409,
                     json={'review_version': 1, 'mock_approval_id': MOCK_PENDING_ID})
        confirmation = {'document_version': 1, 'review_version': 1, 'conclusion': '集成确认结论'}
        self.request('POST', base+'/confirm', 'admin', 403, json=confirmation)
        self.request('POST', base+'/confirm', json=confirmation)
        self.assertEqual(self.request('GET', base+'/review', 'owner').json()['conclusion'], '集成确认结论')

    def test_f1_full_http_chain_and_import(self):
        task = self.upload(ORACLE['F1']['file'])
        base = f'/tasks/{task}'
        snapshot = self.machine(task, run_docx_once)
        self.assert_document(task, 'F1')
        self.assertEqual({r['rule_id'] for r in snapshot['risks']}, {'DEMO-IP-01', 'DEMO-PAY-01'})
        self.assertTrue(all(r['risk_level'] == 'high' for r in snapshot['risks']))
        self.tasks.previews.build(task, 1)
        mapping = self.request('GET', base+'/document/preview-map').json()
        self.assertEqual(mapping['document_version'], 1)
        self.assertTrue(all(p['page'] == 1 and p['locatable'] for p in mapping['paragraphs']))
        self.assertTrue(self.request('GET', base+'/document/preview').content.startswith(b'%PDF'))
        self.confirm(task, snapshot)
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        self.assertEqual(self.tasks.reports.run_next(), 'ready')
        md = self.request('GET', base+'/reports/markdown?review_version=1', 'owner').text
        pdf = self.request('GET', base+'/reports/pdf?review_version=1', 'owner').content
        with pdfplumber.open(io.BytesIO(pdf)) as report:
            text = '\n'.join(page.extract_text() or '' for page in report.pages)
        for expected in ('集成确认结论', '集成复核批注', '法务集成最终建议', '审查版本：1'):
            self.assertIn(expected, md)
            self.assertIn(expected, text)
        payload = {'review_version': 1, 'mock_approval_id': MOCK_PENDING_ID}
        self.assertEqual(self.request('POST', base+'/mock-writeback', json=payload).json()['state'], 'writing')
        self.assertEqual(self.tasks.writebacks.run_next(), 'success')
        first = self.request('GET', base+'/mock-writeback?review_version=1', 'owner').json()
        self.assertEqual(self.request('POST', base+'/mock-writeback', json=payload).json()['comment_id'], first['comment_id'])
        self.assertIn('法务集成最终建议', first['markdown'])
        current = self.request('GET', base, 'owner').json()
        self.assertEqual([current[k] for k in ('machine_status', 'legal_status', 'writeback_status')],
                         ['completed', 'confirmed', 'success'])
        imported = self.request('POST', '/mock-pending/'+MOCK_PENDING_ID+'/import', 'owner', 201).json()
        self.assertEqual(imported['mock_approval_id'], MOCK_PENDING_ID)
        imported_snapshot = self.machine(imported['task_id'], run_docx_once)
        self.assert_document(imported['task_id'], 'F1')
        self.assertEqual(len(imported_snapshot['risks']), 2)

    def test_f1_operation_record_smoke(self):
        task = self.upload(ORACLE['F1']['file'])
        snapshot = self.machine(task, run_docx_once)
        base = f'/tasks/{task}'
        self.confirm(task, snapshot)
        payload = {'review_version': 1, 'mock_approval_id': MOCK_PENDING_ID}
        self.request('POST', base+'/mock-writeback', json=payload)
        self.assertEqual(self.tasks.writebacks.run_next(), 'success')
        self.request('POST', base+'/mock-writeback', json=payload)
        self.request('POST', base+'/confirm', code=409,
                     json={'document_version': 1, 'review_version': 1, 'conclusion': 'different'})
        events = self.auth.connection.execute('''
            SELECT action,actor_user_id,document_version,created_at
            FROM audit_events WHERE task_id=? ORDER BY id''', (task,)).fetchall()
        self.assertEqual([event['action'] for event in events], [
            'task_created', 'review_saved', 'review_confirmed',
            'mock_writeback_requested', 'mock_writeback_succeeded'])
        self.assertTrue(all(event['document_version'] == 1 and event['created_at'] for event in events))
        self.assertEqual(events[0]['actor_user_id'], self.users['owner'].id)
        self.assertTrue(all(event['actor_user_id'] == self.users['legal'].id for event in events[1:]))
        visible = self.request('GET', base+'/audit-events', 'admin').json()
        self.assertEqual(visible['total'], len(events))
        self.assertEqual([item['action'] for item in visible['items']],
                         [event['action'] for event in events])
        self.assertEqual([item['actor_role'] for item in visible['items']],
                         ['business', 'legal', 'legal', 'legal', 'legal'])
        self.assertEqual([item['action'] for item in self.request(
            'GET', base+'/audit-events?document_version=1&limit=2&offset=2', 'admin'
        ).json()['items']], ['review_confirmed', 'mock_writeback_requested'])
        self.assertEqual(self.request('GET', base+'/audit-events?document_version=2', 'admin').json()['total'], 0)
        for role in ('owner', 'legal', 'other'):
            self.request('GET', base+'/audit-events', role, 403)
        self.request('GET', '/tasks/missing/audit-events', 'admin', 404)
        self.request('GET', base+'/audit-events?limit=101', 'admin', 422)
        self.assertEqual(self.client.get('/api/v1'+base+'/audit-events').status_code, 401)

    def test_f2_f3_f4_same_rules_real_parsers_and_legal_versions(self):
        for fixture, filename, runner in [('F1', 'f2-text-software-purchase.pdf', run_pdf_once),
                                          ('F1', 'f3-clear-scan.png', run_ocr_once),
                                          ('F4', ORACLE['F4']['file'], run_docx_once)]:
            with self.subTest(filename=filename):
                task = self.upload(filename)
                snapshot = self.machine(task, runner)
                document = self.assert_document(task, fixture, scan=filename.endswith('.png'))
                self.assertEqual(len(snapshot['risks']), 0 if fixture == 'F4' else 2)
                if fixture == 'F1':
                    self.assertEqual({r['rule_id'] for r in snapshot['risks']}, {'DEMO-IP-01', 'DEMO-PAY-01'})
                    for risk in snapshot['risks']:
                        self.assertEqual(risk['risk_level'], 'high')
                        for anchor in risk['anchors']:
                            self.assertEqual(anchor['document_version'], 1)
                            self.assertEqual(document['normalized_text'][anchor['start']:anchor['end']], anchor['quote'])
                            expected_page = (2 if anchor['paragraph_index'] in (6, 7) else 3) if filename.endswith('.pdf') else 1
                            self.assertEqual(anchor['page'], expected_page)
                self.confirm(task, snapshot)

    def test_f5_blocked_no_conclusion_and_replacement(self):
        for filename, runner, code in [('f5-empty.docx', run_docx_once, 'DOCX_EMPTY'),
                                       ('f5-encrypted.pdf', run_pdf_once, 'PDF_ENCRYPTED'),
                                       ('f5-blurred-scan.png', run_ocr_once, 'OCR_UNREADABLE')]:
            with self.subTest(filename=filename):
                task = self.upload(filename)
                result = runner(self.tasks.jobs)
                self.assertEqual(result['status'], 'blocked')
                current = self.request('GET', f'/tasks/{task}', 'owner').json()
                self.assertEqual(current['blocked_code'], code)
                self.assertEqual(current['recovery_action'], 'replace_attachment')
                self.assertIsNone(current['risk_level'])
                self.request('POST', f'/tasks/{task}/confirm', code=409,
                             json={'document_version': 1, 'review_version': 1, 'conclusion': 'must fail'})
                revised = self.request('POST', f'/tasks/{task}/documents', 'owner', 201,
                    data={'base_document_version': 1}, files={'file': (ORACLE['F4']['file'], (SAMPLES/ORACLE['F4']['file']).read_bytes())}).json()
                self.assertEqual(revised['document_version'], 2)
                self.assertEqual(run_docx_once(self.tasks.jobs)['status'], 'reviewing')
                self.assertEqual(self.request('GET', f'/tasks/{task}/document').json()['document_version'], 2)


del Fixture

if __name__ == '__main__':
    unittest.main()
