import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { AUDIT_PAGE_SIZE, auditActionName, readAuditEvents } from '../src/audit.ts';

const item = { id: 7, action: 'review_confirmed', document_version: 2,
  created_at: '2026-09-26T00:00:00Z', actor_username: 'legal-demo', actor_role: 'legal' };

test('admin reads task operation records with exact task, version, page and bearer', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    return Response.json({ task_id: 'task/1', total: 21, items: [item] });
  };
  try {
    const result = await readAuditEvents('task/1', 'admin-token', 2, AUDIT_PAGE_SIZE);
    assert.equal(result.items[0].action, 'review_confirmed');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/v1/tasks/task%2F1/audit-events?limit=20&offset=20&document_version=2');
    assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer admin-token');
    assert.equal(calls[0].init.method, undefined);
    assert.equal(auditActionName('review_confirmed'), '确认法务结论');
    assert.equal(auditActionName('mock_writeback_succeeded'), '模拟回写成功');
    assert.equal(auditActionName('future_action'), 'future_action');
  } finally { globalThis.fetch = original; }
});

test('operation records reject a different task or document version', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ task_id: 'other', total: 1, items: [item] });
    await assert.rejects(readAuditEvents('task/1', 'admin-token', 2, 0), error => error instanceof ApiError && error.status === 0);
    globalThis.fetch = async () => Response.json({ task_id: 'task/1', total: 1, items: [item] });
    await assert.rejects(readAuditEvents('task/1', 'admin-token', 1, 0), error => error instanceof ApiError && error.status === 0);
  } finally { globalThis.fetch = original; }
});

test('server denies non-admin and expired sessions', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ detail: 'forbidden' }, { status: 403 });
    await assert.rejects(readAuditEvents('task/1', 'business-token', null, 0), error => error instanceof ApiError && error.status === 403);
    globalThis.fetch = async () => Response.json({ detail: 'unauthorized' }, { status: 401 });
    await assert.rejects(readAuditEvents('task/1', 'expired-token', null, 0), error => error instanceof ApiError && error.status === 401);
  } finally { globalThis.fetch = original; }
});
