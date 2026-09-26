import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { canAdminRetry, readAttachmentHistory, readRecoveryTask, recoveryInstruction, retryBlockedTask } from '../src/recovery.ts';
import type { Task } from '../src/model.ts';

const task = { task_id: 'task/1', source: 'mock_pending', document_version: 1,
  machine_status: 'blocked', recovery_action: 'admin_retry', blocked_code: 'ATTACHMENT_FETCH_TIMEOUT' } as Task;

test('only an administrator may retry a blocked task marked admin_retry', () => {
  assert.equal(canAdminRetry(task, 'admin'), true);
  assert.equal(canAdminRetry(task, 'business'), false);
  assert.equal(canAdminRetry(task, 'legal'), false);
  assert.equal(canAdminRetry({ ...task, machine_status: 'pending' }, 'admin'), false);
  assert.equal(canAdminRetry({ ...task, recovery_action: 'replace_attachment' }, 'admin'), false);
  assert.equal(canAdminRetry({ ...task, recovery_action: 'budget_decision' }, 'admin'), false);
  assert.match(recoveryInstruction({ ...task, recovery_action: 'replace_attachment' }), /业务经办人/);
  assert.match(recoveryInstruction({ ...task, recovery_action: 'budget_decision' }), /预算决策/);
});

test('retry sends one request for the current document version and receives current task', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    return Response.json({ ...task, machine_status: 'pending', recovery_action: null });
  };
  try {
    const result = await retryBlockedTask(task, 'admin', 'admin-token');
    assert.equal(result.machine_status, 'pending');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/v1/tasks/task%2F1/retry');
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.body, JSON.stringify({ document_version: 1 }));
    assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer admin-token');
    await assert.rejects(retryBlockedTask(task, 'business', 'business-token'), error => error instanceof ApiError && error.status === 403);
    assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});

test('attachment history is version bound and retry conflicts are surfaced', async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push(String(url));
    if (init?.method === 'POST') return Response.json({ detail: { message: 'state conflict' } }, { status: 409 });
    return Response.json({ task_id: task.task_id, document_version: 1,
      attempts: [{ attempt: 1, state: 'failed', error_code: 'ATTACHMENT_FETCH_TIMEOUT', started_at: '2026-09-26T00:00:00Z', finished_at: null, actor_user_id: 'user-1' }] });
  };
  try {
    const history = await readAttachmentHistory(task, 'admin-token');
    assert.equal(history.attempts[0].error_code, 'ATTACHMENT_FETCH_TIMEOUT');
    assert.equal(calls[0], '/api/v1/tasks/task%2F1/attachment-attempts');
    await assert.rejects(retryBlockedTask(task, 'admin', 'admin-token'), error => error instanceof ApiError && error.status === 409);
    await assert.rejects(readAttachmentHistory({ ...task, document_version: 2 }, 'admin-token'), error => error instanceof ApiError && error.status === 0);
  } finally { globalThis.fetch = original; }
});

test('server rejects unauthorized attachment history and retry', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: 'forbidden' }, { status: 403 });
  try {
    await assert.rejects(readAttachmentHistory(task, 'business-token'), error => error instanceof ApiError && error.status === 403);
    await assert.rejects(retryBlockedTask(task, 'admin', 'invalid-token'), error => error instanceof ApiError && error.status === 403);
  } finally { globalThis.fetch = original; }
});

test('uncertain retry can be reconciled by reading the current task before another submit', async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async url => { calls.push(String(url)); return Response.json({ ...task, machine_status: 'pending' }); };
  try {
    assert.equal((await readRecoveryTask(task.task_id, 'admin-token')).machine_status, 'pending');
    assert.deepEqual(calls, ['/api/v1/tasks/task%2F1']);
  } finally { globalThis.fetch = original; }
});
