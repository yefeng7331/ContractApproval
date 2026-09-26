import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contractAmount, contractTitle, formalRisk, formatTaskTime, isActive, nextStep, phase } from '../src/model.ts';
import type { Task } from '../src/model.ts';
import { ApiError, loadTasks, request } from '../src/api.ts';

const task: Task = { task_id: 'one', owner_username: 'business1', source: 'upload', created_at: '', document_version: 2,
  review_version: 2, machine_status: 'completed', legal_status: 'in_review', writeback_status: 'not_written',
  blocked_code: null, blocked_reason: null, recovery_action: null, attempt_count: 1,
  latest_confirmed_version: { document_version: 1, review_version: 1 }, risk_level: 'high' };

test('dashboard creation time uses local display and marks invalid data', () => {
  const expected = new Date('2026-09-26T08:30:00Z').toLocaleString('zh-CN', { hour12: false });
  assert.equal(formatTaskTime('2026-09-26T08:30:00Z'), expected);
  assert.equal(formatTaskTime(''), '时间未记录');
});

test('contract name and amount show identified data without guessing missing currency', () => {
  assert.equal(contractTitle(task), '待法务确认');
  assert.equal(contractAmount(task), '待法务确认');
  assert.equal(contractTitle({ ...task, contract: { title: null, amount: null, currency: null } }), '未识别');
  assert.equal(contractAmount({ ...task, contract: { title: null, amount: null, currency: null } }), '未识别');
  const identified = { ...task, contract: { title: '软件采购合同', amount: '120,000', currency: null } };
  assert.equal(contractTitle(identified), '软件采购合同');
  assert.equal(contractAmount(identified), '120,000（币种未识别）');
});

test('current phase and formal risk do not inherit historical confirmation', () => {
  assert.equal(phase(task), 'review');
  assert.equal(formalRisk(task), '尚无正式等级');
  assert.equal(phase({ ...task, machine_status: 'blocked', legal_status: 'confirmed' }), 'blocked');
  assert.equal(formalRisk({ ...task, legal_status: 'confirmed' }), '高风险');
  assert.equal(formalRisk({ ...task, legal_status: 'confirmed', risk_level: null }), '无分级结果（以确认意见为准）');
  assert.equal(isActive(task), false);
  assert.equal(isActive({ ...task, writeback_status: 'writing' }), true);
  assert.equal(nextStep({ ...task, machine_status: 'blocked', recovery_action: 'admin_retry' }, 'business'), '联系管理员恢复处理');
  assert.equal(nextStep({ ...task, machine_status: 'blocked', recovery_action: 'replace_attachment' }, 'admin'), '等待业务经办人换传附件');
});

test('all visible pages are collected; duplicate ids do not inflate overview', async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push(String(url));
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer test-only');
    assert.equal(init?.cache, 'no-store');
    assert.equal(init?.credentials, 'omit');
    return Response.json(calls.length === 1 ? { items: [task], total: 2 } : { items: [task, { ...task, task_id: 'two' }], total: 3 });
  };
  try {
    const tasks = await loadTasks('test-only', new AbortController().signal);
    assert.equal(tasks.length, 2);
    assert.match(calls[1], /offset=1/);
  } finally { globalThis.fetch = original; }
});

test('401, invalid JSON and network failure are actionable, 204 logout needs no JSON', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('', { status: 401 });
    await assert.rejects(request('/tasks', 'test-only'), (error: unknown) => error instanceof ApiError && error.status === 401);
    globalThis.fetch = async () => new Response('<html>not an API</html>');
    await assert.rejects(request('/tasks', 'test-only'), /响应无法读取/);
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(request('/tasks', 'test-only'), /无法连接服务/);
    globalThis.fetch = async () => new Response(null, { status: 204 });
    assert.equal(await request('/sessions/current', 'test-only', undefined, { method: 'DELETE' }), undefined);
  } finally { globalThis.fetch = original; }
});

test('aborted reads cannot produce a partial successful dashboard', async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async (_, init) => { init?.signal?.throwIfAborted(); return Response.json({ items: [], total: 0 }); };
  try { await assert.rejects(loadTasks('test-only', controller.signal), { name: 'AbortError' }); }
  finally { globalThis.fetch = original; }
});
