import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, request } from './api.ts';
import { acceptedFiles, importPending, uploadContract } from './intake.ts';
import type { PendingItem } from './intake.ts';
import type { Task } from './model.ts';

export function Intake({ token, onCreated, onExpired }: { token: string; onCreated: (task: Task) => void; onExpired: (message: string) => void }) {
  const [items, setItems] = useState<PendingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setListError('');
    request<{ items: PendingItem[] }>('/mock-pending', token, controller.signal)
      .then(result => { if (!controller.signal.aborted) setItems(result.items); })
      .catch(error => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) onExpired(error.message);
        else setListError(error.message);
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refresh]);

  async function submit(action: (signal: AbortSignal) => Promise<Task>) {
    if (active.current || uncertain) return;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError('');
    try {
      const task = await action(controller.signal);
      if (!controller.signal.aborted) onCreated(task);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) onExpired(error.message);
      else if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        // A lost response does not prove the server rolled back. Never auto-retry a write.
        setUncertain(true); setError('提交结果尚未确认。请返回任务大盘刷新，核对是否已有新任务后再决定是否重新提交，避免重复创建。');
      } else setError((error as Error).message);
    } finally { active.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void submit(signal => uploadContract(token, data.get('file') as File, String(data.get('department')), String(data.get('applicant')), signal));
  }
  return <section className="intake">
    <p className="notice">仅上传合成演示合同。接收成功表示任务已登记，不代表解析、审查或法务确认完成。当前查询验收启动模式不运行后台解析，新任务会保持待处理。</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="intake-grid"><section className="panel"><p className="eyebrow">本地附件</p><h2>上传合同</h2><p className="muted">保留来源与申请信息，从文档 V1 开始审查。</p>
      <form onSubmit={upload} aria-busy={busy}><fieldset disabled={busy || uncertain}>
        <label>送审部门<input name="department" required maxLength={120} /></label>
        <label>申请人<input name="applicant" required maxLength={120} /></label>
        <label>合成合同附件<input name="file" type="file" required accept={acceptedFiles} /></label>
        <small>DOCX、PDF、PNG、JPEG、TIFF · 单个附件不超过 25 MiB。格式与内容由后端再次校验。</small>
        <button className="primary">{busy ? '正在提交…' : '上传并建立任务'}</button>
      </fieldset></form>
    </section><section className="panel"><p className="eyebrow">模拟审批来源</p><h2>导入模拟待办</h2><p className="muted">使用本地合成附件与申请信息，不连接真实审批平台。每次导入都会新建任务。</p>
      {loading ? <p aria-busy="true">正在读取模拟待办…</p> : listError ? <div className="error" role="alert">{listError}<button disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新读取待办</button></div>
        : !items.length ? <p className="empty">暂无模拟待办</p> : items.map(item => <article className="pending-item" key={item.id}><h3>{item.title}</h3><p className="muted">{item.department} · {item.applicant}</p><p className="muted">{item.attachment_filename}</p><small>待办编号：{item.id}</small><button disabled={busy || uncertain} onClick={() => void submit(signal => importPending(token, item.id, signal))}>{busy ? '正在提交…' : '导入并建立任务'}</button></article>)}
    </section></div>
  </section>;
}
