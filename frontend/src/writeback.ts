import { request } from './api.ts';
import type { Role, Task } from './model.ts';

export type WritebackState = 'not_written' | 'writing' | 'success' | 'failed';
export type WritebackStatus = {
  task_id: string; document_version: number; review_version: number; simulated: true;
  mock_approval_id: string | null; state: WritebackState;
  comment_id: string | null; completed_at: string | null;
  markdown?: string | null; error?: string | null;
  attempts?: { id: string; state: string; requested_at: string; finished_at: string | null; error: string | null }[];
};
export type WritebackTarget = { id: string; title: string; synthetic: true };

export function validateWritebackStatus(result: WritebackStatus, taskId: string, documentVersion: number, reviewVersion: number) {
  if (result.simulated !== true || result.task_id !== taskId || result.document_version !== documentVersion ||
      result.review_version !== reviewVersion || (result.state === 'success' && !result.comment_id))
    throw new Error('模拟回写结果与确认版本不一致或缺少评论 ID，请刷新状态核对。');
  return result;
}

export function writebackVersion(task: Task, role: Role) {
  const confirmed = task.latest_confirmed_version;
  if (role === 'admin') return task.legal_status === 'confirmed' && task.review_version
    ? { document_version: task.document_version, review_version: task.review_version, historical: false } : null;
  return confirmed ? { ...confirmed,
    historical: confirmed.document_version !== task.document_version || confirmed.review_version !== task.review_version } : null;
}

export function readWriteback(taskId: string, version: number, token: string, signal?: AbortSignal) {
  return request<WritebackStatus>(`/tasks/${encodeURIComponent(taskId)}/mock-writeback?review_version=${version}`, token, signal);
}

export function readWritebackTargets(token: string, signal?: AbortSignal) {
  return request<{ items: WritebackTarget[] }>('/mock-writeback-targets', token, signal);
}

export function submitWriteback(taskId: string, version: number, target: string, token: string) {
  return request<WritebackStatus>(`/tasks/${encodeURIComponent(taskId)}/mock-writeback`, token, undefined,
    { method: 'POST', body: JSON.stringify({ review_version: version, mock_approval_id: target }) });
}
