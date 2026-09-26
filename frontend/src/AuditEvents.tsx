import { useEffect, useState } from 'react';
import { ApiError } from './api.ts';
import { AUDIT_PAGE_SIZE, auditActionName, readAuditEvents } from './audit.ts';
import type { AuditPage } from './audit.ts';

const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false });

export function AuditEvents({ taskId, documentVersion, token, refresh, onExpired }: {
  taskId: string; documentVersion: number; token: string; refresh: number;
  onExpired: (message: string) => void;
}) {
  const [version, setVersion] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setPage(null);
    void readAuditEvents(taskId, token, version, offset, controller.signal).then(result => {
      if (!controller.signal.aborted) setPage(result);
    }).catch(cause => {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) onExpired(cause.message);
      else setError((cause as Error).message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [taskId, token, version, offset, refresh, reload]);

  return <section className="panel audit-events"><div className="section-head"><div><p className="eyebrow">系统管理 / 操作记录</p><h2>任务操作记录</h2></div><label>文档版本<select value={version ?? 'all'} onChange={event => { setVersion(event.target.value === 'all' ? null : Number(event.target.value)); setOffset(0); }}><option value="all">全部版本</option>{Array.from({ length: documentVersion }, (_, index) => index + 1).map(value => <option key={value} value={value}>V{value}</option>)}</select></label></div>
    <p className="muted">按记录顺序查看操作人、动作和文档版本；解析、规则、模型与报告状态见下方处理记录。</p>
    {loading && <p aria-busy="true">正在读取操作记录…</p>}
    {error && <p className="error" role="alert">{error} <button onClick={() => setReload(value => value + 1)}>重新读取</button></p>}
    {!loading && page && (page.items.length ? <div className="table-wrap"><table><thead><tr><th>序号</th><th>时间</th><th>操作</th><th>文档版本</th><th>操作人</th></tr></thead><tbody>{page.items.map(item => <tr key={item.id}><td>{item.id}</td><td>{date(item.created_at)}</td><td>{auditActionName(item.action)}<small>{item.action}</small></td><td>V{item.document_version}</td><td>{item.actor_username}<small>{item.actor_role}</small></td></tr>)}</tbody></table></div> : <p className="muted">该范围暂无操作记录。</p>)}
    {!loading && page && <div className="pagination"><small>共 {page.total} 条 · 第 {Math.floor(offset / AUDIT_PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(page.total / AUDIT_PAGE_SIZE))} 页</small><div className="actions"><button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - AUDIT_PAGE_SIZE))}>上一页</button><button disabled={offset + AUDIT_PAGE_SIZE >= page.total} onClick={() => setOffset(value => value + AUDIT_PAGE_SIZE)}>下一页</button></div></div>}
  </section>;
}
