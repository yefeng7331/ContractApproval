"""Persist one text PDF parse under the existing exclusive parse lease."""

import hashlib
from pathlib import Path

from backend.docx_job import _renew_lease
from backend.pdf_parser import MAX_PDF_BYTES, PdfParseError, parse_pdf
from backend.pdf_structure import extract_pdf_structure
from backend.ocr import OcrError, parse_scanned_pdf


def run_pdf_once(jobs) -> dict:
    lease = jobs.claim_next(file_format="pdf")
    if lease is None:
        return {"status": "no_pending_pdf"}
    with _renew_lease(jobs, lease):
        try:
            path = Path(lease.file_path).resolve()
            if jobs.upload_root is None or not path.is_relative_to(jobs.upload_root / lease.task_id):
                raise PdfParseError('ATTACHMENT_CHANGED', 'PDF 路径不属于当前任务')
            if path.stat().st_size > MAX_PDF_BYTES:
                raise PdfParseError("PDF_UNREADABLE", "PDF 原件超过大小限制")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != lease.sha256:
                raise PdfParseError("ATTACHMENT_CHANGED", "PDF 原件摘要不一致，请重新上传")
            try:
                parsed = parse_pdf(content, lease.document_version, detect_images=True)
            except PdfParseError as error:
                if error.code not in ('PDF_EMPTY', 'PDF_OCR_REQUIRED'):
                    raise
                parsed = parse_scanned_pdf(content, lease.document_version)
            if hashlib.sha256(path.read_bytes()).hexdigest() != lease.sha256:
                raise PdfParseError('ATTACHMENT_CHANGED', 'PDF 识别期间原件发生变化')
        except (OSError, PdfParseError, OcrError) as error:
            code = getattr(error, 'code', 'ATTACHMENT_UNREADABLE')
            reason = str(error) if isinstance(error, (PdfParseError, OcrError)) else "PDF 原件无法读取，请重新上传"
            saved = jobs.block_parse(lease, code, reason, recovery=getattr(error, 'recovery', 'replace_attachment'))
            return {"status": "blocked" if saved else "stale_lease", "code": code}
        metadata, clauses = extract_pdf_structure(parsed, region_prefix='OCR' if parsed.extraction_method == 'ocr' else 'PDF')
        saved = jobs.complete_docx(lease, parsed, metadata, clauses)
        return {"status": "reviewing" if saved else "stale_lease"}
