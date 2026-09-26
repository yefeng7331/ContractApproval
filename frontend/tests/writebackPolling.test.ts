import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { startWritebackPolling } from '../src/writebackPolling.ts';
import type { WritebackStatus } from '../src/writeback.ts';

const writing: WritebackStatus = { task_id: 'task-1', document_version: 2, review_version: 3,
  simulated: true, mock_approval_id: 'demo-1', state: 'writing', comment_id: null, completed_at: null };
const success: WritebackStatus = { ...writing, state: 'success', comment_id: 'comment-1' };
const tick = () => new Promise<void>(resolve => setImmediate(resolve));

test('writing status survives a transient GET failure, then reaches success without another POST', async () => {
  const responses: Array<WritebackStatus | Error> = [writing, new ApiError(0, '连接暂时失败'), success];
  const timers: Array<() => void> = [];
  const calls: Array<[string, number, string]> = [];
  let visible: WritebackStatus | null = null;
  let error = '';
  const stop = startWritebackPolling({ taskId: 'task-1', documentVersion: 2, reviewVersion: 3,
    role: 'legal', token: 'token',
    load: async (id, version, token) => {
      calls.push([id, version, token]);
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return response!;
    },
    loadTargets: async () => assert.fail('bound writeback must not load targets'),
    onStatus: result => { visible = result; error = ''; },
    onTargets: (_, boundId) => assert.equal(boundId, 'demo-1'),
    onError: (message, retrying) => { assert.equal(retrying, true); error = message; },
    onExpired: () => assert.fail('transient GET failure must not expire session'),
    onStart: () => {}, onSettled: () => {},
    schedule: run => { timers.push(run); return timers.length as unknown as ReturnType<typeof setTimeout>; },
  });
  try {
    await tick();
    assert.equal(visible, writing);
    timers.shift()!(); await tick();
    assert.equal(visible, writing);
    assert.equal(error, '连接暂时失败');
    timers.shift()!(); await tick();
    assert.equal(visible, success);
    assert.equal(error, '');
    assert.equal(timers.length, 0);
    assert.deepEqual(calls, Array(3).fill(['task-1', 3, 'token']));
  } finally { stop(); }
});

test('401, forbidden status and mismatched confirmation stop GET polling', async () => {
  for (const response of [new ApiError(401, '会话失效'), new ApiError(403, '无权读取'),
    { ...writing, review_version: 4 }]) {
    let expired = '';
    let error = '';
    let scheduled = false;
    const stop = startWritebackPolling({ taskId: 'task-1', documentVersion: 2, reviewVersion: 3,
      role: 'business', token: 'token',
      load: async () => { if (response instanceof Error) throw response; return response; },
      onStatus: () => assert.fail('invalid result must not become visible'),
      onTargets: () => assert.fail('invalid result must not load targets'),
      onError: (message, retrying) => { assert.equal(retrying, false); error = message; },
      onExpired: message => { expired = message; },
      onStart: () => {}, onSettled: () => {},
      schedule: () => { scheduled = true; return 1 as unknown as ReturnType<typeof setTimeout>; },
    });
    try {
      await tick();
      assert.equal(scheduled, false);
      if (response instanceof ApiError && response.status === 401) assert.equal(expired, '会话失效');
      else assert.ok(error);
    } finally { stop(); }
  }
});
