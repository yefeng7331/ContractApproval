"""Independent budget smoke: synthetic prices, temporary database, no network."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.auth import AuthStore
from backend.docx_job import run_docx_once
from backend.errors import ApiError
from backend.model_budget import estimate
from backend.tasks import TaskStore


class ModelBudgetTests(unittest.TestCase):
    def test_budget_ledger_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = AuthStore(root / 'test.sqlite3')
            other = None
            try:
                auth.initialize()
                owner = auth.create_user('owner', 'business', 'synthetic-password')
                tasks = TaskStore(auth, root / 'uploads')
                tasks.initialize()
                content = (Path(__file__).resolve().parents[1] / 'samples/f1-software-purchase.docx').read_bytes()
                def new_task():
                    task_id = tasks.create_task(owner, 'f1.docx', content, 'test', 'test')['task_id']
                    self.assertEqual(run_docx_once(tasks.jobs)['status'], 'reviewing')
                    return task_id
                first, second, third = [new_task() for _ in range(3)]
                budget = tasks.model_budget
                # Rates above the supported bound are invalid, not silently truncated.
                with self.assertRaises(ValueError):
                    estimate(20, 5, 10**12, 2 * 10**12)
                # Intentionally synthetic: 1 CNY per token, not an official price.
                def reserve(store, call, task, inputs=20, outputs=10):
                    return store.reserve(call, task, 1, model='synthetic-model',
                        price_reference='SYNTHETIC TEST PRICE; NOT OFFICIAL',
                        input_tokens=inputs, max_output_tokens=outputs,
                        input_rate=10**12, output_rate=10**12)
                self.assertEqual(estimate(1, 0, 1, 0), 1)
                with self.assertRaises(ApiError) as stale:
                    budget.reserve('stale', first, 2, model='synthetic', price_reference='synthetic',
                        input_tokens=1, max_output_tokens=1, input_rate=1, output_rate=1)
                self.assertEqual(stale.exception.code, 'BUDGET_TASK_NOT_READY')
                with self.assertRaises(ValueError):
                    reserve(budget, 'zero', first, 0, 0)
                for invalid in (True, -1, 0.1, '1', 10**13):
                    with self.assertRaises(ValueError):
                        estimate(invalid, 0, 1, 0)
                # Interrupted transaction must not consume money or persist a row.
                with patch.object(budget, 'summary', side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        reserve(budget, 'interrupted', first)
                self.assertEqual(budget.summary()['held_microyuan'], 0)
                other = AuthStore(root / 'test.sqlite3')
                other.initialize()
                other_tasks = TaskStore(other, root / 'uploads')
                other_tasks.initialize()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(reserve, store, call, task) for store, call, task in
                        [(budget, 'a', first), (other_tasks.model_budget, 'b', second)]]
                    results = [future.result() for future in futures]
                self.assertEqual(sorted(r['state'] for r in results), ['rejected', 'reserved'])
                accepted = next(r for r in results if r['state'] == 'reserved')
                rejected = next(r for r in results if r['state'] == 'rejected')
                call, task = accepted['call_id'], accepted['task_id']
                self.assertFalse(reserve(budget, call, task)['created'])
                with self.assertRaises(ApiError):
                    reserve(budget, call, task, inputs=19)
                blocked = tasks.get_task(rejected['task_id'], owner)
                self.assertFalse(reserve(budget, rejected['call_id'], rejected['task_id'])['created'])
                self.assertEqual(blocked['blocked_code'], 'BUDGET_LIMIT')
                self.assertEqual(blocked['recovery_action'], 'budget_decision')
                self.assertEqual(blocked['machine_status'], 'blocked')
                self.assertEqual(budget.summary()['held_microyuan'], 30_000_000)
                self.assertEqual(budget.settle(call)['state'], 'unknown')
                self.assertEqual(budget.settle(call)['state'], 'unknown')
                with self.assertRaises(ValueError):
                    budget.settle(call, input_tokens=1)
                other.close()
                other = AuthStore(root / 'test.sqlite3')
                other.initialize()
                restarted = TaskStore(other, root / 'uploads')
                restarted.initialize()
                self.assertEqual(restarted.model_budget.summary()['held_microyuan'], 30_000_000)
                self.assertFalse(reserve(restarted.model_budget, call, task)['created'])
                # Known usage is 5 CNY; settle once, release remaining 25 CNY.
                settled = budget.settle(call, input_tokens=3, output_tokens=2)
                self.assertEqual(settled['estimated_microyuan'], 5_000_000)
                self.assertEqual(budget.settle(call, input_tokens=3, output_tokens=2), settled)
                with self.assertRaises(ApiError):
                    budget.settle(call, input_tokens=4, output_tokens=2)
                with self.assertRaises(ApiError):
                    budget.settle(rejected['call_id'], input_tokens=0, output_tokens=0)
                # Exactly 50 CNY including settled estimates is allowed.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda store: reserve(store, 'exact', third, 40, 5),
                        [budget, restarted.model_budget]))
                self.assertEqual(sorted(r['created'] for r in results), [False, True])
                self.assertEqual(budget.summary()['available_microyuan'], 0)
                # Over-reservation usage is recorded honestly, not clamped to quote.
                budget.settle('exact', input_tokens=50, output_tokens=5)
                self.assertEqual(budget.summary()['estimated_microyuan'], 60_000_000)
                self.assertEqual(budget.summary()['available_microyuan'], 0)
                fourth = new_task()
                self.assertEqual(reserve(budget, 'over', fourth, 1, 0)['state'], 'rejected')
                # A released reservation never silently clears an existing blocked task.
                self.assertEqual(tasks.get_task(rejected['task_id'], owner)['blocked_code'], 'BUDGET_LIMIT')
                with self.assertRaises(ApiError):
                    reserve(budget, 'retry-blocked', rejected['task_id'], 1, 0)
                with self.assertRaises(ApiError):
                    budget.settle('missing')
                with self.assertRaises(ApiError):
                    reserve(budget, 'missing-task', 'missing', 1, 0)
                # Quote and usage records carry no provider-bill or legal completion claim.
                self.assertEqual(tasks.get_task(task, owner)['machine_status'], 'reviewing')
                self.assertEqual(auth.connection.execute('SELECT COUNT(*) FROM model_budget_entries').fetchone()[0], 4)
            finally:
                if other is not None:
                    other.close()
                auth.close()


if __name__ == '__main__':
    unittest.main()
