import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../src/api.ts';
import { PROCESSING_PAGE_SIZE, processingStatusName, readProcessingRecords, stageNames } from '../src/processing.ts';

const item = { stage: 'model', document_version: 2, review_version: null, attempt: null,
  status: 'completed', code: 'MODEL_VALID', started_at: '2026-09-26T00:00:00Z', finished_at: '2026-09-26T00:00:01Z' };

test('admin reads versioned processing records with bearer and pagination', async () => {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init! });
    return Response.json({ task_id: 'task/1', total: 21, items: [item] });
  };
  try {
    const result = await readProcessingRecords('task/1', 'admin-token', 2, PROCESSING_PAGE_SIZE);
    assert.equal(result.items[0].stage, 'model');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/v1/tasks/task%2F1/processing-records?limit=20&offset=20&document_version=2');
    assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer admin-token');
    assert.equal(stageNames.model, '模型建议');
    assert.equal(processingStatusName('completed'), '已完成');
  } finally { globalThis.fetch = original; }
});

test('processing records reject wrong task and version', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ task_id: 'other', total: 1, items: [item] });
    await assert.rejects(readProcessingRecords('task/1', 'token', 2, 0), error => error instanceof ApiError && error.status === 0);
    globalThis.fetch = async () => Response.json({ task_id: 'task/1', total: 1, items: [item] });
    await assert.rejects(readProcessingRecords('task/1', 'token', 1, 0), error => error instanceof ApiError && error.status === 0);
  } finally { globalThis.fetch = original; }
});

test('processing records propagate role and session rejection', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ detail: 'forbidden' }, { status: 403 });
    await assert.rejects(readProcessingRecords('task/1', 'business-token', null, 0), error => error instanceof ApiError && error.status === 403);
    globalThis.fetch = async () => Response.json({ detail: 'unauthorized' }, { status: 401 });
    await assert.rejects(readProcessingRecords('task/1', 'expired-token', null, 0), error => error instanceof ApiError && error.status === 401);
  } finally { globalThis.fetch = original; }
});
