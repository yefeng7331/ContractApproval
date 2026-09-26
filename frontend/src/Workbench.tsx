import { useEffect, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { ApiError } from './api.ts';
import { evidenceMarks, loadEvidence } from './workbench.ts';
import type { Advice, Document, EvidenceMode, Mapping, Snapshot } from './workbench.ts';
import { PdfPage } from './PdfPage.tsx';
import { ReviewEditor } from './ReviewEditor.tsx';
import type { Task } from './model.ts';

GlobalWorkerOptions.workerSrc = workerUrl;

export function Workbench({ task, token, onExpired, onChanged, onDirtyChange, canLeave }: { task: Task; token: string; onExpired: (message: string) => void; onChanged: () => void; onDirtyChange: (dirty: boolean) => void; canLeave: () => boolean }) {
  const [data, setData] = useState<{ document: Document; snapshot: Snapshot | null; mapping: Mapping | null; advice: Advice | null } | null>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState('');
  const [notes, setNotes] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [mode, setMode] = useState<EvidenceMode>('risk');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [copied, setCopied] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let loadingPdf: ReturnType<typeof getDocument> | undefined;
    setData(null); setPdf(null); setError(''); setNotes([]); setSelected(''); setMode('risk'); setDetailsOpen(false); setPage(1); setCopied('');
    async function load() {
      try {
        const { document, snapshot, mapping, advice, notices } = await loadEvidence(task.task_id, task.document_version, task.submission?.filename, token, controller.signal);
        if (controller.signal.aborted) return;
        setData({ document, snapshot, mapping, advice });
        setNotes([...notices]);
        if (!document.preview_available) { setNotes([...notices, '固定 PDF 预览尚未生成，仅展示已保存原文与摘录。']); return; }
        try {
          const response = await fetch(`/api/v1/tasks/${encodeURIComponent(task.task_id)}/document/preview?document_version=${task.document_version}`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]), cache: 'no-store', credentials: 'omit' });
          if (!response.ok) throw new ApiError(response.status, `预览读取失败（${response.status}）`);
          const bytes = await response.arrayBuffer();
          if (mapping?.preview_sha256) {
            const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), value => value.toString(16).padStart(2, '0')).join('');
            if (hash !== mapping.preview_sha256) throw new Error('预览文件与定位摘要不一致');
          }
          if (controller.signal.aborted) return;
          loadingPdf = getDocument({ data: new Uint8Array(bytes), cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/', iccUrl: '/pdfjs/iccs/' });
          const loaded = await loadingPdf.promise;
          if (!controller.signal.aborted) setPdf(loaded);
        } catch (error) {
          if (controller.signal.aborted) return;
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) throw error;
          setNotes([...notices, `PDF 预览不可用：${(error as Error).message}`]);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setData(null); setPdf(null);
        if (error instanceof ApiError && error.status === 401) onExpired(error.message);
        else setError((error as Error).message);
      }
    }
    void load();
    return () => { controller.abort(); void loadingPdf?.destroy(); };
  }, [task.task_id, task.document_version, token, refresh]);
  const risks = data?.snapshot?.risks ?? [];
  const marks = data && pdf ? evidenceMarks(data.document, data.snapshot, data.mapping, mode).filter(mark => mark.rect.page <= pdf.numPages) : [];
  function select(id: string, kind: EvidenceMode, jump: boolean) {
    setMode(kind);
    setSelected(id);
    if (kind !== 'risk') setDetailsOpen(true);
    const first = data && pdf ? evidenceMarks(data.document, data.snapshot, data.mapping, kind).find(mark => mark.id === id && mark.rect.page <= pdf.numPages) : undefined;
    if (jump && first) setPage(first.rect.page);
    if (!jump) requestAnimationFrame(() => document.getElementById(`evidence-${kind}-${id}`)?.scrollIntoView({ block: 'nearest' }));
  }
  return <section className="review-workbench"><div className="section-head"><h2>原文与机器草稿 · 文档 V{task.document_version}</h2><button onClick={() => { if (canLeave()) { setRefresh(value => value + 1); onChanged(); } }}>重新读取工作台</button></div>
    <p className="notice">规则与模型内容均为草稿，演示规则不是法律结论，依据待法务核定。法务须核对同版原文和证据后保存、确认。</p>
    {error ? <p className="error" role="alert">{error}</p> : !data ? <p aria-busy="true">正在读取同版证据…</p> : <>
      {data.document.extraction_warning && <p className="notice">{data.document.extraction_warning}</p>}
      {notes.map(note => <p className="notice" key={note}>{note}</p>)}
      <div className="review-grid"><section className="panel"><h3>合同原文</h3>{pdf ? <><div className="actions page-controls"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><label>页码<input type="number" min={1} max={pdf.numPages} value={page} onChange={event => setPage(Math.max(1, Math.min(pdf.numPages, Math.trunc(Number(event.target.value)) || 1)))} /></label><span>/ {pdf.numPages}</span><button disabled={page >= pdf.numPages} onClick={() => setPage(page + 1)}>下一页</button></div><div className="actions evidence-modes" aria-label="原文高亮类型">{(['risk', 'field', 'clause'] as const).map(kind => <button key={kind} aria-pressed={mode === kind} onClick={() => { setMode(kind); setSelected(''); if (kind !== 'risk') setDetailsOpen(true); }}>{({ risk: '风险', field: '字段', clause: '条款' })[kind]}</button>)}</div><small>高亮为同版段落/整行区域，不代表逐字精确框；点击区域选中对应证据。</small><PdfPage pdf={pdf} page={page} marks={marks} selected={selected} label={mode} onSelect={id => select(id, mode, false)} /></> : <p className="muted">固定 PDF 尚不可显示；不能据此验收视觉定位。</p>}
        <details open={detailsOpen} onToggle={event => setDetailsOpen(event.currentTarget.open)}><summary>字段、条款与已解析文本</summary><dl>{data.document.fields.map(field => <div id={`evidence-field-${field.name}`} key={field.name} className={mode === 'field' && selected === field.name ? 'evidence-selected' : ''}><dt><button onClick={() => select(field.name, 'field', true)}>{field.name} · 定位原文</button></dt><dd>{field.value ?? '未识别'}{pdf && !evidenceMarks(data.document, data.snapshot, data.mapping, 'field').some(mark => mark.id === field.name && mark.rect.page <= pdf.numPages) && <small className="muted"> · 无法可靠定位</small>}</dd></div>)}</dl><p>未找到条款：{data.document.missing_clause_types.join('、') || '无'}</p>{data.document.clauses.map((clause, index) => <p id={`evidence-clause-${index}`} className={`original-text ${mode === 'clause' && selected === String(index) ? 'evidence-selected' : ''}`} key={`${clause.start}:${clause.end}`}><button onClick={() => select(String(index), 'clause', true)}>{clause.clause_type} · 定位原文</button>：{clause.quote}{pdf && !evidenceMarks(data.document, data.snapshot, data.mapping, 'clause').some(mark => mark.id === String(index) && mark.rect.page <= pdf.numPages) && <small className="muted"> · 无法可靠定位</small>}</p>)}<pre className="original-text">{data.document.normalized_text}</pre></details>
      </section><section className="risk-list"><h3>已保存规则草稿</h3><p>{data.snapshot?.machine_suggestion ?? '规则草稿暂不可用，不计算风险结论。'}</p>{data.snapshot && !risks.length && <p className="notice">未发现已启用规则风险，不代表法律安全。</p>}
        {risks.map(risk => <article id={`evidence-risk-${risk.rule_id}`} key={risk.rule_id} className={`panel risk-card ${mode === 'risk' && selected === risk.rule_id ? 'selected' : ''}`}><button onClick={() => select(risk.rule_id, 'risk', true)}>{risk.clause_type} · {({ high: '高', medium: '中', low: '低' } as Record<string, string>)[risk.risk_level] ?? risk.risk_level}风险 · 定位原文</button><p>{risk.trigger_reason}</p><small>规则 {risk.rule_id} / {risk.rule_version} · 企业商业风险演示规则 · 待法务核定</small>{risk.anchors.map(anchor => <blockquote key={`${anchor.start}:${anchor.end}`}>{anchor.quote}</blockquote>)}
          {pdf && !evidenceMarks(data.document, data.snapshot, data.mapping, 'risk').some(mark => mark.id === risk.rule_id && mark.rect.page <= pdf.numPages) && <p className="muted">无法可靠定位：同版 PDF 或已核验区域不可用，请核对摘录与原文。</p>}
          <h3>规则建议</h3><p>{risk.suggestion}</p><h3>已有模型建议</h3><p>{data.advice?.suggestions.find(item => item.rule_id === risk.rule_id)?.suggestion ?? '暂无可用建议，需法务补充。'}</p>
          <button onClick={async () => { try { await navigator.clipboard.writeText(data.advice?.suggestions.find(item => item.rule_id === risk.rule_id)?.suggestion ?? risk.suggestion); setCopied(`${risk.rule_id} 建议已复制`); } catch { setCopied('复制失败，请手动选择建议文本。'); } }}>复制建议</button>
          <small>以上为说明性建议，未作为替换条款或正式法务意见。</small>
        </article>)}<p role="status">{copied}</p>
      </section></div><ReviewEditor key={refresh} task={task} snapshot={data.snapshot} advice={data.advice} token={token} onExpired={onExpired} onChanged={onChanged} onDirtyChange={onDirtyChange} /></>}
  </section>;
}
