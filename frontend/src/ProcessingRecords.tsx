import { useEffect, useState } from 'react';
import { ApiError } from './api.ts';
import { PROCESSING_PAGE_SIZE, processingStatusName, readProcessingRecords, stageNames } from './processing.ts';
import type { ProcessingPage } from './processing.ts';

const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未记录';

export function ProcessingRecords({ taskId, documentVersion, token, refresh, onExpired }: {
  taskId: string; documentVersion: number; token: string; refresh: number;
  onExpired: (message: string) => void;
}) {
  const [version, setVersion] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ProcessingPage | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setPage(null);
    void readProcessingRecords(taskId, token, version, offset, controller.signal).then(result => {
      if (!controller.signal.aborted) setPage(result);
    }).catch(cause => {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
      else setError((cause as Error).message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [taskId, token, version, offset, refresh, reload]);

  return <section className="panel processing-records"><div className="section-head"><div><p className="eyebrow">系统管理 / 处理记录</p><h2>任务处理记录</h2></div><label>文档版本<select value={version ?? 'all'} onChange={event => { setVersion(event.target.value === 'all' ? null : Number(event.target.value)); setOffset(0); }}><option value="all">全部版本</option>{Array.from({ length: documentVersion }, (_, index) => index + 1).map(value => <option key={value} value={value}>V{value}</option>)}</select></label></div>
    <p className="muted">按文档版本与处理阶段查看作业结果；模型请求、合同原文和报告正文不在此展示。</p>
    {loading && <p aria-busy="true">正在读取处理记录…</p>}
    {error && <p className="error" role="alert">{error} <button onClick={() => setReload(value => value + 1)}>重新读取</button></p>}
    {!loading && page && (page.items.length ? <div className="table-wrap"><table><thead><tr><th>阶段</th><th>版本</th><th>尝试</th><th>结果</th><th>故障代码</th><th>开始</th><th>结束</th></tr></thead><tbody>{page.items.map((item, index) => <tr key={`${item.stage}:${item.document_version}:${item.review_version ?? 0}:${item.attempt ?? 0}:${index}`}><td>{stageNames[item.stage]}</td><td>文档 V{item.document_version}{item.review_version && <small>审查 V{item.review_version}</small>}</td><td>{item.attempt ?? '—'}</td><td>{processingStatusName(item.status)}</td><td>{item.code ?? '—'}</td><td>{date(item.started_at)}</td><td>{date(item.finished_at)}</td></tr>)}</tbody></table></div> : <p className="muted">该范围暂无处理记录。</p>)}
    {!loading && page && <div className="pagination"><small>共 {page.total} 条 · 第 {Math.floor(offset / PROCESSING_PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(page.total / PROCESSING_PAGE_SIZE))} 页</small><div className="actions"><button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - PROCESSING_PAGE_SIZE))}>上一页</button><button disabled={offset + PROCESSING_PAGE_SIZE >= page.total} onClick={() => setOffset(value => value + PROCESSING_PAGE_SIZE)}>下一页</button></div></div>}
  </section>;
}
