import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { ApiError, request } from './api.ts';
import { contractAmount, contractTitle, formalRisk, formatTaskTime, legalNames, machineNames, nextStep, phase, phases, roles, writebackNames } from './model.ts';
import type { Phase, Role, Session, Task } from './model.ts';
import './style.css';
import { Intake } from './Intake.tsx';
import { Replacement } from './Replacement.tsx';
import { Reports } from './Reports.tsx';
import { Writeback } from './Writeback.tsx';
import { Recovery } from './Recovery.tsx';
import { AuditEvents } from './AuditEvents.tsx';
import { ProcessingRecords } from './ProcessingRecords.tsx';
import { canReplace } from './intake.ts';
import { startTaskPolling } from './taskPolling.ts';
const Workbench = lazy(() => import('./Workbench.tsx').then(module => ({ default: module.Workbench })));

const Brand = () => <div className="brand"><b>审</b><div>合同审查<small>CONTRACT REVIEW</small></div></div>;
const date = formatTaskTime;

function App() {
  // Session and protected views live only in memory; refresh requires login.
  const [session, setSession] = useState<Session | null>(null);
  const [message, setMessage] = useState('');
  return session ? <Workspace key={session.access_token} session={session} onExit={message => { setSession(null); setMessage(message); }} />
    : <Login message={message} onLogin={value => { setSession(value); setMessage(''); }} />;
}

function Login({ message, onLogin }: { message: string; onLogin: (session: Session) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(message);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true); setError('');
    try {
      const result = await request<Session>('/sessions', null, undefined, {
        method: 'POST', body: JSON.stringify({ username: String(fields.get('username')).trim(), password: fields.get('password') }),
      });
      form.reset(); onLogin(result);
    } catch (error) {
      setError(error instanceof ApiError && error.status === 401 ? '账号或密码错误，请重新输入。' : (error as Error).message);
    } finally { setBusy(false); }
  }
  return <section className="login">
    <div className="login-story"><Brand /><div><p className="eyebrow">合同审查工作空间</p><h1>每一个审查结论，<br />都有原文可循。</h1><p>从合同接入、证据定位，到法务复核与报告交付。<br />同一任务里，看清来源、版本和责任。</p></div><small>中国大陆软件采购合同 · 合成数据演示版</small></div>
    <div className="login-form"><p className="eyebrow">欢迎回来</p><h2>登录工作空间</h2><p className="muted">使用已有本地账号，查看你的合同任务。</p>
      <form onSubmit={submit} aria-busy={busy}><label>账号<input name="username" autoComplete="username" required maxLength={64} disabled={busy} autoFocus /></label>
        <label>密码<input name="password" type="password" autoComplete="current-password" required disabled={busy} /></label>
        {error && <p className="error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? '正在登录…' : '登录'}</button>
      </form><small>身份由账号权限决定。刷新页面后需重新登录。</small>
    </div>
  </section>;
}

