import { ApiError, request } from './api.ts';

export type Rect = { page: number; x: number; y: number; width: number; height: number };
export type Anchor = { document_version: number; start: number; end: number; quote: string; locatable: boolean; rects: Rect[]; reason?: string | null; clause_type?: string };
export type Field = { name: string; value: string | null; anchor: Anchor | null };
export type Document = { task_id: string; document_version: number; normalized_text: string; extraction_method: string; extraction_warning: string | null; preview_available: boolean; fields: Field[]; clauses: Anchor[]; missing_clause_types: string[] };
export type Risk = { rule_id: string; rule_version: string; risk_level: string; trigger_reason: string; suggestion: string; anchors: Anchor[]; clause_type: string };
export type Snapshot = { task_id: string; document_version: number; evidence_sha256: string; rule_version: string; machine_suggestion: string; risks: Risk[] };
export type Mapping = { task_id: string; document_version: number; normalized_text: string; paragraphs: Anchor[]; fields?: Field[]; clauses?: Anchor[]; preview_sha256?: string };
export type Advice = { document_version: number; evidence_sha256: string; rule_version: string; suggestions: { rule_id: string; suggestion: string }[] };

export async function loadEvidence(taskId: string, version: number, filename: string | null | undefined, token: string, signal: AbortSignal) {
  const base = `/tasks/${encodeURIComponent(taskId)}`;
  const query = `?document_version=${version}`;
  const notices: string[] = [];
  const document = await request<Document>(base + '/document' + query, token, signal);
  if (document.task_id !== taskId || document.document_version !== version) throw new Error('原文版本不一致，请返回大盘刷新。');
  async function optional<T>(path: string, label: string): Promise<T | null> {
    try { return await request<T>(base + path + query, token, signal); }
    catch (error) {
      if (signal.aborted || error instanceof ApiError && [401, 403].includes(error.status)) throw error;
      notices.push(`${label}暂不可用：${(error as Error).message}`);
      return null;
    }
  }
  const [snapshot, mapping, advice] = await Promise.all([
    optional<Snapshot>('/risks/snapshot', '已保存规则草稿'),
    filename?.toLowerCase().endsWith('.pdf') ? Promise.resolve(null) : optional<Mapping>('/document/preview-map', '预览定位'),
    optional<Advice>('/model-result', '已有模型建议'),
  ]);
  if (snapshot && (snapshot.task_id !== taskId || snapshot.document_version !== version)) throw new Error('风险与原文版本不一致，已停止展示。');
  if (advice && (!snapshot || advice.document_version !== version || advice.evidence_sha256 !== snapshot.evidence_sha256 || advice.rule_version !== snapshot.rule_version)) throw new Error('模型建议与规则证据不一致，已停止展示。');
  if (mapping && (mapping.task_id !== taskId || mapping.document_version !== version || mapping.normalized_text !== document.normalized_text)) throw new Error('预览映射与原文不一致，已停止展示。');
  return { document, snapshot, mapping, advice, notices };
}

// Converted previews locate whole paragraphs. A clause may cover several, but
// its exact boundaries and every intervening source span must still agree.
export function locations(anchor: Anchor, document: Document, mapping: Mapping | null): Rect[] {
  const text = Array.from(document.normalized_text);
  const matches = (item: Anchor) => Number.isInteger(item.start) && Number.isInteger(item.end) && item.start >= 0 && item.end > item.start && item.end <= text.length && item.document_version === document.document_version && text.slice(item.start, item.end).join('') === item.quote;
  if (!matches(anchor)) return [];
  if (mapping && (mapping.document_version !== document.document_version || mapping.task_id !== document.task_id || mapping.normalized_text !== document.normalized_text)) return [];
  const sources = mapping ? (mapping.paragraphs ?? []).filter(item => item.start < anchor.end && item.end > anchor.start) : [anchor];
  if (!sources.length || sources[0].start !== anchor.start || sources.at(-1)!.end !== anchor.end) return [];
  if (!sources.every((item, index) => matches(item) && item.locatable && item.rects?.length && (!index || item.start >= sources[index - 1].end && !text.slice(sources[index - 1].end, item.start).join('').trim()))) return [];
  const rects = sources.flatMap(item => item.rects);
  return rects.every(r => Number.isInteger(r.page) && r.page > 0 && [r.x, r.y, r.width, r.height].every(Number.isFinite) && r.x >= 0 && r.y >= 0 && r.width > 0 && r.height > 0 && r.x + r.width <= 1 && r.y + r.height <= 1) ? rects : [];
}

export type EvidenceMode = 'risk' | 'field' | 'clause';
export function evidenceMarks(document: Document, snapshot: Snapshot | null, mapping: Mapping | null, mode: EvidenceMode): { id: string; rect: Rect }[] {
  const entries: { id: string; anchors: Anchor[] }[] = mode === 'risk'
    ? (snapshot?.risks ?? []).map(risk => ({ id: risk.rule_id, anchors: risk.anchors }))
    : mode === 'field'
      ? document.fields.filter(field => field.anchor).map(field => ({ id: field.name, anchors: [field.anchor!] }))
      : document.clauses.map((clause, index) => ({ id: String(index), anchors: [clause] }));
  return entries.flatMap(entry => entry.anchors.flatMap(anchor => locations(anchor, document, mapping).map(rect => ({ id: entry.id, rect }))));
}
