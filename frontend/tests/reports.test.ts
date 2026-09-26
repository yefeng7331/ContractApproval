import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { confirmedReport, readReportFile, readReportStatus, reportPath, retryReport } from '../src/reports.ts';
import type { Task } from '../src/model.ts';

const task = { task_id: 'task-1', document_version: 2, review_version: 2,
  latest_confirmed_version: { document_version: 1, review_version: 1 } } as Task;

test('history and paths always use the confirmed review version', () => {
  assert.deepEqual(confirmedReport(task), { document_version: 1, review_version: 1, historical: true });
  assert.equal(reportPath(task.task_id, 1), '/tasks/task-1/reports/status?review_version=1');
  assert.equal(reportPath(task.task_id, 1, 'pdf'), '/tasks/task-1/reports/pdf?review_version=1');
  assert.equal(confirmedReport({ ...task, latest_confirmed_version: null }), null);
});

test('status, ready file and failed-format retry carry Bearer and exact version', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    if (String(url).endsWith('/retry')) return Response.json({ task_id: 'task-1', review_version: 1, reports: [{ format: 'pdf', state: 'pending' }] });
    if (String(url).includes('/pdf?')) return new Response(new Blob(['%PDF-test'], { type: 'application/pdf' }));
    return Response.json({ task_id: 'task-1', review_version: 1, reports: [{ format: 'markdown', state: 'ready' }, { format: 'pdf', state: 'failed' }] });
  };
  try {
    const status = await readReportStatus('task-1', 1, 'token');
    assert.equal(status.reports[1].state, 'failed');
    assert.equal((await readReportFile('task-1', 1, 'pdf', 'token')).type, 'application/pdf');
    assert.equal((await retryReport('task-1', 1, 'pdf', 'token')).reports[0].state, 'pending');
    assert.deepEqual(calls.map(call => call.url), [
      '/api/v1/tasks/task-1/reports/status?review_version=1',
      '/api/v1/tasks/task-1/reports/pdf?review_version=1',
      '/api/v1/tasks/task-1/reports/pdf/retry',
    ]);
    assert.ok(calls.every(call => new Headers(call.init.headers).get('Authorization') === 'Bearer token'));
    assert.equal(calls[2].init.method, 'POST');
    assert.equal(calls[2].init.body, JSON.stringify({ review_version: 1 }));
  } finally { globalThis.fetch = original; }
});

test('unready report and permission refusal do not return files or retry success', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async url => String(url).endsWith('/retry')
    ? Response.json({ code: 'FORBIDDEN' }, { status: 403 })
    : Response.json({ code: 'REPORT_NOT_READY', message: '报告尚未生成成功' }, { status: 409 });
  try {
    await assert.rejects(readReportFile('task-1', 1, 'markdown', 'token'), error => error instanceof ApiError && error.status === 409);
    await assert.rejects(retryReport('task-1', 1, 'pdf', 'token'), error => error instanceof ApiError && error.status === 403);
  } finally { globalThis.fetch = original; }
});
