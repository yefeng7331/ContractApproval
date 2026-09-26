import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from './api.ts';
import { acceptedFiles, replaceAttachment } from './intake.ts';
import type { Task } from './model.ts';

export function Replacement({ task, token, onSaved, onExpired }: {
  task: Task; token: string; onSaved: (task: Task) => void; onExpired: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [locked, setLocked] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current || locked) return;
    const data = new FormData(event.currentTarget);
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError('');
    try {
      const updated = await replaceAttachment(token, task, data.get('file') as File, controller.signal);
      if (!controller.signal.aborted) onSaved(updated);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) onExpired(error.message);
      else if (error instanceof ApiError && (error.status === 0 || error.status >= 500 || error.status === 409)) {
        setLocked(true);
        setError(error.status === 409 ? '任务状态或版本已变化。请返回大盘刷新并重新打开任务，核对后再操作。'
          : '提交结果尚未确认。请返回大盘刷新并核对文档版本，避免重复上传；不会自动重试。');
      } else setError((error as Error).message);
    } finally { active.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="panel intake"><h2>上传新版附件</h2>
    <p className="notice">基于当前文档 V{task.document_version} 创建 V{task.document_version + 1}，保留旧版证据与确认记录。新版重新等待处理、法务复核与模拟回写，旧版结论不代表新版。</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form onSubmit={submit} aria-busy={busy}><fieldset disabled={busy || locked}>
      <label>合成合同新版附件<input name="file" type="file" accept={acceptedFiles} required /></label>
      <small>单个附件不超过 25 MiB；当前查询验收模式不运行后台解析。</small>
      <label><span><input type="checkbox" required /> 我已确认本次创建新文档版本，旧版结论不会自动沿用。</span></label>
      <button className="primary">{busy ? '正在上传…' : '确认上传新版'}</button>
    </fieldset></form>
  </section>;
}
