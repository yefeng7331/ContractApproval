"""Extract text and same-version page regions from a text PDF.

This component has no job or API side effects. Each extracted visual line is a
paragraph until layout-aware grouping is verified with more than the F2 sample.
"""

from __future__ import annotations

import io
import math
import unicodedata
from dataclasses import dataclass

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfexceptions import PDFException
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException


MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_CHARACTERS = 1_000_000


class PdfParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PdfParagraph:
    document_version: int
    paragraph_index: int
    quote: str
    start: int
    end: int
    page: int
    locatable: bool
    reason: str | None
    rects: tuple[dict[str, int | float], ...]


@dataclass(frozen=True)
class ParsedPdf:
    document_version: int
    normalized_text: str
    page_count: int
    paragraphs: tuple[PdfParagraph, ...]
    extraction_method: str = 'text'


def _region(line: dict, page: object, page_number: int) -> dict[str, int | float] | None:
    width, height = float(page.width), float(page.height)
    x0, top, x1, bottom = (float(line[key]) for key in ("x0", "top", "x1", "bottom"))
    if not all(math.isfinite(value) for value in (width, height, x0, top, x1, bottom)):
        return None
    if not (0 <= x0 < x1 <= width and 0 <= top < bottom <= height):
        return None
    return {
        "page": page_number,
        "x": x0 / width,
        "y": top / height,
        "width": (x1 - x0) / width,
        "height": (bottom - top) / height,
    }


def parse_pdf(content: bytes, document_version: int, *, detect_images: bool = False) -> ParsedPdf:
    """Return NFC text, exact code-point spans, and normalized PDF regions."""
    if document_version < 1:
        raise ValueError("document_version must be positive")
    if not content or len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
        raise PdfParseError("PDF_UNREADABLE", "PDF 附件为空、过大或格式不正确")

    paragraphs: list[PdfParagraph] = []
    parts: list[str] = []
    offset = 0
    page_count = 0
    needs_ocr = False
    try:
        with pdfplumber.open(io.BytesIO(content), unicode_norm="NFC") as pdf:
            if pdf.doc.encryption:
                raise PdfParseError("PDF_ENCRYPTED", "PDF 已加密，请重新上传可读取的附件")
            page_count = len(pdf.pages)
            if page_count > MAX_PAGES:
                raise PdfParseError("PDF_TOO_COMPLEX", "PDF 页数超过处理上限")
            for page_number, page in enumerate(pdf.pages, 1):
                before = len(paragraphs)
                # Uploads with images may contain scanned text alongside a text layer.
                needs_ocr |= detect_images and bool(page.images)
                for line in page.extract_text_lines(return_chars=False):
                    quote = unicodedata.normalize("NFC", line["text"]).strip()
                    if not quote:
                        continue
                    if offset + len(quote) > MAX_CHARACTERS:
                        raise PdfParseError("PDF_TOO_COMPLEX", "PDF 正文超过处理上限")
                    if parts:
                        parts.append("\n")
                        offset += 1
                    start = offset
                    parts.append(quote)
                    offset += len(quote)
                    region = _region(line, page, page_number)
                    paragraphs.append(PdfParagraph(
                        document_version=document_version,
                        paragraph_index=len(paragraphs),
                        quote=quote,
                        start=start,
                        end=offset,
                        page=page_number,
                        locatable=region is not None,
                        reason=None if region is not None else "PDF_REGION_UNRELIABLE",
                        rects=(region,) if region is not None else (),
                    ))
                needs_ocr |= len(paragraphs) == before
                page.close()
    except PdfminerException as exc:
        cause = exc.args[0] if exc.args else None
        if isinstance(cause, (PDFPasswordIncorrect, PDFEncryptionError)):
            raise PdfParseError("PDF_ENCRYPTED", "PDF 需要口令或加密格式不可读取，请重新上传") from exc
        raise PdfParseError("PDF_UNREADABLE", "PDF 结构或文本层无法读取") from exc
    except PDFPasswordIncorrect as exc:
        raise PdfParseError("PDF_ENCRYPTED", "PDF 需要口令，请重新上传可读取的附件") from exc
    except PDFEncryptionError as exc:
        raise PdfParseError("PDF_ENCRYPTED", "PDF 加密格式不可读取，请重新上传") from exc
    except (PDFException, MalformedPDFException, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        if isinstance(exc, PdfParseError):
            raise
        raise PdfParseError("PDF_UNREADABLE", "PDF 结构或文本层无法读取") from exc

    if not paragraphs:
        raise PdfParseError("PDF_EMPTY", "PDF 未提取到文字；扫描件需 OCR")
    if needs_ocr:
        raise PdfParseError('PDF_OCR_REQUIRED', 'PDF 存在图片或无文本页，需整份 OCR 核对')
    return ParsedPdf(document_version, "".join(parts), page_count, tuple(paragraphs))
