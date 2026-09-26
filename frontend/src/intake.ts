import { request } from './api.ts';
import type { Task } from './model.ts';

export const acceptedFiles = '.docx,.pdf,.png,.jpg,.jpeg,.tif,.tiff';
export type PendingItem = { id: string; title: string; department: string; applicant: string; attachment_filename: string; synthetic: boolean };

export function canReplace(task: Task) {
  return (task.machine_status === 'blocked' && task.recovery_action === 'replace_attachment')
    || (task.machine_status === 'completed' && task.legal_status === 'confirmed');
}

export function replaceAttachment(token: string, task: Task, file: File, signal?: AbortSignal) {
  validateAttachment(file);
  const body = new FormData();
  body.set('file', file); body.set('base_document_version', String(task.document_version));
  return request<Task>(`/tasks/${encodeURIComponent(task.task_id)}/documents`, token, signal, { method: 'POST', body });
}

export function validateAttachment(file: File) {
  if (!file.size) throw new Error('请选择非空附件。');
  if (file.size > 25 * 1024 * 1024) throw new Error('附件不能超过 25 MiB。');
  if (!acceptedFiles.split(',').some(extension => file.name.toLowerCase().endsWith(extension))) throw new Error('仅接受 DOCX、PDF、PNG、JPEG 或 TIFF。');
}

export function uploadContract(token: string, file: File, department: string, applicant: string, signal?: AbortSignal) {
  if (!department.trim() || !applicant.trim() || department.trim().length > 120 || applicant.trim().length > 120) {
    throw new Error('部门和申请人须为 1 至 120 个字符。');
  }
  validateAttachment(file);
  const body = new FormData();
  body.set('file', file); body.set('department', department.trim()); body.set('applicant', applicant.trim());
  return request<Task>('/tasks', token, signal, { method: 'POST', body });
}

export function importPending(token: string, id: string, signal?: AbortSignal) {
  return request<Task>(`/mock-pending/${encodeURIComponent(id)}/import`, token, signal, { method: 'POST' });
}
