"""Extract verifiable paragraph spans from a DOCX body without page claims."""

from __future__ import annotations

import io
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PARAGRAPH_TAG = f"{{{WORD_NS}}}p"
BODY_TAG = f"{{{WORD_NS}}}body"
TEXT_TAG = f"{{{WORD_NS}}}t"
TAB_TAG = f"{{{WORD_NS}}}tab"
BREAK_TAGS = {f"{{{WORD_NS}}}br", f"{{{WORD_NS}}}cr"}
MAX_DOCX_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_XML_BYTES = 32 * 1024 * 1024


class DocxParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParagraphSpan:
    document_version: int
    paragraph_index: int
    quote: str
    start: int
    end: int
    page: None = None
    locatable: bool = False
    reason: str = "PREVIEW_NOT_AVAILABLE"
    rects: tuple[()] = ()


@dataclass(frozen=True)
class ParsedDocx:
    document_version: int
    normalized_text: str
    paragraphs: tuple[ParagraphSpan, ...]


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == TEXT_TAG:
            parts.append(element.text or "")
        elif element.tag == TAB_TAG:
            parts.append("\t")
        elif element.tag in BREAK_TAGS:
            parts.append("\n")
    return unicodedata.normalize("NFC", "".join(parts).replace("\r\n", "\n").replace("\r", "\n"))


def parse_docx(content: bytes, document_version: int) -> ParsedDocx:
    """Return Word-body text and exact Unicode spans; page mapping comes later."""
    if document_version < 1:
        raise ValueError("document_version must be positive")
    if not content or len(content) > MAX_DOCX_BYTES:
        raise DocxParseError("DOCX_UNREADABLE", "DOCX 附件为空或超过 25 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
                raise DocxParseError("DOCX_TOO_COMPLEX", "DOCX 解压后内容过大")
            try:
                document = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise DocxParseError("DOCX_UNREADABLE", "DOCX 缺少正文") from exc
            if document.file_size > MAX_DOCUMENT_XML_BYTES:
                raise DocxParseError("DOCX_TOO_COMPLEX", "DOCX 正文过大")
            xml = archive.read(document)
    except (OSError, zipfile.BadZipFile, EOFError, RuntimeError, zlib.error) as exc:
        raise DocxParseError("DOCX_UNREADABLE", "DOCX 文件损坏或无法读取") from exc
    declaration_view = xml.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declaration_view or b"<!ENTITY" in declaration_view:
        raise DocxParseError("DOCX_UNREADABLE", "DOCX 正文包含不支持的实体定义")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DocxParseError("DOCX_UNREADABLE", "DOCX 正文 XML 无法解析") from exc
    body = root.find(BODY_TAG)
    if body is None:
        raise DocxParseError("DOCX_UNREADABLE", "DOCX 缺少正文节点")

    text_parts: list[str] = []
    spans: list[ParagraphSpan] = []
    offset = 0
    for index, paragraph in enumerate(body.iter(PARAGRAPH_TAG)):
        quote = _paragraph_text(paragraph)
        if not quote.strip():
            continue
        if text_parts:
            text_parts.append("\n")
            offset += 1
        start = offset
        text_parts.append(quote)
        offset += len(quote)
        spans.append(ParagraphSpan(document_version, index, quote, start, offset))
    if not spans:
        raise DocxParseError("DOCX_EMPTY", "DOCX 正文没有可提取文字")
    return ParsedDocx(document_version, "".join(text_parts), tuple(spans))
