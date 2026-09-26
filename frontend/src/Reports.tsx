import { useEffect, useState } from 'react';
import { ApiError } from './api.ts';
import type { Role, Task } from './model.ts';
import { confirmedReport, readReportFile, readReportStatus, retryReport } from './reports.ts';
import type { ReportFormat, ReportStatus } from './reports.ts';

const formats: { key: ReportFormat; label: string; extension: string }[] = [
  { key: 'markdown', label: 'Markdown', extension: 'md' },
  { key: 'pdf', label: 'PDF', extension: 'pdf' },
];

export function Reports({ task, role, token, onExpired }: { task: Task; role: Role; token: string; onExpired: (message: string) => void }) {
  const confirmed = confirmedReport(task);
  const version = confirmed?.review_version;
  const [status, setStatus] = useState<ReportStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<ReportFormat | null>(null);
  const [preview, setPreview] = useState<{ format: ReportFormat; content: string } | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => () => {
    if (preview?.format === 'pdf') URL.revokeObjectURL(preview.content);
  }, [preview]);

  useEffect(() => {
    if (!version) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      setLoading(true);
      try {
        const result = await readReportStatus(task.task_id, version!, token, controller.signal);
        if (controller.signal.aborted) return;
        if (result.review_version !== version || result.task_id !== task.task_id) throw new Error('报告版本与当前任务不一致，请刷新。');
        setStatus(result); setError('');
        if (result.reports.some(item => item.state === 'pending')) timer = setTimeout(load, 5000);
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
        else { setStatus(null); setError((cause as Error).message); }
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    setError('');
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [task.task_id, version, token, revision]);

  if (!confirmed || role === 'admin') return null;

  function handleError(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
    else setError((cause as Error).message);
  }

  async function open(format: ReportFormat, download: boolean) {
    if (busy) return;
    setBusy(format); setError('');
    try {
      const blob = await readReportFile(task.task_id, version!, format, token);
      if (download) {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `review-${task.task_id.slice(0, 8)}-v${version}.${format === 'pdf' ? 'pdf' : 'md'}`;
        document.body.append(anchor); anchor.click(); anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } else if (format === 'markdown') {
        setPreview({ format, content: await blob.text() });
      } else {
        setPreview({ format, content: URL.createObjectURL(blob) });
      }
    } catch (cause) { handleError(cause); }
    finally { setBusy(null); }
  }

  async function retry(format: ReportFormat) {
    if (busy) return;
    setBusy(format); setError('');
    try {
      const result = await retryReport(task.task_id, version!, format, token);
      setStatus(result);
      setRevision(value => value + 1);
    } catch (cause) { handleError(cause); }
    finally { setBusy(null); }
  }

  return <section className="panel reports"><div className="section-head"><div><p className="eyebrow">正式交付</p><h2>已确认审查报告</h2></div><small>文档 V{confirmed.document_version} · 审查 V{version}</small></div>
    {confirmed.historical && <p className="notice">这是历史确认版本的报告，不代表当前文档结论。</p>}
    <p className="muted">Markdown 与 PDF 分别生成。仅“已就绪”的格式可预览或下载。</p>
    {loading && !status && <p aria-busy="true">正在读取报告状态…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {status && <div className="report-list">{formats.map(format => {
      const report = status.reports.find(item => item.format === format.key);
      const state = report?.state ?? 'pending';
      return <div className="report-row" key={format.key}><div><strong>{format.label}</strong><small>{state === 'ready' ? `已就绪${report?.generated_at ? ` · ${new Date(report.generated_at).toLocaleString('zh-CN', { hour12: false })}` : ''}` : state === 'failed' ? role === 'legal' ? '生成失败' : '暂不可用，请联系法务' : '生成中'}</small>
        {role === 'legal' && state === 'failed' && report?.error && <small>错误代码：{report.error}</small>}</div><div className="actions">
          {state === 'ready' && <><button onClick={() => void open(format.key, false)} disabled={busy !== null}>预览</button><button onClick={() => void open(format.key, true)} disabled={busy !== null}>下载</button></>}
          {role === 'legal' && state === 'failed' && <button onClick={() => void retry(format.key)} disabled={busy !== null}>重试生成</button>}
        </div></div>;
    })}</div>}
    {status && <button onClick={() => setRevision(value => value + 1)} disabled={busy !== null || loading}>刷新报告状态</button>}
    {preview && <div className="report-preview"><div className="section-head"><h3>{preview.format === 'pdf' ? 'PDF 预览' : 'Markdown 原文预览'}</h3><button onClick={() => setPreview(null)}>关闭预览</button></div>
      {preview.format === 'pdf' ? <iframe title="已确认 PDF 报告预览" src={preview.content} /> : <pre>{preview.content}</pre>}</div>}
  </section>;
}
