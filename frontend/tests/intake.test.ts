import { test } from 'node:test';
import assert from 'node:assert/strict';
import { uploadContract, importPending, canReplace, replaceAttachment } from '../src/intake.ts';
import type { Task } from '../src/model.ts';

test('upload sends multipart without overriding browser boundary; validates before sending', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_url, init) => {
    calls++;
    assert.equal(new Headers(init?.headers).get('Content-Type'), null);
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer local-test');
    const body = init?.body as FormData;
    assert.equal(body.get('department'), 'Demo');
    assert.equal(body.get('applicant'), 'Tester');
    assert.equal((body.get('file') as File).name, 'test.PDF');
    return Response.json({ task_id: 'created', document_version: 1 });
  };
  try {
    assert.throws(() => uploadContract('local-test', new File(['bad'], 'bad.txt'), 'Demo', 'Tester'));
    assert.throws(() => uploadContract('local-test', new File([], 'empty.pdf'), 'Demo', 'Tester'));
    assert.throws(() => uploadContract('local-test', new File(['x'], 'x.pdf'), ' ', 'Tester'));
    const result = await uploadContract('local-test', new File(['%PDF'], 'test.PDF'), ' Demo ', 'Tester');
    assert.equal(result.task_id, 'created'); assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test('pending import preserves blocked receipt and never retries uncertain writes', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async (url, init) => {
      calls++; assert.equal(String(url), '/api/v1/mock-pending/demo/import'); assert.equal(init?.method, 'POST');
      return Response.json({ task_id: 'blocked-task', machine_status: 'blocked', recovery_action: 'admin_retry' });
    };
    assert.equal((await importPending('local-test', 'demo')).machine_status, 'blocked');
    globalThis.fetch = async () => { calls++; throw new TypeError('connection lost'); };
    await assert.rejects(importPending('local-test', 'demo'));
    assert.equal(calls, 2);
  } finally { globalThis.fetch = original; }
});

test('replacement sends the displayed base version and surfaces conflicts without retry', async () => {
  const task = { task_id: 'versioned', document_version: 3, machine_status: 'blocked', recovery_action: 'replace_attachment', legal_status: 'pending' } as Task;
  assert.equal(canReplace(task), true);
  assert.equal(canReplace({ ...task, recovery_action: 'admin_retry' }), false);
  assert.equal(canReplace({ ...task, machine_status: 'completed', legal_status: 'confirmed' }), true);
  assert.equal(canReplace({ ...task, machine_status: 'reviewing' }), false);
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async (url, init) => {
      calls++;
      assert.equal(String(url), '/api/v1/tasks/versioned/documents');
      assert.equal((init?.body as FormData).get('base_document_version'), '3');
      assert.equal(new Headers(init?.headers).get('Content-Type'), null);
      return Response.json({ message: 'version conflict' }, { status: 409 });
    };
    await assert.rejects(replaceAttachment('local-test', task, new File(['%PDF'], 'new.pdf')), /version conflict/);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});
