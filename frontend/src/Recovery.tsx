import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api.ts';
import type { Task } from './model.ts';
import { canAdminRetry, readAttachmentHistory, readRecoveryTask, recoveryInstruction, retryBlockedTask } from './recovery.ts';
import type { AttachmentHistory } from './recovery.ts';

const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';

export function Recovery({ task, token, onChanged, onExpired }: {
  task: Task; token: string; onChanged: (task: Task) => void; onExpired: (message: string) => void;
}) {
  const [history, setHistory] = useState<AttachmentHistory | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [message, setMessage] = useState('');
  const pending = useRef(false);

  useEffect(() => {
    if (task.source !== 'mock_pending') return;
    const controller = new AbortController();
    void readAttachmentHistory(task, token, controller.signal).then(setHistory).catch(error => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) onExpired(error.message);
      else setHistoryError((error as Error).message);
    });
    return () => controller.abort();
  }, [task.task_id, task.document_version, task.source, token]);

  async function retry() {
    if (pending.current || locked || !canAdminRetry(task, 'admin')) return;
    pending.current = true; setBusy(true); setMessage('');
    try {
      const updated = await retryBlockedTask(task, 'admin', token);
      setMessage(updated.machine_status === 'blocked' ? '重试已执行，但任务仍受阻；请查看新故障原因。' : '重试已受理，请查看更新后的任务状态。');
      onChanged(updated);
      if (updated.source === 'mock_pending') {
        try { setHistory(await readAttachmentHistory(updated, token)); setHistoryError(''); }
        catch (error) {
          if (error instanceof ApiError && error.status === 401) onExpired(error.message);
          else setHistoryError('重试已执行，但尝试历史读取失败；请稍后重新读取任务。');
        }
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired(error.message);
      else {
        setLocked(true);
        setMessage(error instanceof ApiError && error.status === 409
          ? '任务状态或版本已变化。请刷新任务并重新核对后操作。'
          : '重试结果尚未确认。请刷新任务并核对状态及尝试历史，避免重复提交。');
      }
    } finally { pending.current = false; setBusy(false); }
  }

  async function recheck() {
    if (pending.current) return;
    pending.current = true; setBusy(true);
    try {
      const current = await readRecoveryTask(task.task_id, token);
      if (current.source === 'mock_pending') setHistory(await readAttachmentHistory(current, token));
      setLocked(false); setMessage('任务已重新读取，请核对当前状态后再操作。');
      onChanged(current);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired(error.message);
      else setMessage('任务状态尚未重新确认，请稍后再次读取；当前不会重复提交。');
    } finally { pending.current = false; setBusy(false); }
  }

  if (task.machine_status !== 'blocked' && task.source !== 'mock_pending') return null;
  return <section className="panel recovery"><div className="section-head"><div><p className="eyebrow">系统管理 / 受阻恢复</p><h2>处理与尝试记录</h2></div><span className="pill">文档 V{task.document_version}</span></div>
    {task.machine_status === 'blocked' && <><p className="notice">{recoveryInstruction(task)}</p><dl><dt>故障代码</dt><dd>{task.blocked_code ?? '未提供'}</dd><dt>受阻原因</dt><dd>{task.blocked_reason ?? '未提供'}</dd><dt>当前处理阶段尝试次数</dt><dd>{task.attempt_count}</dd></dl></>}
    {canAdminRetry(task, 'admin') && <div className="actions"><button className="primary" disabled={busy || locked} onClick={() => void retry()}>{busy ? '正在重试…' : `重试文档 V${task.document_version}`}</button><small>每次点击仅提交一次；状态不确定时先刷新任务。</small></div>}
    {message && <p className={locked ? 'error' : 'notice'} role={locked ? 'alert' : 'status'}>{message}</p>}
    {locked && <button disabled={busy} onClick={() => void recheck()}>{busy ? '正在重新读取…' : '重新读取任务及尝试历史'}</button>}
    {task.source === 'mock_pending' && <div className="recovery-history"><h3>附件获取尝试历史</h3><p className="muted">仅展示本任务的尝试序号、状态与故障代码；当前处理阶段次数与附件累计次数分别统计。</p>
      {historyError && <p className="error" role="alert">{historyError}</p>}
      {!history && !historyError && <p aria-busy="true">正在读取尝试历史…</p>}
      {history && (history.attempts.length ? <div className="table-wrap"><table><thead><tr><th>次数</th><th>状态</th><th>故障代码</th><th>开始</th><th>结束</th></tr></thead><tbody>{history.attempts.map(item => <tr key={item.attempt}><td>{item.attempt}</td><td>{item.state}</td><td>{item.error_code ?? '—'}</td><td>{date(item.started_at)}</td><td>{date(item.finished_at)}</td></tr>)}</tbody></table></div> : <p className="muted">暂无附件获取尝试记录。</p>)}
    </div>}
  </section>;
}
