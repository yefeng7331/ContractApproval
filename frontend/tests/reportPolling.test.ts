import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { startReportPolling } from '../src/reportPolling.ts';
import type { ReportStatus } from '../src/reports.ts';

const pending: ReportStatus = { task_id: 'task-1', review_version: 2, reports: [
  { format: 'markdown', state: 'ready', attempts: 1, generated_at: '2026-09-26T00:00:00Z' },
  { format: 'pdf', state: 'pending', attempts: 0, generated_at: null },
] };
const ready: ReportStatus = { ...pending, reports: pending.reports.map(item => ({ ...item, state: 'ready' })) };
const tick = () => new Promise<void>(resolve => setImmediate(resolve));

test('pending report survives transient status failure and recovers at the same version', async () => {
  const responses: Array<ReportStatus | Error> = [pending, new ApiError(0, '连接暂时失败'), ready];
  const timers: Array<() => void> = [];
  const delays: number[] = [];
  let visible: ReportStatus | null = null;
  let error = '';
  const calls: Array<[string, number, string]> = [];
  const stop = startReportPolling({ taskId: 'task-1', version: 2, token: 'token',
    load: async (taskId, version, token) => {
      calls.push([taskId, version, token]);
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return response!;
    },
    onStatus: result => { visible = result; error = ''; },
    onError: (message, retrying) => { assert.equal(retrying, true); error = message; },
    onExpired: () => assert.fail('transient failure must not expire session'),
    onSettled: () => {},
    schedule: (run, delay) => { timers.push(run); delays.push(delay); return timers.length as unknown as ReturnType<typeof setTimeout>; },
  });
  try {
    await tick();
    assert.equal(visible, pending);
    timers.shift()!(); await tick();
    assert.equal(visible, pending);
    assert.equal(error, '连接暂时失败');
    timers.shift()!(); await tick();
    assert.equal(visible, ready);
    assert.equal(error, '');
    assert.equal(timers.length, 0);
    assert.deepEqual(delays, [5000, 5000]);
    assert.deepEqual(calls, Array(3).fill(['task-1', 2, 'token']));
  } finally { stop(); }
});

test('401, permission refusal and mismatched version stop polling', async () => {
  for (const response of [new ApiError(401, '会话失效'), new ApiError(403, '无权读取'),
    { ...pending, review_version: 3 }]) {
    let expired = '';
    let error = '';
    let scheduled = false;
    const stop = startReportPolling({ taskId: 'task-1', version: 2, token: 'token',
      load: async () => { if (response instanceof Error) throw response; return response; },
      onStatus: () => assert.fail('invalid response must not become visible'),
      onError: (message, retrying) => { assert.equal(retrying, false); error = message; },
      onExpired: message => { expired = message; },
      onSettled: () => {},
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
