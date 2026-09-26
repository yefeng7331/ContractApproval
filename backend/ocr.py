"""Same-version image OCR, isolated from the application's Python environment."""

import hashlib
import io
import json
import math
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image

from backend.pdf_parser import ParsedPdf, PdfParagraph

ROOT = Path(__file__).resolve().parents[1]
IMAGE_FORMATS = ('png', 'jpeg', 'tiff')
MAX_BYTES = 25 * 1024 * 1024


class OcrError(ValueError):
    def __init__(self, code, message, recovery='replace_attachment'):
        super().__init__(message)
        self.code, self.recovery = code, recovery


def image_pages(content):
    """Use the same pixel orientation and page order for OCR and PDF preview."""
    if not content or len(content) > MAX_BYTES:
        raise OcrError('OCR_IMAGE_INVALID', '图片为空或超过大小限制，请重新上传')
    try:
        pages = []
        pixels = 0
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ('PNG', 'JPEG', 'TIFF') or image.n_frames > 20:
                raise OcrError('OCR_IMAGE_INVALID', '图片格式或页数超出处理范围')
            for index in range(image.n_frames):
                image.seek(index)
                pixels += image.width * image.height
                if pixels > 40_000_000:
                    raise OcrError('OCR_IMAGE_INVALID', '图片总像素超过处理上限')
                pages.append(image.convert('RGB'))
        return pages
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        if isinstance(error, OcrError):
            raise
        raise OcrError('OCR_IMAGE_INVALID', '图片无法解码，请重新上传') from None


