import { useEffect, useState } from 'react';
import { ApiError, request } from './api.ts';
import { adopt, confirmReview, initialDecisions, saveReview, validateDecisions } from './review.ts';
import type { Decision, Review } from './review.ts';
import type { Task } from './model.ts';
import type { Advice, Snapshot } from './workbench.ts';

export function ReviewEditor({ task, snapshot, advice, token, onExpired, onChanged, onDirtyChange }: {
  task: Task; snapshot: Snapshot | null; advice: Advice | null; token: string;
  onExpired: (message: string) => void; onChanged: () => void; onDirtyChange: (dirty: boolean) => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [annotation, setAnnotation] = useState('');
  const [conclusion, setConclusion] = useState('');
  const [dirty, setDirty] = useState(false);
  const [conclusionDirty, setConclusionDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const result = await request<Review>(`/tasks/${encodeURIComponent(task.task_id)}/review?document_version=${task.document_version}`, token, controller.signal);
        if (controller.signal.aborted) return;
        if (result.document_version !== task.document_version || result.review_version !== task.review_version) throw new Error('审查版本与任务不一致，请刷新任务。');
        setReview(result); setDecisions(result.risks.map(item => ({ rule_id: item.rule_id, retained: item.retained, risk_level: item.risk_level, suggestion_source: item.suggestion_source, final_suggestion: item.final_suggestion, comment: item.comment })));
        setAnnotation(result.annotation); setConclusion(result.conclusion ?? '');
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 404 && task.review_version === null && snapshot) setDecisions(initialDecisions(snapshot));
        else if (failure instanceof ApiError && failure.status === 401) onExpired(failure.message);
        else { setLocked(true); setError((failure as Error).message); }
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [task.task_id, task.document_version, task.review_version, token, snapshot, advice]);
  useEffect(() => { onDirtyChange(dirty || conclusionDirty); return () => onDirtyChange(false); }, [dirty, conclusionDirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty && !conclusionDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, conclusionDirty]);
  const ready = task.machine_status === 'completed' && snapshot && advice && !loading && !locked;
  function update(ruleId: string, change: (decision: Decision) => Decision) {
    setDecisions(current => current.map(item => item.rule_id === ruleId ? change(item) : item));
    setDirty(true); setError(''); setMessage('');
  }
  function writeFailure(failure: unknown) {
    if (failure instanceof ApiError && failure.status === 401) { onExpired(failure.message); return; }
    if (failure instanceof ApiError && failure.status === 409) {
      setLocked(true); setError('状态或版本已变化，已停止提交。请刷新任务，核对新版本后重新编辑。'); return;
    }
    if (!(failure instanceof ApiError) || failure.status === 0 || failure.status >= 500) {
      setLocked(true); setError('提交结果不确定，请先刷新任务核对审查版本，不要重复提交。'); return;
    }
    setError((failure as Error).message);
  }
  async function save() {
    if (!ready || busy || locked) return;
    if (conclusionDirty && !window.confirm('保存新审查草稿会清除尚未提交的正式结论输入，确定继续？')) return;
    const problem = validateDecisions(decisions, snapshot, annotation);
    if (problem) { setError(problem); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const saved = await saveReview(task.task_id, task.document_version, review?.review_version ?? null, decisions, annotation, token);
      if (saved.document_version !== task.document_version) throw new Error('返回的文档版本不一致，请刷新任务。');
      setReview(saved); setDirty(false); setConclusion(''); setConclusionDirty(false); setMessage(`审查草稿 V${saved.review_version} 已保存，尚未正式确认。`); onChanged();
    } catch (failure) { writeFailure(failure); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!ready || busy || locked || dirty || !review || review.status !== 'in_review') return;
    if (!conclusion.trim()) { setError('请填写正式结论后确认。'); return; }
    if (conclusion.length > 10000) { setError('正式结论不能超过 10000 字。'); return; }
    if (!window.confirm(`确认文档 V${task.document_version} / 审查 V${review.review_version} 为正式结论？确认后该版本不可改写，并将进入报告生成。`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const saved = await confirmReview(task.task_id, task.document_version, review.review_version, conclusion, token);
      if (saved.document_version !== task.document_version || saved.review_version !== review.review_version || saved.status !== 'confirmed') throw new Error('确认回执版本不一致，请刷新任务。');
      setReview(saved); setConclusionDirty(false); setMessage(`审查 V${saved.review_version} 已由 ${saved.confirmed_by} 确认。`); onChanged();
    } catch (failure) { writeFailure(failure); }
    finally { setBusy(false); }
  }
  return <section className="panel review-editor"><div className="section-head"><h2>法务复核与确认</h2><small>文档 V{task.document_version} · {review ? `审查 V${review.review_version} / ${review.status === 'confirmed' ? '已确认' : '草稿'}` : '尚无审查版本'}</small></div>
    {task.machine_status !== 'completed' ? <p className="notice">机器草稿尚未完成，不能保存或确认审查。</p>
      : !snapshot || !advice ? <p className="notice">同版规则或模型结果暂不可用，不能创建可确认的审查版本。</p>
        : loading ? <p aria-busy="true">正在读取审查版本…</p> : <>
          <p className="muted">逐项决定是否保留风险及等级；规则、模型和人工建议分别记录。保存草稿不产生正式结论。</p>
          {decisions.map(decision => {
            const risk = snapshot.risks.find(item => item.rule_id === decision.rule_id);
            if (!risk) return null;
            const modelSuggestion = advice.suggestions.find(item => item.rule_id === decision.rule_id)?.suggestion;
            return <div className="review-decision" key={decision.rule_id}><h3>{risk.clause_type} · {risk.rule_id}</h3>
              <label className="check-row"><input type="checkbox" checked={decision.retained} disabled={busy || locked} onChange={event => update(decision.rule_id, current => ({ ...current, retained: event.target.checked }))} />保留此项风险</label>
              <label>法务等级<select value={decision.risk_level} disabled={busy || locked} onChange={event => update(decision.rule_id, current => ({ ...current, risk_level: event.target.value as Decision['risk_level'] }))}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
              <label>建议来源<select value={decision.suggestion_source} disabled={busy || locked} onChange={event => update(decision.rule_id, current => adopt(current, event.target.value as Decision['suggestion_source'], risk, advice))}><option value="rule">采纳规则建议</option><option value="model" disabled={!modelSuggestion}>采纳已有模型建议</option><option value="manual">人工编辑</option></select></label>
              <label>最终建议<textarea value={decision.final_suggestion} maxLength={10000} readOnly={decision.suggestion_source !== 'manual'} disabled={busy || locked} onChange={event => update(decision.rule_id, current => ({ ...current, final_suggestion: event.target.value }))} /></label>
              <label>单项批注<textarea value={decision.comment} maxLength={10000} disabled={busy || locked} onChange={event => update(decision.rule_id, current => ({ ...current, comment: event.target.value }))} /></label>
            </div>;
          })}
          <label>整体批注<textarea value={annotation} maxLength={20000} disabled={busy || locked} onChange={event => { setAnnotation(event.target.value); setDirty(true); setError(''); }} /></label>
          <div className="actions"><button className="primary" disabled={!ready || busy || locked} onClick={save}>{busy ? '正在提交…' : review?.status === 'confirmed' ? '另存新审查草稿' : '保存审查草稿'}</button>{(dirty || conclusionDirty) && <small>有未保存输入，离开页面前会提示。</small>}</div>
          {review?.status === 'in_review' && <div className="review-confirm"><h3>正式确认</h3><p className="muted">请核对已保存的草稿，再填写正式结论。确认后该审查版本不可改写。</p><label>正式结论<textarea value={conclusion} maxLength={10000} disabled={busy || locked} onChange={event => { setConclusion(event.target.value); setConclusionDirty(true); }} /></label><button disabled={busy || locked || dirty || !conclusion.trim()} onClick={confirm}>确认审查 V{review.review_version}</button></div>}
          {review?.status === 'confirmed' && <p className="notice">已由 {review.confirmed_by} 于 {review.confirmed_at} 确认；修改须另存新审查草稿。</p>}
        </>}
    {error && <p className="error" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
  </section>;
}
