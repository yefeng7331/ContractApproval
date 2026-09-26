import { ApiError, request } from './api.ts';
import type { Role, Task } from './model.ts';

export type AttachmentAttempt = {
  attempt: number; state: string; error_code: string | null;
  started_at: string; finished_at: string | null; actor_user_id: string;
};
export type AttachmentHistory = { task_id: string; document_version: number; attempts: AttachmentAttempt[] };

export function canAdminRetry(task: Task, role: Role): boolean {
  return role === 'admin' && task.machine_status === 'blocked' && task.recovery_action === 'admin_retry';
}

export function recoveryInstruction(task: Task): string {
  if (task.recovery_action === 'replace_attachment') return '需由业务经办人更换可读取附件；管理员不能重试此类受阻。';
  if (task.recovery_action === 'budget_decision') return '等待预算决策；管理员不能通过重试跳过预算约束。';
  if (task.recovery_action === 'admin_retry') return '可按当前文档版本发起一次管理员重试。';
  return '请核对故障原因与恢复指引；当前无管理员重试操作。';
}

export async function readAttachmentHistory(task: Task, token: string, signal?: AbortSignal): Promise<AttachmentHistory> {
  const history = await request<AttachmentHistory>(`/tasks/${encodeURIComponent(task.task_id)}/attachment-attempts`, token, signal);
  if (history.task_id !== task.task_id || history.document_version !== task.document_version || !Array.isArray(history.attempts))
    throw new ApiError(0, '附件尝试历史与当前任务版本不一致，请刷新任务。');
  return history;
}

export async function readRecoveryTask(taskId: string, token: string): Promise<Task> {
  const current = await request<Task>(`/tasks/${encodeURIComponent(taskId)}`, token);
  if (current.task_id !== taskId) throw new ApiError(0, '读取的任务与当前任务不一致，请重新打开任务。');
  return current;
}

export async function retryBlockedTask(task: Task, role: Role, token: string): Promise<Task> {
  if (!canAdminRetry(task, role)) throw new ApiError(403, '当前角色或任务状态不允许管理员重试。');
  const updated = await request<Task>(`/tasks/${encodeURIComponent(task.task_id)}/retry`, token, undefined,
    { method: 'POST', body: JSON.stringify({ document_version: task.document_version }) });
  if (updated.task_id !== task.task_id || updated.document_version !== task.document_version)
    throw new ApiError(0, '重试响应与当前任务版本不一致，请刷新任务核对。');
  return updated;
}
