"""Independent offline smoke: real F1/F4 evidence, fake TLS/HTTP, no real key."""

import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.errors import ApiError
from backend.model_advice import validate_response
from backend.model_transport import prepare_request, _post_json, MAX_RESPONSE_BYTES
from backend.tasks import TaskStore


class ModelTransportTests(unittest.TestCase):
    def test_preflight_and_ledger(self):
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
                for name in ('f1-software-purchase.docx', 'f4-revised-software-purchase.docx'):
                    task = tasks.create_task(owner, name, (samples / name).read_bytes(), 'test', 'test')['task_id']
                    self.assertEqual(run_docx_once(tasks.jobs)['status'], 'reviewing')
                    self.assertEqual(tasks.rule_snapshots.run_next()['status'], 'completed')
                    snapshot = tasks.get_rule_snapshot(task, legal)
                    if name.startswith('f4'):
                        self.assertIsNone(prepare_request(snapshot, tokenizer_path=root / 'missing.zip'))
                        continue
                    with self.assertRaises(ApiError) as missing:
                        prepare_request(snapshot, tokenizer_path=root / 'missing.zip')
                    self.assertEqual(missing.exception.code, 'MODEL_TOKENIZER_UNAVAILABLE')
                    corrupt = root / 'corrupt.zip'
                    corrupt.write_bytes(b'not the reviewed tokenizer')
                    with self.assertRaises(ApiError) as changed:
                        prepare_request(snapshot, tokenizer_path=corrupt)
                    self.assertEqual(changed.exception.code, 'MODEL_TOKENIZER_UNAVAILABLE')
                    with patch.dict('sys.modules', {'tokenizers': None}):
                        with self.assertRaises(ApiError) as dependency:
                            prepare_request(snapshot)
                    self.assertEqual(dependency.exception.code, 'MODEL_TOKENIZER_UNAVAILABLE')
                    for invalid in (True, 0, -1, 2.5, '1000', 1_000_001):
                        with patch('backend.model_transport.estimate_input_tokens', return_value=invalid):
                            with self.assertRaises(ValueError):
                                prepare_request(snapshot)
                    # Synthetic counts only. 33,616 * 2 + 4,096 * 8 = 100,000 microyuan.
                    with patch('backend.model_transport.estimate_input_tokens', return_value=33_616):
                        exact = prepare_request(snapshot)
                    self.assertEqual(exact['estimated_microyuan'], 100_000)
                    with patch('backend.model_transport.estimate_input_tokens', return_value=33_617):
                        with self.assertRaises(ApiError) as over:
                            prepare_request(snapshot)
                    self.assertEqual(over.exception.code, 'MODEL_CALL_LIMIT')
                    # Real pinned local tokenizer + real synthetic F1, no network.
                    prepared = prepare_request(snapshot)
                    self.assertEqual(prepared['quote']['input_tokens'], 476)
                    self.assertEqual(prepared['estimated_microyuan'], 33_720)
                    self.assertEqual(prepared['quote']['max_output_tokens'], 4096)
                    self.assertEqual(prepared['quote']['reservation_microyuan'], 100_000)
                    self.assertIn('local-chat-template-estimate', prepared['quote']['input_reference'])
                    self.assertEqual(json.loads(prepared['body'])['model'], 'deepseek-flash')
                    self.assertEqual(len(prepared['request_sha256']), 64)
                    # Caller-side ledger composition; this is not an automatic model job.
                    budget = tasks.model_budget
                    held = budget.reserve('offline-success', task, 1, **prepared['quote'])
                    self.assertEqual(held['reserved_microyuan'], 100_000)
                    self.assertEqual(json.loads(held['quote_json']), prepared['quote'])
                    for invalid in (True, 0, 33_719, -1, '100000', 10**15 + 1):
                        with self.assertRaises(ValueError):
                            budget.reserve('invalid-floor', task, 1,
                                **{**prepared['quote'], 'reservation_microyuan': invalid})
                    with self.assertRaises(ApiError) as conflict:
                        budget.reserve('offline-success', task, 1,
                            **{**prepared['quote'], 'reservation_microyuan': 100_001})
                    self.assertEqual(conflict.exception.code, 'BUDGET_CALL_CONFLICT')
                    advice = {key: snapshot[key] for key in ('document_version', 'evidence_sha256', 'rule_version')}
                    advice['suggestions'] = [{'rule_id': risk['rule_id'], 'suggestion': '请法务核定协商建议。'}
                        for risk in snapshot['risks']]
                    raw = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                        'content': json.dumps(advice)}}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}).encode()
                    response = MagicMock(status=200)
                    response.getheader.side_effect = lambda key, default=None: {'Content-Type': 'application/json'}.get(key, default)
                    response.read1.side_effect = io.BytesIO(raw).read1
                    with patch('backend.model_transport.http.client.HTTPSConnection') as factory:
                        factory.return_value.getresponse.return_value = response
                        result = validate_response(snapshot, _post_json(prepared['body'], 'fake-test-key'))
                    self.assertFalse(result['requires_legal_supplement'])
                    self.assertEqual(budget.settle('offline-success', **result['usage'])['estimated_microyuan'], 60)
                    reservation = budget.reserve('offline-transport', task, 1, **prepared['quote'])
                    self.assertTrue(reservation['created'])
                    self.assertEqual(reservation['reserved_microyuan'], 100_000)
                    self.assertFalse(budget.reserve('offline-transport', task, 1, **prepared['quote'])['created'])
                    self.assertEqual(budget.settle('offline-transport')['state'], 'unknown')
                    self.assertEqual(budget.summary()['held_microyuan'], 100_000)
                    # Restart preserves the full unknown hold, not just the 0.03372 estimate.
                    reopened = AuthStore(root / 'test.sqlite3')
                    try:
                        reopened_tasks = TaskStore(reopened, root / 'uploads')
                        reopened_tasks.initialize()
                        self.assertEqual(reopened_tasks.model_budget.summary()['held_microyuan'], 100_000)
                        self.assertFalse(reopened_tasks.model_budget.reserve(
                            'offline-transport', task, 1, **prepared['quote'])['created'])
                    finally:
                        reopened.close()
                    # Usage may exceed the application reservation; never clamp accounting.
                    budget.reserve('offline-overrun', task, 1, **prepared['quote'])
                    self.assertEqual(budget.settle('offline-overrun', input_tokens=40_000,
                        output_tokens=4096)['estimated_microyuan'], 112_768)
                    # Another caller has consumed almost all project budget.
                    budget.reserve('synthetic-expense', task, 1, model='synthetic',
                        price_reference='SYNTHETIC', input_tokens=49_750,
                        max_output_tokens=0, input_rate=1_000_000_000, output_rate=0)
                    self.assertGreater(budget.summary()['available_microyuan'], prepared['estimated_microyuan'])
                    self.assertLess(budget.summary()['available_microyuan'], 100_000)
                    rejected = budget.reserve('no-budget', task, 1, **prepared['quote'])
                    self.assertEqual(rejected['state'], 'rejected')
                    self.assertFalse(rejected['created'])
            finally:
                auth.close()

    def test_https_boundary(self):
        def run(raw=b'{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
                *, status=200, headers=None, error=None, error_stage='request', ticks=None):
            headers = {'Content-Type': 'application/json; charset=utf-8', **(headers or {})}
            response = MagicMock(status=status)
            response.getheader.side_effect = lambda name, default=None: headers.get(name, default)
            response.read1.side_effect = io.BytesIO(raw).read1
            connection = MagicMock()
            connection.getresponse.return_value = response
            if error:
                if error_stage == 'read':
                    response.read1.side_effect = error
                else:
                    getattr(connection, error_stage).side_effect = error
            with patch('backend.model_transport.http.client.HTTPSConnection', return_value=connection) as factory:
                with patch('backend.model_transport.time.monotonic', side_effect=ticks) if ticks else patch(
                        'backend.model_transport.time.monotonic', return_value=1):
                    try:
                        result = _post_json(b'{"model":"deepseek-flash"}', 'fake-test-key')
                    except ApiError as exc:
                        result = exc
                factory.assert_called_once()
                self.assertEqual(factory.call_args.args, ('api.deepseek.com',))
                self.assertEqual(factory.call_args.kwargs['context'].verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(factory.call_args.kwargs['context'].check_hostname)
                connection.connect.assert_called_once()
                if error_stage == 'connect' and error:
                    connection.request.assert_not_called()
                else:
                    connection.request.assert_called_once()
                    self.assertEqual(connection.request.call_args.args, ('POST', '/chat/completions'))
                    self.assertEqual(connection.request.call_args.kwargs['headers']['Authorization'], 'Bearer fake-test-key')
                connection.close.assert_called_once()
                if status != 200:
                    response.read1.assert_not_called()
                if isinstance(result, ApiError):
                    self.assertNotIn('fake-test-key', result.message)
                    self.assertNotIn('sensitive', result.message)
                    self.assertFalse(result.retryable)
                return result

        self.assertEqual(run()['usage']['total_tokens'], 15)
        for status, code in [(301, 'MODEL_HTTP_ERROR'), (302, 'MODEL_HTTP_ERROR'),
                             (307, 'MODEL_HTTP_ERROR'), (308, 'MODEL_HTTP_ERROR'),
                             (401, 'MODEL_AUTH_FAILED'), (403, 'MODEL_AUTH_FAILED'),
                             (402, 'MODEL_BALANCE_REQUIRED'), (429, 'MODEL_RATE_LIMIT'),
                             (500, 'MODEL_HTTP_ERROR'), (503, 'MODEL_HTTP_ERROR')]:
            with self.subTest(status=status):
                self.assertEqual(run(status=status).code, code)
        for raw in (b'not json', b'\xff', b'[]', b'{"usage":{},"usage":{}}', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.subTest(raw=raw):
                self.assertEqual(run(raw).code, 'MODEL_RESPONSE_INVALID')
        for headers in ({'Content-Type': 'text/html'}, {'Content-Encoding': 'gzip'},
                        {'Content-Length': '-1'}, {'Content-Length': 'x'}, {'Content-Length': '99999999999'},
                        {'Content-Length': '2'}):
            self.assertEqual(run(headers=headers).code, 'MODEL_RESPONSE_INVALID')
        self.assertEqual(run(headers={'Content-Length': str(MAX_RESPONSE_BYTES + 1)}).code, 'MODEL_RESPONSE_TOO_LARGE')
        self.assertEqual(run(b' ' * (MAX_RESPONSE_BYTES + 1)).code, 'MODEL_RESPONSE_TOO_LARGE')
        self.assertEqual(run(b'{}' + b' ' * (MAX_RESPONSE_BYTES - 2)), {})
        self.assertEqual(run(error=TimeoutError('sensitive fake-test-key')).code, 'MODEL_TIMEOUT')
        self.assertEqual(run(error=OSError('sensitive fake-test-key')).code, 'MODEL_TRANSPORT_FAILED')
        for stage in ('connect', 'getresponse', 'read'):
            self.assertEqual(run(error=TimeoutError('sensitive fake-test-key'), error_stage=stage).code, 'MODEL_TIMEOUT')
        self.assertEqual(run(error=ssl.SSLError('sensitive'), error_stage='connect').code, 'MODEL_TRANSPORT_FAILED')
        self.assertEqual(run(ticks=[0, 0, 0, 61]).code, 'MODEL_TIMEOUT')

    def test_no_connection_for_invalid_arguments(self):
        with patch('backend.model_transport.http.client.HTTPSConnection') as factory:
            for body, key in [(b'', 'fake'), (b'{}', ''), (b'{}', 'fake\r\nHeader: bad'),
                              (b'{}', 'fake key'), (b'{}', '中文'), (b'x' * 100_001, 'fake')]:
                with self.assertRaises(ValueError):
                    _post_json(body, key)
            factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
