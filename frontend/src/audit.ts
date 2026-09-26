import { ApiError, request } from './api.ts';

export type AuditEvent = {
  id: number; action: string; document_version: number; created_at: string;
  actor_username: string; actor_role: string;
};
export type AuditPage = { task_id: string; total: number; items: AuditEvent[] };
export const AUDIT_PAGE_SIZE = 20;

export async function readAuditEvents(
  taskId: string, token: string, documentVersion: number | null, offset: number,
  signal?: AbortSignal,
): Promise<AuditPage> {
  const params = new URLSearchParams({ limit: String(AUDIT_PAGE_SIZE), offset: String(offset) });
  if (documentVersion !== null) params.set('document_version', String(documentVersion));
  const page = await request<AuditPage>(`/tasks/${encodeURIComponent(taskId)}/audit-events?${params}`, token, signal);
  if (page.task_id !== taskId || !Number.isInteger(page.total) || page.total < 0 || !Array.isArray(page.items)
    || page.items.length > AUDIT_PAGE_SIZE || page.items.some(item => !Number.isInteger(item.id)
      || !Number.isInteger(item.document_version) || (documentVersion !== null && item.document_version !== documentVersion))) {
    throw new ApiError(0, '操作记录与当前任务或版本不一致，请刷新后重试。');
  }
  return page;
}

const actionNames: Record<string, string> = {
  task_created: '任务建立', document_version_created: '上传新文档版本',
  mock_pending_imported: '模拟待办附件导入', attachment_fetch_started: '开始获取待办附件',
  attachment_fetch_timeout: '待办附件获取超时',
  rule_retry_requested: '请求重试规则处理', ocr_retry_requested: '请求重试识别',
  review_saved: '保存法务草稿', review_confirmed: '确认法务结论',
  mock_writeback_requested: '发起模拟回写', mock_writeback_succeeded: '模拟回写成功',
  mock_writeback_failed: '模拟回写失败',
};
export function auditActionName(action: string): string { return actionNames[action] ?? action; }