def recognize(content):
    python = ROOT / '.tools/ocr/venv/Scripts/python.exe'
    if not python.is_file():
        raise OcrError('OCR_DEPENDENCY_MISSING', 'OCR 隔离环境缺失，请管理员修复后重试', 'admin_retry')
    work = ROOT / 'storage/ocr/jobs'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as directory:
        source, result = Path(directory) / 'input.img', Path(directory) / 'result.json'
        source.write_bytes(content)
        try:
            completed = subprocess.run([str(python), '-X', 'utf8', str(ROOT / 'scripts/ocr_runtime.py'),
                str(source), str(result)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise OcrError('OCR_TIMEOUT', 'OCR 处理超时，请管理员核对后重试', 'admin_retry') from None
        except OSError:
            raise OcrError('OCR_RUNTIME_FAILED', 'OCR 进程无法启动，请管理员核对后重试', 'admin_retry') from None
        if completed.returncode or not result.is_file() or result.stat().st_size > 8 * 1024 * 1024:
            raise OcrError('OCR_RUNTIME_FAILED', 'OCR 运行失败，请管理员核对后重试', 'admin_retry')
        try:
            return json.loads(result.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise OcrError('OCR_RESULT_INVALID', 'OCR 返回数据无效，请管理员核对后重试', 'admin_retry') from None


def parse_image(content, version):
    if version < 1:
        raise ValueError('document_version must be positive')
    images = image_pages(content)
    pages = recognize(content)
    paragraphs, parts, offset = [], [], 0
    try:
        if not isinstance(pages, list) or len(pages) != len(images):
            raise ValueError
        for number, (page, image) in enumerate(zip(pages, images), 1):
            if (page['width'], page['height']) != image.size:
                raise ValueError
            texts, boxes, scores = page['texts'], page['boxes'], page['scores']
            if not all(isinstance(items, list) for items in (texts, boxes, scores)):
                raise ValueError
            if not texts:
                raise OcrError('OCR_UNREADABLE', '扫描页未识别到文字，请换传清晰附件')
            if not len(texts) == len(boxes) == len(scores):
                raise ValueError
            for text, box, score in zip(texts, boxes, scores):
                quote = unicodedata.normalize('NFC', text).strip()
                x1, y1, x2, y2 = map(float, box)
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError
                # Initial conservative cutoff, not calibrated accuracy or proof of completeness.
                if not quote or score < 0.9:
                    raise OcrError('OCR_LOW_CONFIDENCE', '扫描文字识别不可靠，请换传清晰附件')
                if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
                    raise ValueError
                if offset + len(quote) > 1_000_000:
                    raise OcrError('OCR_IMAGE_INVALID', '识别正文超过处理上限')
                if parts:
                    offset += 1
                rect = {'page': number, 'x': x1/image.width, 'y': y1/image.height,
                    'width': (x2-x1)/image.width, 'height': (y2-y1)/image.height}
                paragraphs.append(PdfParagraph(version, len(paragraphs), quote, offset,
                    offset+len(quote), number, True, None, (rect,)))
                parts.append(quote)
                offset += len(quote)
        return ParsedPdf(version, '\n'.join(parts), len(images), tuple(paragraphs), 'ocr')
    except (TypeError, KeyError, ValueError) as error:
        if isinstance(error, OcrError):
            raise
        raise OcrError('OCR_RESULT_INVALID', 'OCR 返回数据无效，请管理员核对后重试', 'admin_retry') from None


def parse_scanned_pdf(content, version):
    """Rasterize every page in displayed orientation; never silently omit a scan page."""
    import pypdfium2 as pdfium

    images = []
    try:
        with pdfium.PdfDocument(content) as pdf:
            if not 1 <= len(pdf) <= 20:
                raise OcrError('OCR_IMAGE_INVALID', '扫描 PDF 页数超过处理范围')
            pixels = 0
            for page in pdf:
                try:
                    width, height = page.get_size()
                    pixels += math.ceil(width * 150 / 72) * math.ceil(height * 150 / 72)
                    if pixels > 40_000_000:
                        raise OcrError('OCR_IMAGE_INVALID', '扫描 PDF 总像素超过处理上限')
                    bitmap = page.render(scale=150 / 72)
                    try:
                        images.append(bitmap.to_pil().convert('RGB'))
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        output = io.BytesIO()
        images[0].save(output, format='TIFF', save_all=True, append_images=images[1:], compression='tiff_lzw')
        return parse_image(output.getvalue(), version)
    except pdfium.PdfiumError:
        raise OcrError('OCR_PDF_UNREADABLE', '扫描 PDF 无法渲染，请换传清晰附件') from None
    finally:
        for image in images:
            image.close()


def image_preview(content, version, source):
    pages = image_pages(content)
    output = io.BytesIO()
    pages[0].save(output, format='PDF', save_all=True, append_images=pages[1:], resolution=72)
    pdf = output.getvalue()
    if len(pdf) > MAX_BYTES:
        raise OcrError('OCR_PREVIEW_TOO_LARGE', '扫描预览超过大小上限')
    return pdf, {'document_version': version, 'source_sha256': hashlib.sha256(content).hexdigest(),
        'preview_sha256': hashlib.sha256(pdf).hexdigest(), 'page_count': len(pages),
        'normalized_text': source['normalized_text'], 'text_matches': None,
        'mapping_scope': 'ocr_line_regions', 'paragraphs': json.loads(source['paragraphs_json'])}


def run_ocr_once(jobs):
    from backend.docx_job import _renew_lease
    from backend.pdf_structure import extract_pdf_structure

    lease = next((lease for fmt in IMAGE_FORMATS if (lease := jobs.claim_next(file_format=fmt))), None)
    if lease is None:
        return {'status': 'no_pending_image'}
    with _renew_lease(jobs, lease):
        try:
            path = Path(lease.file_path).resolve()
            if jobs.upload_root is None or not path.is_relative_to(jobs.upload_root / lease.task_id):
                raise OcrError('ATTACHMENT_CHANGED', '图片路径不属于当前任务，请重新上传')
            if path.stat().st_size > MAX_BYTES:
                raise OcrError('OCR_IMAGE_INVALID', '图片超过大小限制')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != lease.sha256:
                raise OcrError('ATTACHMENT_CHANGED', '图片原件摘要不一致，请重新上传')
            parsed = parse_image(content, lease.document_version)
            # Recheck the source after slow inference; stale leases are rejected at commit.
            if hashlib.sha256(path.read_bytes()).hexdigest() != lease.sha256:
                raise OcrError('ATTACHMENT_CHANGED', '识别期间图片发生变化，请重新上传')
            metadata, clauses = extract_pdf_structure(parsed, region_prefix='OCR')
            saved = jobs.complete_docx(lease, parsed, metadata, clauses)
            return {'status': 'reviewing' if saved else 'stale_lease'}
        except (OcrError, OSError) as error:
            code = getattr(error, 'code', 'ATTACHMENT_UNREADABLE')
            reason = str(error) if isinstance(error, OcrError) else '图片原件无法读取，请重新上传'
            saved = jobs.block_parse(lease, code, reason, recovery=getattr(error, 'recovery', 'replace_attachment'))
            return {'status': 'blocked' if saved else 'stale_lease', 'code': code}