function Workspace({ session, onExit }: { session: Session; onExit: (message: string) => void }) {
  const role = session.user.role;
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [forbidden, setForbidden] = useState(false);
  const [updated, setUpdated] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [reviewDirty, setReviewDirty] = useState(false);
  const [workbenchEpoch, setWorkbenchEpoch] = useState(0);
  const reviewDirtyRef = useRef(false);
  reviewDirtyRef.current = reviewDirty;
  const [selected, setSelected] = useState<string | null>(null);
  const [intake, setIntake] = useState(false);
  const [receipt, setReceipt] = useState<Task | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [statusFilter, setStatusFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState('all');
  const [page, setPage] = useState(0);

  useEffect(() => {
    setLoading(true);
    return startTaskPolling({ token: session.access_token,
       onTasks: data => { if (!reviewDirtyRef.current) { setTasks(data); setError(''); setForbidden(false); setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false })); } },
       onError: message => { if (!reviewDirtyRef.current) setError(message); },
       onForbidden: message => { setTasks([]); setReceipt(null); setSelected(null); setIntake(false); setReviewDirty(false); setUpdated(''); setForbidden(true); setError(message); },
      onExpired: onExit,
      onSettled: () => setLoading(false),
    });
  }, [session.access_token, refresh]);

  useEffect(() => {
    const expiry = Date.parse(session.expires_at) - Date.now();
    const timer = setTimeout(() => onExit('登录已到期，请重新登录。'), Math.max(0, expiry));
    return () => clearTimeout(timer);
  }, [session.expires_at]);

  async function logout() {
    if (loggingOut) return;
    if (!canLeaveReview()) return;
    setLoggingOut(true);
    try { await request<void>('/sessions/current', session.access_token, undefined, { method: 'DELETE' }); onExit('已退出登录。'); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) onExit('会话已失效。');
      else onExit('本页已退出；服务未响应，服务端会话未确认撤销，将按原有效期到期。');
    }
  }
  const counts = { blocked: 0, processing: 0, review: 0, confirmed: 0 };
  tasks.forEach(task => counts[phase(task)]++);
  const filtered = tasks.filter(task => (statusFilter === 'all' || phase(task) === statusFilter)
    && (riskFilter === 'all' || (phase(task) === 'confirmed' && task.risk_level === riskFilter)));
  const currentPage = Math.min(page, Math.max(0, Math.ceil(filtered.length / 20) - 1));
  const task = tasks.find(task => task.task_id === selected) ?? (receipt?.task_id === selected ? receipt : undefined);
  const next = tasks.find(task => role === 'legal' ? phase(task) === 'review'
    : task.machine_status === 'blocked' && task.recovery_action === (role === 'admin' ? 'admin_retry' : 'replace_attachment'));
  function canLeaveReview() { return !reviewDirtyRef.current || window.confirm('有未保存的法务输入，确定离开并丢弃本次输入？'); }
  function dashboard() { if (!canLeaveReview()) return; setSelected(null); setIntake(false); setReceipt(null); setReviewDirty(false); setRefresh(value => value + 1); }
  function created(task: Task) {
    setReceipt(task); setTasks(current => [task, ...current.filter(item => item.task_id !== task.task_id)]);
    setSelected(task.task_id); setIntake(false); setRefresh(value => value + 1);
  }

  return <div className="shell"><aside><Brand /><div className="nav-caption">工作空间</div><nav aria-label="主导航"><button onClick={dashboard} className={!selected && !intake ? 'active' : ''} aria-current={!selected && !intake ? 'page' : undefined}>任务大盘</button>
      {role === 'business' && <button className={intake ? 'active' : ''} aria-current={intake ? 'page' : undefined} onClick={() => { setIntake(true); setSelected(null); setReceipt(null); }}>合同接入</button>}
      <span className="nav-note">{role === 'business' ? '本人任务与处理进度' : role === 'legal' ? '待复核任务与确认状态' : '处理状态与故障恢复'}</span></nav>
      <div className="sidebar-foot"><strong>{session.user.username}</strong><small>{roles[role]}</small><button onClick={logout} disabled={loggingOut}>{loggingOut ? '正在退出…' : '退出登录'}</button><small>合成数据演示版</small></div></aside>
    <main className="workspace"><header><div><p className="eyebrow">{roles[role]} / 工作空间</p><h1>{intake ? '合同接入' : selected ? '任务进度' : '任务大盘'}</h1></div><span className="pill">{error ? '服务读取失败' : loading ? '正在读取服务' : '已连接本地服务'}</span></header>
      <div className="subhead"><p className="muted">{selected ? '当前文档的独立处理状态' : role === 'business' ? '本人任务的当前进度与下一步' : '可见任务的当前进度与下一步'}</p><div className="actions"><small aria-live="polite">{loading ? '正在读取…' : error ? '读取失败' : `更新于 ${updated}`}</small><button disabled={loading} onClick={() => { if (canLeaveReview()) { setReviewDirty(false); setWorkbenchEpoch(value => value + 1); setRefresh(value => value + 1); } }}>刷新任务</button></div></div>
      {receipt && <p className="notice" role="status">任务已登记：{receipt.task_id} · 文档 V{receipt.document_version}。{receipt.machine_status === 'blocked' ? `附件接入受阻：${receipt.blocked_reason ?? receipt.blocked_code}。请按任务指引处理。` : '附件已接收，请查看下方处理进度。'}</p>}
       {error && <section className="error" role="alert"><h2>{forbidden ? '无权访问任务' : '任务读取失败'}</h2><p>{forbidden ? `${error}。已隐藏当前任务信息。` : `${error}，正在重试；已有任务信息可能过期。`}</p><button onClick={() => setRefresh(value => value + 1)}>重新读取</button></section>}
       {forbidden ? null
         : intake && role === 'business' ? <Intake token={session.access_token} onCreated={created} onExpired={onExit} />
        : error && !updated ? null
        : loading && !updated ? <section className="empty" aria-busy="true">正在读取当前账号可见的任务…</section>
        : selected ? <><button onClick={dashboard}>← 返回任务大盘</button>{task ? <><TaskDetail task={task} role={role} />{role === 'admin' && <><Recovery key={`${task.task_id}:${task.document_version}`} task={task} token={session.access_token} onExpired={onExit} onChanged={updated => { setTasks(current => current.map(item => item.task_id === updated.task_id ? updated : item)); setRefresh(value => value + 1); }} /><AuditEvents key={task.task_id} taskId={task.task_id} documentVersion={task.document_version} token={session.access_token} refresh={refresh} onExpired={onExit} /><ProcessingRecords key={task.task_id} taskId={task.task_id} documentVersion={task.document_version} token={session.access_token} refresh={refresh} onExpired={onExit} /></>}{role === 'legal' && <Suspense fallback={<p aria-busy="true">正在载入原文工作台…</p>}><Workbench key={`${task.task_id}:${task.document_version}:${task.review_version}:${workbenchEpoch}`} task={task} token={session.access_token} onExpired={onExit} onChanged={() => { setReviewDirty(false); setRefresh(value => value + 1); }} onDirtyChange={setReviewDirty} canLeave={canLeaveReview} /></Suspense>}{role === 'business' && canReplace(task) && <Replacement key={`${task.task_id}:${task.document_version}`} task={task} token={session.access_token} onSaved={created} onExpired={onExit} />}{role !== 'admin' && <Reports key={`${task.task_id}:${task.latest_confirmed_version?.review_version ?? 'none'}`} task={task} role={role} token={session.access_token} onExpired={onExit} />}{(role !== 'admin' || task.legal_status === 'confirmed') && <Writeback key={`${task.task_id}:${task.latest_confirmed_version?.review_version ?? task.review_version ?? 'none'}`} task={task} role={role} token={session.access_token} onExpired={onExit} />}</> : <section className="empty">任务已不存在或当前账号不可见，请返回大盘。</section>}</>
        : <>
          <section className="overview"><div className="panel"><div className="section-head"><h2>当前处理分布</h2><small>{role === 'business' ? '本人任务' : '可见任务'} · 共 {tasks.length} 份</small></div><p className="muted">按当前文档归类，旧版已确认结果不计入当前分布。</p>
            <div className="distribution" aria-hidden="true">{(Object.keys(phases) as Phase[]).map(key => counts[key] > 0 && <div key={key} className={key} style={{ flex: counts[key] }} />)}</div>
            <div className="legend">{(Object.keys(phases) as Phase[]).map(key => <div key={key}><span className={`dot ${key}`} /><strong>{phases[key]}</strong><small>{counts[key]} 份 · {tasks.length ? Math.round(counts[key] / tasks.length * 100) : 0}%</small></div>)}</div>
          </div><div className="panel next"><p className="eyebrow">下一步</p><h2>{next ? nextStep(next, role) : '暂无需要你处理的任务'}</h2><p className="muted">{next ? role === 'admin' ? `任务 ${next.task_id.slice(0, 8)}` : next.submission?.filename ?? `任务 ${next.task_id.slice(0, 8)}` : '任务进度更新后，可在这里查看处理方向。'}</p>{next && <button className="primary" onClick={() => setSelected(next.task_id)}>查看任务进度</button>}</div></section>
          <section className="panel"><div className="section-head"><div><h2>合同任务</h2><small>三组状态分别展示；机器完成不等于法务确认。</small></div><div className="filters"><label>当前阶段<select value={statusFilter} onChange={event => { setStatusFilter(event.target.value); setPage(0); }}><option value="all">全部阶段</option>{Object.entries(phases).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            {role !== 'admin' && <label>正式等级<select value={riskFilter} onChange={event => { setRiskFilter(event.target.value); setPage(0); }}><option value="all">全部等级</option><option value="high">高风险</option><option value="medium">中风险</option><option value="low">低风险</option></select></label>}</div></div>
            {!filtered.length ? <div className="empty"><h3>{tasks.length ? '没有符合筛选条件的任务' : '还没有可见任务'}</h3><p className="muted">{tasks.length ? '调整筛选条件查看其他任务。' : role === 'business' ? '从左侧合同接入上传合成附件或导入模拟待办。' : '业务提交任务后将显示在这里。'}</p></div>
              : <div className="table-wrap"><table><thead><tr><th>{role === 'admin' ? '任务 / 所属账号' : '合同名称 / 提交信息'}</th>{role !== 'admin' && <th>金额</th>}<th>机器审查</th><th>法务复核</th><th>模拟回写</th>{role !== 'admin' && <th>当前正式等级</th>}<th>下一步</th><th>操作</th></tr></thead><tbody>{filtered.slice(currentPage * 20, (currentPage + 1) * 20).map(task => <tr key={task.task_id}><td><strong>{role === 'admin' ? `任务 ${task.task_id.slice(0, 8)}` : contractTitle(task)}</strong>{role !== 'admin' && <small>文件：{task.submission?.filename ?? '未记录'}</small>}<small>{role === 'admin' ? task.owner_username : `${task.submission?.department ?? '未提供部门'} · ${task.submission?.applicant ?? task.owner_username}`}</small>{role !== 'admin' && <small>业务类型：{task.submission?.business_type ?? '未记录'}</small>}<small>创建：{date(task.created_at)}（本机时间）</small><small>文档 V{task.document_version}{task.review_version ? ` · 审查 V${task.review_version}` : ''}</small></td>{role !== 'admin' && <td>{contractAmount(task)}</td>}<td><span className={`pill ${task.machine_status === 'blocked' ? 'bad' : ''}`}>{machineNames[task.machine_status] ?? task.machine_status}</span></td><td>{legalNames[task.legal_status] ?? task.legal_status}</td><td>{writebackNames[task.writeback_status] ?? task.writeback_status}</td>{role !== 'admin' && <td>{formalRisk(task)}</td>}<td className="muted">{nextStep(task, role)}</td><td><button onClick={() => setSelected(task.task_id)} aria-label={`查看任务 ${task.task_id} 的进度`}>查看进度</button></td></tr>)}</tbody></table></div>}
            <div className="pagination"><small>筛选结果 {filtered.length} 份 · 第 {currentPage + 1} / {Math.max(1, Math.ceil(filtered.length / 20))} 页</small><div className="actions"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button><button disabled={(currentPage + 1) * 20 >= filtered.length} onClick={() => setPage(currentPage + 1)}>下一页</button></div></div>
          </section>
        </>}
      <footer>本机合成数据演示 · 模拟回写不连接真实审批平台</footer>
    </main></div>;
}

