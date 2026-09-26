import { request } from './api.ts';
import type { Advice, Risk, Snapshot } from './workbench.ts';

export type Decision = { rule_id: string; retained: boolean; risk_level: 'high' | 'medium' | 'low'; suggestion_source: 'rule' | 'model' | 'manual'; final_suggestion: string; comment: string };
export type Review = { task_id: string; document_version: number; review_version: number; status: 'in_review' | 'confirmed'; risks: Decision[]; annotation: string; risk_summary: string; conclusion: string | null; confirmed_by: string | null; confirmed_at: string | null };

export function initialDecisions(snapshot: Snapshot): Decision[] {
  return snapshot.risks.map(risk => ({
    rule_id: risk.rule_id, retained: true, risk_level: risk.risk_level as Decision['risk_level'],
    suggestion_source: 'rule', final_suggestion: risk.suggestion, comment: '',
  }));
}

export function adopt(decision: Decision, source: Decision['suggestion_source'], risk: Risk, advice: Advice | null): Decision {
  const suggestion = source === 'rule' ? risk.suggestion
    : source === 'model' ? advice?.suggestions.find(item => item.rule_id === risk.rule_id)?.suggestion ?? ''
      : decision.final_suggestion;
  return { ...decision, suggestion_source: source, final_suggestion: suggestion };
}

export function validateDecisions(decisions: Decision[], snapshot: Snapshot, annotation: string): string | null {
  if (annotation.length > 20000) return '整体批注不能超过 20000 字。';
  if (decisions.length !== snapshot.risks.length || new Set(decisions.map(item => item.rule_id)).size !== decisions.length || decisions.some(item => !snapshot.risks.some(risk => risk.rule_id === item.rule_id))) return '风险列表已变化，请重新读取。';
  for (const decision of decisions) {
    if (decision.final_suggestion.length > 10000 || decision.comment.length > 10000) return '单项建议或批注不能超过 10000 字。';
    if (decision.retained && !decision.final_suggestion.trim()) return `风险 ${decision.rule_id} 保留时必须提供最终建议。`;
  }
  return null;
}

export function saveReview(taskId: string, documentVersion: number, baseReviewVersion: number | null, decisions: Decision[], annotation: string, token: string, signal?: AbortSignal) {
  return request<Review>(`/tasks/${encodeURIComponent(taskId)}/review`, token, signal, {
    method: 'PUT', body: JSON.stringify({ document_version: documentVersion, base_review_version: baseReviewVersion, risks: decisions, annotation }),
  });
}

export function confirmReview(taskId: string, documentVersion: number, reviewVersion: number, conclusion: string, token: string, signal?: AbortSignal) {
  return request<Review>(`/tasks/${encodeURIComponent(taskId)}/confirm`, token, signal, {
    method: 'POST', body: JSON.stringify({ document_version: documentVersion, review_version: reviewVersion, conclusion: conclusion.trim() }),
  });
}
