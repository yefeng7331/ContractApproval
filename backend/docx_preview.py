"""Isolated DOCX conversion and conservative paragraph-to-preview mapping.

Component only: no database, API, rule-snapshot mutation, or automatic install.
"""

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict
from pathlib import Path

from backend.docx_parser import parse_docx
from backend.errors import ApiError
from backend.pdf_parser import MAX_PDF_BYTES, parse_pdf


def find_converter():
    """Discover an existing executable without installing or changing PATH."""
    candidates = [shutil.which('soffice')]
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe') as key:
                candidates.append(winreg.QueryValue(key, None))
        except OSError:
            pass
    for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / 'LibreOffice/program/soffice.exe')
    return next((Path(p).resolve() for p in candidates if p and Path(p).is_file()), None)


def _check_package(content):
    # Only static synthetic documents in this demo; refuse embedded/linked content.
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for entry in archive.infolist():
            name = entry.filename.lower()
            if 'vbaproject' in name or name.startswith(('word/embeddings/', 'word/activex/')):
                raise ApiError(409, 'DOCX_PREVIEW_UNSUPPORTED', '预览不接受宏或嵌入对象')
            if name.endswith('.rels'):
                try:
                    root = ET.fromstring(archive.read(entry))
                except ET.ParseError:
                    raise ApiError(409, 'DOCX_PREVIEW_UNSUPPORTED', 'DOCX 关系文件无法核对') from None
                if any(r.get('TargetMode', '').lower() == 'external' for r in root):
                    raise ApiError(409, 'DOCX_PREVIEW_UNSUPPORTED', '预览不接受外部链接或资源')


def map_preview(parsed, pdf_content):
    """Map complete visual lines only; retain original DOCX Unicode offsets.

    Ignoring whitespace permits wrapping and page breaks. The complete non-space
    text must agree in order: partial/fuzzy matches never claim reliable locations.
    """
    pdf = parse_pdf(pdf_content, parsed.document_version)
    compact = lambda text: ''.join(text.split())
    matching = compact(parsed.normalized_text) == compact(pdf.normalized_text)
    lines, offset = [], 0
    for line in pdf.paragraphs:
        end = offset + len(compact(line.quote))
        lines.append((offset, end, line))
        offset = end
    anchors, offset, cursor = [], 0, 0
    for paragraph in parsed.paragraphs:
        end = offset + len(compact(paragraph.quote))
        while cursor < len(lines) and lines[cursor][1] <= offset:
            cursor += 1
        following = cursor
        while following < len(lines) and lines[following][0] < end:
            following += 1
        selected = lines[cursor:following]
        reliable = (matching and bool(selected) and selected[0][0] == offset
                    and selected[-1][1] == end and all(line.locatable for _, _, line in selected))
        anchor = asdict(paragraph)
        anchor.update(page=selected[0][2].page if reliable else None,
            locatable=reliable,
            reason=None if reliable else ('DOCX_PREVIEW_TEXT_MISMATCH' if not matching else 'DOCX_PREVIEW_REGION_UNVERIFIED'),
            rects=[rect for _, _, line in selected for rect in line.rects] if reliable else [])
        anchors.append(anchor)
        offset = end
    # ponytail: whole-text agreement and whole-line boxes; add character geometry
    # only after real complex layouts can verify smaller field/substring regions.
    return {'document_version': parsed.document_version, 'page_count': pdf.page_count,
        'preview_sha256': hashlib.sha256(pdf_content).hexdigest(),
        'normalized_text': parsed.normalized_text, 'paragraphs': anchors,
        'mapping_scope': 'paragraph_whole_lines', 'text_matches': matching}


def convert_docx(content, document_version, *, executable=None):
    """Return PDF bytes and mapping, without publishing or replacing any artifact."""
    if type(document_version) is not int or document_version < 1:
        raise ValueError('document_version must be a positive integer')
    parsed = parse_docx(content, document_version)
    _check_package(content)
    converter = Path(executable).resolve() if executable else find_converter()
    if converter is None or not converter.is_file():
        raise ApiError(409, 'DOCX_PREVIEW_DEPENDENCY_MISSING', '未找到 LibreOffice，未生成固定预览')
    # Each conversion owns its input/output/profile; do not attach to a user's GUI.
    with tempfile.TemporaryDirectory(prefix='contract-preview-') as directory:
        root = Path(directory)
        source = root / 'source.docx'
        source.write_bytes(content)
        output = root / 'output'
        output.mkdir()
        command = [str(converter), '-env:UserInstallation=' + (root / 'profile').as_uri(),
            '--headless', '--norestore', '--nodefault', '--nolockcheck',
            '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(output), str(source)]
        try:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=60, check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise ApiError(409, 'DOCX_PREVIEW_TIMEOUT', 'DOCX 转换超时，未发布预览') from None
        except OSError:
            raise ApiError(409, 'DOCX_PREVIEW_FAILED', 'DOCX 转换程序无法运行') from None
        preview = output / 'source.pdf'
        if completed.returncode != 0 or not preview.is_file() or preview.stat().st_size > MAX_PDF_BYTES:
            raise ApiError(409, 'DOCX_PREVIEW_FAILED', 'DOCX 转换未产出可读取的预览')
        pdf_content = preview.read_bytes()
        mapping = map_preview(parsed, pdf_content)
        mapping['source_sha256'] = hashlib.sha256(content).hexdigest()
        return pdf_content, mapping
