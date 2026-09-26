import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { Rect } from './workbench.ts';

export function PdfPage({ pdf, page, marks, selected, label, onSelect }: { pdf: PDFDocumentProxy; page: number; marks: { id: string; rect: Rect }[]; selected: string; label: 'risk' | 'field' | 'clause'; onSelect: (id: string) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [rendered, setRendered] = useState<{ pdf: PDFDocumentProxy; page: number } | null>(null);
  const ready = rendered?.pdf === pdf && rendered.page === page;
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    let render: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    setRendered(null); setError('');
    void pdf.getPage(page).then(async source => {
      if (cancelled || !canvas.current) return;
      const viewport = source.getViewport({ scale: 1.35 });
      canvas.current.width = viewport.width; canvas.current.height = viewport.height;
      render = source.render({ canvas: canvas.current, viewport });
      await render.promise;
      if (!cancelled) setRendered({ pdf, page });
    }).catch(error => { if (!cancelled) setError(`预览渲染失败：${error.message}`); });
    return () => { cancelled = true; render?.cancel(); };
  }, [pdf, page]);
  return <><p aria-live="polite">{error || (!ready ? '正在渲染页面…' : '')}</p><div className="pdf-page" style={{ visibility: ready ? 'visible' : 'hidden' }}><canvas ref={canvas} aria-label={`合同原文第 ${page} 页`} />
    {ready && marks.filter(mark => mark.rect.page === page).map((mark, index) => <button key={`${mark.id}:${index}`} className={`pdf-mark ${selected === mark.id ? 'chosen' : ''}`} aria-label={`选择${({ risk: '风险', field: '字段', clause: '条款' })[label]} ${mark.id}`} onClick={() => onSelect(mark.id)} style={{ left: `${mark.rect.x * 100}%`, top: `${mark.rect.y * 100}%`, width: `${mark.rect.width * 100}%`, height: `${mark.rect.height * 100}%` }} />)}
  </div></>;
}
