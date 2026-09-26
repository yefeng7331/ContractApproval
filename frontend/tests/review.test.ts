import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../src/api.ts';
import { adopt, confirmReview, initialDecisions, saveReview, validateDecisions } from '../src/review.ts';
import type { Advice, Snapshot } from '../src/workbench.ts';

const risk = { rule_id: 'R1', rule_version: 'demo', clause_type: '付款', risk_level: 'high', suggestion: '规则建议' };
const snapshot = { risks: [risk] } as Snapshot;
const advice = { suggestions: [{ rule_id: 'R1', suggestion: '模型建议' }] } as Advice;

test('逐项采纳、人工修改与空建议校验', () => {
  const [initial] = initialDecisions(snapshot);
  assert.equal(initial.final_suggestion, '规则建议');
  const model = adopt(initial, 'model', risk as Parameters<typeof adopt>[2], advice);
  assert.equal(model.final_suggestion, '模型建议');
  const manual = adopt(model, 'manual', risk as Parameters<typeof adopt>[2], advice);
  assert.equal(manual.suggestion_source, 'manual');
  assert.equal(validateDecisions([{ ...manual, final_suggestion: '' }], snapshot, ''), '风险 R1 保留时必须提供最终建议。');
  assert.equal(validateDecisions([{ ...manual, retained: false, final_suggestion: '' }], snapshot, ''), null);
  assert.match(validateDecisions([manual, manual], snapshot, '') ?? '', /风险列表/);
});

test('保存完整同版风险列表和基准审查版本，再确认指定版本', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  try {
    globalThis.fetch = async (url, init) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      calls.push({ url: String(url), body });
      assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer legal-token');
      return Response.json({ document_version: 3, review_version: 7, status: calls.length === 1 ? 'in_review' : 'confirmed' });
    };
    const decisions = initialDecisions(snapshot);
    await saveReview('task 1', 3, 6, decisions, '已核对', 'legal-token');
    await confirmReview('task 1', 3, 7, '正式结论', 'legal-token');
    assert.match(calls[0].url, /tasks\/task%201\/review$/);
    assert.deepEqual(calls[0].body, { document_version: 3, base_review_version: 6, risks: decisions, annotation: '已核对' });
    assert.match(calls[1].url, /tasks\/task%201\/confirm$/);
    assert.deepEqual(calls[1].body, { document_version: 3, review_version: 7, conclusion: '正式结论' });
  } finally { globalThis.fetch = original; }
});

test('权限拒绝与版本冲突原样上报，不自动重复提交', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () => { calls++; return Response.json({ code: calls === 1 ? 'FORBIDDEN' : 'REVIEW_VERSION_CONFLICT', message: calls === 1 ? '无权限' : '版本冲突' }, { status: calls === 1 ? 403 : 409 }); };
    await assert.rejects(saveReview('task', 1, null, [], '', 'token'), (error: unknown) => error instanceof ApiError && error.status === 403);
    await assert.rejects(confirmReview('task', 1, 1, '结论', 'token'), (error: unknown) => error instanceof ApiError && error.status === 409);
    assert.equal(calls, 2);
  } finally { globalThis.fetch = original; }
});
