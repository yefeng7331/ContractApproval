import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evidenceMarks, loadEvidence, locations } from '../src/workbench.ts';
import type { Anchor, Document, Mapping } from '../src/workbench.ts';

test('only same-version exact Unicode evidence permits finite normalized highlights', () => {
  const anchor: Anchor = { document_version: 2, start: 1, end: 3, quote: '合同', locatable: true, rects: [{ page: 1, x: 0.1, y: 0.2, width: 0.3, height: 0.1 }] };
  const document = { task_id: 'one', document_version: 2, normalized_text: '😀合同正文' } as Document;
  assert.equal(locations(anchor, document, null).length, 1);
  assert.deepEqual(locations({ ...anchor, start: -4 }, document, null), []);
  assert.deepEqual(locations({ ...anchor, start: 1.5 }, document, null), []);
  assert.deepEqual(locations({ ...anchor, end: 99, quote: '合同正文' }, document, null), []);
  assert.deepEqual(locations({ ...anchor, document_version: 1 }, document, null), []);
  assert.deepEqual(locations({ ...anchor, quote: 'wrong' }, document, null), []);
  assert.deepEqual(locations({ ...anchor, locatable: false }, document, null), []);
  assert.deepEqual(locations({ ...anchor, rects: [{ ...anchor.rects[0], x: NaN }] }, document, null), []);
  assert.deepEqual(locations({ ...anchor, rects: [{ ...anchor.rects[0], width: 1 }] }, document, null), []);
  const mapping: Mapping = { task_id: 'one', document_version: 2, normalized_text: document.normalized_text, paragraphs: [anchor] };
  assert.equal(locations({ ...anchor, locatable: false, rects: [] }, document, mapping).length, 1);
  assert.deepEqual(locations(anchor, document, { ...mapping, task_id: 'other' }), []);
  assert.deepEqual(locations(anchor, document, { ...mapping, paragraphs: [{ ...anchor, end: 4 }] }), []);
});

test('converted paragraph mappings cover complete multi-page clauses without guessing gaps', () => {
  const document = { task_id: 'one', document_version: 1, normalized_text: '付款：\n签约即付全款' } as Document;
  const rect = { page: 1, x: .1, y: .2, width: .3, height: .1 };
  const first: Anchor = { document_version: 1, start: 0, end: 3, quote: '付款：', locatable: true, rects: [rect] };
  const last: Anchor = { ...first, start: 4, end: 10, quote: '签约即付全款', rects: [{ ...rect, page: 2 }] };
  const clause: Anchor = { ...first, end: 10, quote: document.normalized_text, locatable: false, rects: [] };
  const mapping: Mapping = { task_id: 'one', document_version: 1, normalized_text: document.normalized_text, paragraphs: [first, last] };
  assert.deepEqual(locations(clause, document, mapping).map(rect => rect.page), [1, 2]);
  assert.deepEqual(locations(clause, document, { ...mapping, paragraphs: [last, first] }), []);
  assert.deepEqual(locations(clause, document, { ...mapping, paragraphs: [first] }), []);
  assert.deepEqual(locations(clause, document, { ...mapping, paragraphs: [first, { ...last, start: 5, quote: '约即付全款' }] }), []);
  assert.deepEqual(locations(clause, document, { ...mapping, paragraphs: [first, { ...last, locatable: false }] }), []);
});

test('workbench loads protected same-version evidence and keeps unfinished advice visible as a limitation', async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  const document = { task_id: 'one', document_version: 2, normalized_text: '合同', preview_available: true };
  const snapshot = { task_id: 'one', document_version: 2, evidence_sha256: 'evidence', rule_version: 'demo-v2', risks: [] };
  const mapping = { task_id: 'one', document_version: 2, normalized_text: '合同', paragraphs: [] };
  try {
    globalThis.fetch = async (url, init) => {
      paths.push(String(url));
      assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer test-token');
      if (String(url).includes('/document/preview-map')) return Response.json(mapping);
      if (String(url).includes('/risks/snapshot')) return Response.json(snapshot);
      if (String(url).includes('/model-result')) return Response.json({ message: '模型结果未就绪' }, { status: 409 });
      return Response.json(document);
    };
    const result = await loadEvidence('one', 2, 'contract.docx', 'test-token', new AbortController().signal);
    assert.equal(result.document.document_version, 2);
    assert.equal(result.snapshot?.evidence_sha256, 'evidence');
    assert.equal(result.mapping?.normalized_text, '合同');
    assert.equal(result.advice, null);
    assert.match(result.notices.join(' '), /模型结果未就绪/);
    assert.equal(paths.length, 4);
    assert.ok(paths.every(path => path.includes('document_version=2')));
  } finally { globalThis.fetch = original; }
});

test('workbench refuses permission errors and mixed-version risk evidence', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ message: '无权访问' }, { status: 403 });
    await assert.rejects(loadEvidence('one', 2, 'contract.pdf', 'test-token', new AbortController().signal), /无权/);
    globalThis.fetch = async url => Response.json(String(url).includes('/document')
      ? { task_id: 'one', document_version: 2, normalized_text: '合同' }
      : { task_id: 'one', document_version: 1, risks: [] });
    await assert.rejects(loadEvidence('one', 2, 'contract.pdf', 'test-token', new AbortController().signal), /风险与原文版本不一致/);
  } finally { globalThis.fetch = original; }
});

test('risk, field and clause modes expose only their own verified PDF locations', () => {
  const anchor: Anchor = { document_version: 2, start: 0, end: 2, quote: '合同', locatable: true, rects: [{ page: 1, x: .1, y: .2, width: .3, height: .1 }] };
  const stale = { ...anchor, document_version: 1 };
  const document = { task_id: 'one', document_version: 2, normalized_text: '合同', fields: [{ name: '合同名称', value: '合同', anchor }], clauses: [anchor, stale] } as Document;
  const snapshot = { task_id: 'one', document_version: 2, risks: [{ rule_id: 'R1', anchors: [anchor, stale] }] } as Parameters<typeof evidenceMarks>[1];
  assert.deepEqual(evidenceMarks(document, snapshot, null, 'risk').map(mark => mark.id), ['R1']);
  assert.deepEqual(evidenceMarks(document, snapshot, null, 'field').map(mark => mark.id), ['合同名称']);
  assert.deepEqual(evidenceMarks(document, snapshot, null, 'clause').map(mark => mark.id), ['0']);
  assert.deepEqual(evidenceMarks({ ...document, fields: [{ name: '合同名称', value: '合同', anchor: stale }] }, snapshot, null, 'field'), []);
});

test('missing optional draft leaves original readable, but permission denial stops the workbench', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async url => String(url).includes('/document')
      ? Response.json({ task_id: 'one', document_version: 2, normalized_text: '合同' })
      : Response.json({}, { status: 404 });
    const result = await loadEvidence('one', 2, 'contract.pdf', 'test-token', new AbortController().signal);
    assert.equal(result.snapshot, null);
    assert.equal(result.advice, null);
    assert.equal(result.notices.length, 2);
    globalThis.fetch = async url => String(url).includes('/document')
      ? Response.json({ task_id: 'one', document_version: 2, normalized_text: '合同' })
      : Response.json({}, { status: 403 });
    await assert.rejects(loadEvidence('one', 2, 'contract.pdf', 'test-token', new AbortController().signal), /无权/);
  } finally { globalThis.fetch = original; }
});
