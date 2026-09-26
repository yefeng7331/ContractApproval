import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { readWriteback, readWritebackTargets, submitWriteback, validateWritebackStatus, writebackVersion } from '../src/writeback.ts';
import type { Task } from '../src/model.ts';

const task = { task_id: 'task-1', document_version: 2, review_version: 2,
  legal_status: 'in_review', latest_confirmed_version: { document_version: 1, review_version: 1 } } as Task;

test('legal and business use confirmed history; admin only uses current confirmed version', () => {
  assert.deepEqual(writebackVersion(task, 'legal'), { document_version: 1, review_version: 1, historical: true });
  assert.deepEqual(writebackVersion(task, 'business'), { document_version: 1, review_version: 1, historical: true });
  assert.equal(writebackVersion(task, 'admin'), null);
  assert.deepEqual(writebackVersion({ ...task, legal_status: 'confirmed' }, 'admin'),
    { document_version: 2, review_version: 2, historical: false });
  assert.equal(writebackVersion({ ...task, latest_confirmed_version: null }, 'business'), null);
});

test('status, target selection and submit use exact confirmed version and Bearer', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    if (String(url).endsWith('/mock-writeback-targets')) return Response.json({ items: [{ id: 'demo-f1-001', title: '合成待办', synthetic: true }] });
    return Response.json({ task_id: 'task-1', document_version: 1, review_version: 1, simulated: true,
      mock_approval_id: 'demo-f1-001', state: init?.method === 'POST' ? 'writing' : 'not_written', comment_id: null });
  };
  try {
    assert.equal((await readWriteback('task-1', 1, 'token')).state, 'not_written');
    assert.equal((await readWritebackTargets('token')).items[0].id, 'demo-f1-001');
    assert.equal((await submitWriteback('task-1', 1, 'demo-f1-001', 'token')).state, 'writing');
    assert.deepEqual(calls.map(call => call.url), [
      '/api/v1/tasks/task-1/mock-writeback?review_version=1',
      '/api/v1/mock-writeback-targets', '/api/v1/tasks/task-1/mock-writeback',
    ]);
    assert.ok(calls.every(call => new Headers(call.init.headers).get('Authorization') === 'Bearer token'));
    assert.equal(calls[2].init.method, 'POST');
    assert.equal(calls[2].init.body, JSON.stringify({ review_version: 1, mock_approval_id: 'demo-f1-001' }));
  } finally { globalThis.fetch = original; }
});

test('unconfirmed and unauthorized operations are rejected', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => Response.json({ message: '拒绝' },
    { status: init?.method === 'POST' ? 403 : String(url).includes('targets') ? 403 : 409 });
  try {
    await assert.rejects(readWriteback('task-1', 2, 'token'), error => error instanceof ApiError && error.status === 409);
    await assert.rejects(readWritebackTargets('token'), error => error instanceof ApiError && error.status === 403);
    await assert.rejects(submitWriteback('task-1', 1, 'demo-f1-001', 'token'), error => error instanceof ApiError && error.status === 403);
  } finally { globalThis.fetch = original; }
});

test('success requires a matching confirmed version and a comment ID', () => {
  const result = { task_id: 'task-1', document_version: 1, review_version: 1, simulated: true as const,
    mock_approval_id: 'demo-f1-001', state: 'success' as const, comment_id: 'comment-1', completed_at: null };
  assert.equal(validateWritebackStatus(result, 'task-1', 1, 1).comment_id, 'comment-1');
  assert.throws(() => validateWritebackStatus({ ...result, comment_id: null }, 'task-1', 1, 1));
  assert.throws(() => validateWritebackStatus(result, 'task-1', 2, 1));
});
