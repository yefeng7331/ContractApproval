import { ApiError, fetchResponse, request } from './api.ts';
import type { Task } from './model.ts';

export type ReportFormat = 'markdown' | 'pdf';
export type ReportRecord = { format: ReportFormat; state: 'pending' | 'ready' | 'failed'; attempts: number; generated_at: string | null; error?: string | null };
export type ReportStatus = { task_id: string; review_version: number; reports: ReportRecord[] };

export function confirmedReport(task: Task) {
  const version = task.latest_confirmed_version;
  return version ? { ...version, historical: version.document_version !== task.document_version || version.review_version !== task.review_version } : null;
}

export function reportPath(taskId: string, version: number, format?: ReportFormat) {
  const base = `/tasks/${encodeURIComponent(taskId)}/reports/`;
  return format ? `${base}${format}?review_version=${version}` : `${base}status?review_version=${version}`;
}

export function readReportStatus(taskId: string, version: number, token: string, signal?: AbortSignal) {
  return request<ReportStatus>(reportPath(taskId, version), token, signal);
}

export async function readReportFile(taskId: string, version: number, format: ReportFormat, token: string, signal?: AbortSignal) {
  const response = await fetchResponse(reportPath(taskId, version, format), token, signal);
  const blob = await response.blob();
  if (format === 'pdf' && blob.type && !blob.type.startsWith('application/pdf')) throw new ApiError(0, '服务返回的报告格式不正确。');
  return blob;
}

export function retryReport(taskId: string, version: number, format: ReportFormat, token: string) {
  return request<ReportStatus>(`/tasks/${encodeURIComponent(taskId)}/reports/${format}/retry`, token, undefined,
    { method: 'POST', body: JSON.stringify({ review_version: version }) });
}
