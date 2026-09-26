export type Role = 'business' | 'legal' | 'admin';
export type Session = { access_token: string; expires_at: string; user: { username: string; role: Role } };
export type Task = {
  task_id: string; owner_username: string; source: string; created_at: string;
  document_version: number; review_version: number | null;
  machine_status: string; legal_status: string; writeback_status: string;
  blocked_code: string | null; blocked_reason: string | null; recovery_action: string | null;
  attempt_count: number;
  submission?: { department: string; applicant: string; filename: string | null };
  risk_level?: string | null;
  latest_confirmed_version?: { document_version: number; review_version: number } | null;
};
export const roles: Record<Role, string> = { business: '业务经办人', legal: '法务审查人', admin: '系统管理员' };
export const phases = { blocked: '处理受阻', processing: '机器处理中', review: '待法务复核', confirmed: '法务已确认' };
export type Phase = keyof typeof phases;
export const machineNames: Record<string, string> = { pending: '等待处理', parsing: '解析中', reviewing: '审查中', completed: '草稿完成', blocked: '处理受阻' };
export const legalNames: Record<string, string> = { pending: '待复核', in_review: '复核中', confirmed: '已确认' };
export const writebackNames: Record<string, string> = { not_written: '未回写', writing: '模拟回写中', success: '模拟成功', failed: '模拟失败' };
export function phase(task: Task): Phase {
  if (task.machine_status === 'blocked') return 'blocked';
  if (task.legal_status === 'confirmed') return 'confirmed';
  return task.machine_status === 'completed' ? 'review' : 'processing';
}
export function formalRisk(task: Task): string {
  if (phase(task) !== 'confirmed') return '尚无正式等级';
  // A null aggregate can mean no rule hits or all risks removed by legal review.
  // The summary endpoint cannot distinguish those cases; do not invent a verdict.
  return ({ high: '高风险', medium: '中风险', low: '低风险' } as Record<string, string>)[task.risk_level ?? ''] ?? '无分级结果（以确认意见为准）';
}
export function isActive(task: Task): boolean {
  return ['pending', 'parsing', 'reviewing'].includes(task.machine_status) || task.writeback_status === 'writing';
}
export function nextStep(task: Task, role: Role): string {
  if (task.machine_status === 'blocked') {
    if (task.recovery_action === 'replace_attachment') return role === 'business' ? '需换传可读取的附件' : '等待业务经办人换传附件';
    if (task.recovery_action === 'admin_retry') return role === 'admin' ? '可由管理员重试' : '联系管理员恢复处理';
    return '查看受阻原因与恢复指引';
  }
  if (phase(task) === 'processing') return '等待机器处理';
  if (phase(task) === 'review') return role === 'legal' ? '待核对原文并复核' : '等待法务确认';
  return role === 'admin' ? '已确认，关注回写状态' : '已形成正式确认版本';
}
