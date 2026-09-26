import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../src/api.ts';
import { startTaskPolling } from '../src/taskPolling.ts';
import type { Task } from '../src/model.ts';

const task: Task = {
  task_id: 'synthetic-task', owner_username: 'owner', source: 'upload', created_at: '',
  document_version: 1, review_version: null, machine_status: 'parsing',
  legal_status: 'pending', writeback_status: 'not_written', blocked_code: null,
  blocked_reason: null, recovery_action: null, attempt_count: 1,
};
const tick = () => new Promise<void>(resolve => setImmediate(resolve));

test('a transient poll failure keeps the last tasks and retries until completion', async () => {
  const responses: Array<Task[] | Error> = [[task], new ApiError(0, '连接暂时失败'),
    [{ ...task, machine_status: 'completed' }]];
  const timers: Array<() => void> = [];
  const delays: number[] = [];
  let visible: Task[] = [];
  let error = '';
  let settled = 0;
  const stop = startTaskPolling({ token: 'synthetic-token',
    load: async () => { const response = responses.shift(); if (response instanceof Error) throw response; return response!; },
    onTasks: tasks => { visible = tasks; error = ''; },
    onError: message => { error = message; },
    onExpired: () => assert.fail('transient failure must not expire session'),
    onForbidden: () => assert.fail('transient failure must not revoke access'),
    onSettled: () => { settled++; },
    schedule: (run, delay) => { timers.push(run); delays.push(delay); return timers.length as unknown as ReturnType<typeof setTimeout>; },
  });
  try {
    await tick();
    assert.equal(visible[0].machine_status, 'parsing');
    assert.equal(timers.length, 1);
    timers.shift()!(); await tick();
    assert.equal(error, '连接暂时失败');
    assert.equal(visible[0].machine_status, 'parsing');
    assert.equal(timers.length, 1);
    timers.shift()!(); await tick();
    assert.equal(visible[0].machine_status, 'completed');
    assert.equal(error, '');
    assert.equal(timers.length, 0);
    assert.deepEqual(delays, [5000, 5000]);
    assert.equal(settled, 3);
  } finally { stop(); }
});

test('an expired session stops polling and never shows tasks', async () => {
  let expired = '';
  let scheduled = false;
  const stop = startTaskPolling({ token: 'synthetic-token',
    load: async () => { throw new ApiError(401, '登录已失效'); },
    onTasks: () => assert.fail('expired session must not show tasks'),
    onError: () => assert.fail('401 must not become a transient error'),
    onExpired: message => { expired = message; },
    onForbidden: () => assert.fail('401 must expire session'),
    onSettled: () => {},
    schedule: () => { scheduled = true; return 1 as unknown as ReturnType<typeof setTimeout>; },
  });
  try { await tick(); assert.equal(expired, '登录已失效'); assert.equal(scheduled, false); }
  finally { stop(); }
});

test('a forbidden response stops polling and revokes the cached list', async () => {
  const timers: Array<() => void> = [];
  let visible: Task[] = [];
  let forbidden = '';
  let reads = 0;
  const stop = startTaskPolling({ token: 'synthetic-token',
    load: async () => { reads++; if (reads === 1) return [task]; throw new ApiError(403, '无权访问任务'); },
    onTasks: tasks => { visible = tasks; },
    onError: () => assert.fail('403 must not be retried as a transient failure'),
    onExpired: () => assert.fail('403 must not expire the session'),
    onForbidden: message => { forbidden = message; visible = []; },
    onSettled: () => {},
    schedule: run => { timers.push(run); return timers.length as unknown as ReturnType<typeof setTimeout>; },
  });
  try {
    await tick();
    assert.equal(visible.length, 1);
    timers.shift()!(); await tick();
    assert.equal(forbidden, '无权访问任务');
    assert.deepEqual(visible, []);
    assert.equal(timers.length, 0);
    assert.equal(reads, 2);
  } finally { stop(); }
});