function TaskDetail({ task, role }: { task: Task; role: Role }) {
  const history = task.latest_confirmed_version;
  return <section className="panel detail"><p className="eyebrow">{task.source === 'mock_pending' ? '模拟待办导入' : '本地上传'} · 文档 V{task.document_version}</p><h2>{role === 'admin' ? `任务 ${task.task_id.slice(0, 8)}` : task.submission?.filename ?? `任务 ${task.task_id.slice(0, 8)}`}</h2>
    <div className="status-strip"><div><small>机器审查</small><strong>{machineNames[task.machine_status] ?? task.machine_status}</strong></div><div><small>法务复核</small><strong>{legalNames[task.legal_status] ?? task.legal_status}</strong></div><div><small>模拟回写</small><strong>{writebackNames[task.writeback_status] ?? task.writeback_status}</strong></div></div>
    <div className={task.machine_status === 'blocked' ? 'error' : 'notice'}><strong>{nextStep(task, role)}</strong>{task.blocked_reason && <p>{task.blocked_reason}</p>}{task.blocked_code && <small>故障代码：{task.blocked_code}</small>}</div>
    <dl><dt>任务 ID</dt><dd>{task.task_id}</dd><dt>所属账号</dt><dd>{task.owner_username}</dd><dt>建立时间</dt><dd>{date(task.created_at)}</dd>{role !== 'admin' && <><dt>合同名称</dt><dd>{contractTitle(task)}</dd><dt>金额</dt><dd>{contractAmount(task)}</dd></>}<dt>当前审查版本</dt><dd>{task.review_version ? `V${task.review_version}` : '尚未形成'}</dd>{role !== 'admin' && <><dt>当前正式等级</dt><dd>{formalRisk(task)}</dd></>}</dl>
    {role !== 'admin' && history && <p className="notice">最近确认结果属于文档 V{history.document_version} / 审查 V{history.review_version}。{history.document_version !== task.document_version || history.review_version !== task.review_version ? '此为历史确认版本，不代表当前文档结论。' : '此为当前确认版本。'}</p>}
    <p className="muted">{role === 'admin' ? '管理员仅查看处理状态、故障和操作记录元数据，不显示合同原文或法务意见。' : role === 'legal' ? '请在下方核对同版原文和机器草稿，逐项保存审查草稿并填写正式结论。' : '当前任务进度以已保存版本为准。'}</p>
  </section>;
}

createRoot(document.getElementById('root')!).render(<App />);
