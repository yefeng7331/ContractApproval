import { ApiError, request } from './api.ts';

export type ProcessingRecord = {
  stage: 'parse' | 'rules' | 'model' | 'report_markdown' | 'report_pdf';
  document_version: number; review_version: number | null; attempt: number | null;
  status: string; code: string | null; started_at: string | null; finished_at: string | null;
};
export type ProcessingPage = { task_id: string; total: number; items: ProcessingRecord[] };
export const PROCESSING_PAGE_SIZE = 20;

export async function readProcessingRecords(
  taskId: string, token: string, documentVersion: number | null, offset: number,
  signal?: AbortSignal,
): Promise<ProcessingPage> {
  const params = new URLSearchParams({ limit: String(PROCESSING_PAGE_SIZE), offset: String(offset) });
  if (documentVersion !== null) params.set('document_version', String(documentVersion));
  const page = await request<ProcessingPage>(`/tasks/${encodeURIComponent(taskId)}/processing-records?${params}`, token, signal);
  if (page.task_id !== taskId || !Number.isInteger(page.total) || page.total < 0 || !Array.isArray(page.items)
    || page.items.length > PROCESSING_PAGE_SIZE || page.items.some(item =>
      !Number.isInteger(item.document_version) || (documentVersion !== null && item.document_version !== documentVersion)
      || !['parse', 'rules', 'model', 'report_markdown', 'report_pdf'].includes(item.stage)
      || typeof item.status !== 'string')) {
    throw new ApiError(0, '处理记录与当前任务或版本不一致，请刷新后重试。');
  }
  return page;
}

export const stageNames: Record<ProcessingRecord['stage'], string> = {
  parse: '附件解析', rules: '演示规则', model: '模型建议',
  report_markdown: 'Markdown 报告', report_pdf: 'PDF 报告',
};

const statusNames: Record<string, string> = {
  pending: '待处理', running: '处理中', completed: '已完成', ready: '已就绪',
  blocked: '受阻', failed: '失败', superseded: '已由新版替代', lease_expired: '执行超时',
};
export function processingStatusName(status: string): string { return statusNames[status] ?? status; }
