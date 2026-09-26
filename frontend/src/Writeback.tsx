import { useEffect, useState } from 'react';
import { ApiError } from './api.ts';
import type { Role, Task } from './model.ts';
import { readWriteback, readWritebackTargets, submitWriteback, validateWritebackStatus, writebackVersion } from './writeback.ts';
import type { WritebackStatus, WritebackTarget } from './writeback.ts';

export function Writeback({ task, role, token, onExpired }: { task: Task; role: Role; token: string; onExpired: (message: string) => void }) {
  const confirmed = writebackVersion(task, role);
  const version = confirmed?.review_version;
  const [status, setStatus] = useState<WritebackStatus | null>(null);
  const [targets, setTargets] = useState<WritebackTarget[]>([]);
  const [target, setTarget] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!confirmed) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      setLoading(true);
      try {
        const result = validateWritebackStatus(await readWriteback(task.task_id, version!, token, controller.signal),
          task.task_id, confirmed!.document_version, version!);
        if (controller.signal.aborted) return;
        setStatus(result); setError(''); setUncertain(false);
        if (role === 'legal' && !result.mock_approval_id) {
          const options = await readWritebackTargets(token, controller.signal);
          if (controller.signal.aborted) return;
          setTargets(options.items);
          setTarget(current => options.items.some(item => item.id === current) ? current : options.items[0]?.id ?? '');
        } else { setTargets([]); setTarget(result.mock_approval_id ?? ''); }
        if (result.state === 'writing') timer = setTimeout(load, 5000);
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
        else setError((cause as Error).message);
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [task.task_id, version, confirmed?.document_version, role, token, revision]);

  if (!confirmed) return null;

  async function submit() {
    if (role !== 'legal' || !status || busy || uncertain || !target || !['not_written', 'failed'].includes(status.state)) return;
    if (status.state === 'not_written' && !window.confirm(`确认对文档 V${confirmed!.document_version} / 审查 V${version} 执行本地模拟回写？目标：${target}。`)) return;
    setBusy(true); setError('');
    try {
      const result = validateWritebackStatus(await submitWriteback(task.task_id, version!, target, token),
        task.task_id, confirmed!.document_version, version!);
      setStatus(result);
      setRevision(value => value + 1);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
      else {
        setError(cause instanceof ApiError && (cause.status === 0 || cause.status >= 500)
          ? '请求结果不确定，请先刷新状态核对，页面不会自动再次提交。'
          : (cause as Error).message);
        setUncertain(true);
      }
    } finally { setBusy(false); }
  }

  const labels = { not_written: '尚未回写', writing: '写入中', success: '模拟回写成功', failed: '模拟回写失败' };
  return <section className="panel writeback"><div className="section-head"><div><p className="eyebrow">仅本地保存 · 未连接真实审批平台</p><h2>模拟回写</h2></div><small>文档 V{confirmed.document_version} · 审查 V{version}</small></div>
    {confirmed.historical && <p className="notice">这是历史确认版本的模拟回写，不代表当前文档结果。</p>}
    {loading && !status && <p aria-busy="true">正在读取模拟回写状态…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {status && <><div className="writeback-summary"><div><small>状态</small><strong>{labels[status.state]}</strong></div><div><small>模拟审批单</small><strong>{status.mock_approval_id ?? '尚未绑定'}</strong></div>{status.comment_id && <div><small>本地评论 ID</small><strong>{status.comment_id}</strong></div>}</div>
      {role === 'legal' && status.state === 'not_written' && !status.mock_approval_id && <label className="writeback-target">选择已有模拟审批单<select value={target} onChange={event => setTarget(event.target.value)} disabled={busy || uncertain}>{targets.map(item => <option key={item.id} value={item.id}>{item.title} · {item.id}</option>)}</select></label>}
      {role === 'legal' && status.state === 'failed' && status.error && <p className="error">失败代码：{status.error}</p>}
      {role === 'admin' && status.state === 'failed' && status.error && <p className="error">故障代码：{status.error}</p>}
      {(role === 'legal' || role === 'admin') && status.attempts && <p className="muted">已登记尝试 {status.attempts.length} 次。{status.state === 'writing' ? '请求已登记，仍在写入中。' : ''}</p>}
      {status.state === 'success' && status.comment_id && status.markdown && role !== 'admin' && <details className="writeback-comment"><summary>查看本地模拟评论</summary><pre>{status.markdown}</pre></details>}
      <div className="actions">{role === 'legal' && (status.state === 'not_written' || status.state === 'failed') && <button className="primary" onClick={() => void submit()} disabled={busy || uncertain || loading || !target}>{busy ? '正在提交…' : status.state === 'failed' ? '重试模拟回写' : '执行模拟回写'}</button>}
        <button onClick={() => setRevision(value => value + 1)} disabled={busy || loading}>刷新回写状态</button></div>
    </>}
  </section>;
}
