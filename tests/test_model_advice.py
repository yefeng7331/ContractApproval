"""Model-boundary smoke using real saved F1/F2/F4 evidence and synthetic replies."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.errors import ApiError
from backend.model_advice import build_request, validate_response, RATES, PRICE_REFERENCE
from backend.pdf_job import run_pdf_once
from backend.tasks import TaskStore


class ModelAdviceTests(unittest.TestCase):
    def test_model_advice_boundary_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = AuthStore(root / 'test.sqlite3')
            try:
                auth.initialize()
                owner = auth.create_user('owner', 'business', 'synthetic-password')
                legal = auth.create_user('legal', 'legal', 'synthetic-password')
                tasks = TaskStore(auth, root / 'uploads')
                tasks.initialize()
                samples = Path(__file__).resolve().parents[1] / 'samples'
                for filename in ('f1-software-purchase.docx', 'f2-text-software-purchase.pdf', 'f4-revised-software-purchase.docx'):
                    with self.subTest(filename=filename):
                        task_id = tasks.create_task(owner, filename, (samples / filename).read_bytes(), 'test', 'test')['task_id']
                        process = run_pdf_once if filename.endswith('.pdf') else run_docx_once
                        self.assertEqual(process(tasks.jobs)['status'], 'reviewing')
                        self.assertEqual(tasks.rule_snapshots.run_next()['status'], 'completed')
                        snapshot = tasks.get_rule_snapshot(task_id, legal)
                        original = copy.deepcopy(snapshot)
                        request = build_request(snapshot, model='deepseek-flash')
                        if filename.startswith('f4'):
                            self.assertIsNone(request)
                            self.assertEqual(snapshot['enabled_rule_risk_summary'], '未发现已启用规则风险')
                            continue
                        self.assertEqual(request['thinking'], {'type': 'disabled'})
                        self.assertEqual(request['response_format'], {'type': 'json_object'})
                        evidence = json.loads(request['messages'][1]['content'])
                        self.assertNotIn('task_id', evidence)
                        self.assertNotIn('normalized_text', evidence)
                        self.assertEqual(evidence['risks'][0]['quotes'], [a['quote'] for a in snapshot['risks'][0]['anchors']])
                        self.assertEqual(build_request(snapshot, model='deepseek-v4-pro')['model'], 'deepseek-v4-pro')
                        advice = {k: snapshot[k] for k in ('document_version', 'evidence_sha256', 'rule_version')}
                        advice['suggestions'] = [{'rule_id': r['rule_id'], 'suggestion': '请法务结合项目目的协商，并核定具体条款。'}
                            for r in reversed(snapshot['risks'])]
                        def response(data):
                            return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                                'content': json.dumps(data, ensure_ascii=False)}}],
                                'usage': {'prompt_tokens': 128, 'completion_tokens': 64, 'total_tokens': 192}}
                        valid = validate_response(snapshot, response(advice))
                        self.assertFalse(valid['requires_legal_supplement'])
                        self.assertEqual([r['rule_id'] for r in valid['suggestions']], [r['rule_id'] for r in snapshot['risks']])
                        self.assertEqual(valid['usage'], {'input_tokens': 128, 'output_tokens': 64})
                        self.assertEqual(valid['legal_basis_status'], '待法务核定')
                        bad_contents = [None, [], {**advice, 'document_version': 2},
                            {**advice, 'document_version': True}, {**advice, 'evidence_sha256': '0' * 64},
                            {**advice, 'rule_version': 'other'}, {**advice, 'anchors': []},
                            {**advice, 'suggestions': []}, {**advice, 'suggestions': [advice['suggestions'][0]] * 2}]
                        for field, value in [('rule_id', 'invented'), ('suggestion', ''), ('suggestion', 'x' * 2001),
                                             ('legal_conclusion', '合法'), ('anchors', [])]:
                            invalid = copy.deepcopy(advice)
                            invalid['suggestions'][0][field] = value
                            bad_contents.append(invalid)
                        for invalid in bad_contents:
                            result = validate_response(snapshot, response(invalid))
                            self.assertTrue(result['requires_legal_supplement'])
                            self.assertEqual(result['suggestions'], [])
                            self.assertEqual(result['usage'], valid['usage'])
                        truncated = response(advice)
                        truncated['choices'][0]['finish_reason'] = 'length'
                        duplicate_key = response(advice)
                        duplicate_key['choices'][0]['message']['content'] = '{"document_version":1,"document_version":2}'
                        for invalid in (None, {}, [], truncated, duplicate_key):
                            self.assertTrue(validate_response(snapshot, invalid)['requires_legal_supplement'])
                        unknown = response(advice)
                        unknown['usage']['total_tokens'] = 0
                        self.assertIsNone(validate_response(snapshot, unknown)['usage'])
                        self.assertFalse(validate_response(snapshot, unknown)['requires_legal_supplement'])
                        # Compose with the accepted ledger using explicit synthetic token counts.
                        budget = tasks.model_budget
                        reservation = budget.reserve(task_id, task_id, 1, model='deepseek-flash',
                            price_reference=PRICE_REFERENCE, input_tokens=1000, max_output_tokens=4096,
                            input_rate=RATES['deepseek-flash'][0], output_rate=RATES['deepseek-flash'][1])
                        self.assertEqual(reservation['reserved_microyuan'], 34_768)
                        budget.settle(task_id)
                        self.assertEqual(budget.settle(task_id, **valid['usage'])['estimated_microyuan'], 768)
                        self.assertEqual(snapshot, original)
                        self.assertEqual(tasks.get_rule_snapshot(task_id, legal), original)
                        self.assertEqual(tasks.get_task(task_id, owner)['machine_status'], 'reviewing')
                        with self.assertRaises(ApiError):
                            tasks.get_rule_snapshot(task_id, owner)
                        with self.assertRaises(ApiError):
                            build_request({**snapshot, 'persisted': False}, model='deepseek-flash')
                        oversized = copy.deepcopy(snapshot)
                        oversized['risks'][0]['anchors'][0]['quote'] = 'x' * 100_001
                        with self.assertRaises(ApiError) as error:
                            build_request(oversized, model='deepseek-flash')
                        self.assertEqual(error.exception.code, 'MODEL_INPUT_TOO_LARGE')
                        with self.assertRaises(ValueError):
                            build_request(snapshot, model='unchecked-model')
            finally:
                auth.close()


if __name__ == '__main__':
    unittest.main()
