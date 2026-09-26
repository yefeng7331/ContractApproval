"""Preview component smoke; real synthetic PDF extraction, simulated conversion."""

import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.docx_parser import parse_docx
from backend.docx_preview import convert_docx, map_preview
from backend.errors import ApiError
from backend.pdf_parser import ParsedPdf, PdfParagraph
from tests.test_docx_parser import package


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


class DocxPreviewTests(unittest.TestCase):
    def setUp(self):
        self.docx = (SAMPLES / 'f1-software-purchase.docx').read_bytes()
        self.pdf = (SAMPLES / 'f2-text-software-purchase.pdf').read_bytes()

    def test_real_text_mapping_without_claiming_real_conversion(self):
        parsed = parse_docx(self.docx, 7)
        mapped = map_preview(parsed, self.pdf)
        oracle = json.loads((SAMPLES / 'f2_expected.json').read_text(encoding='utf-8'))
        pages = {index: row['page'] for row in oracle['pages'] for index in row['paragraph_indexes']}
        self.assertTrue(mapped['text_matches'])
        self.assertEqual(mapped['page_count'], oracle['page_count'])
        self.assertEqual(mapped['normalized_text'], parsed.normalized_text)
        for anchor, paragraph in zip(mapped['paragraphs'], parsed.paragraphs, strict=True):
            self.assertEqual(anchor['document_version'], 7)
            self.assertEqual(anchor['page'], pages[paragraph.paragraph_index])
            self.assertEqual(anchor['quote'], parsed.normalized_text[anchor['start']:anchor['end']])
            self.assertTrue(anchor['locatable'])
            for rect in anchor['rects']:
                self.assertEqual(rect['page'], anchor['page'])
                self.assertTrue(0 <= rect['x'] < rect['x'] + rect['width'] <= 1)
                self.assertTrue(0 <= rect['y'] < rect['y'] + rect['height'] <= 1)
        changed = replace(parsed, normalized_text=parsed.normalized_text + 'changed')
        rejected = map_preview(changed, self.pdf)
        self.assertFalse(rejected['text_matches'])
        self.assertTrue(all(p['page'] is None and not p['rects'] and not p['locatable'] for p in rejected['paragraphs']))

    def test_wrap_duplicate_text_and_unreliable_boundaries(self):
        parsed = parse_docx(package('<w:p><w:r><w:t>甲😀乙</w:t></w:r></w:p><w:p><w:r><w:t>甲😀乙</w:t></w:r></w:p>'), 2)
        def line(text, start, page, index):
            rect = {'page': page, 'x': .1, 'y': .2, 'width': .4, 'height': .05}
            return PdfParagraph(2, index, text, start, start + len(text), page, True, None, (rect,))
        pdf = ParsedPdf(2, '甲😀\n乙\n甲😀乙', 2,
            (line('甲😀', 0, 1, 0), line('乙', 3, 2, 1), line('甲😀乙', 5, 2, 2)))
        with patch('backend.docx_preview.parse_pdf', return_value=pdf):
            result = map_preview(parsed, b'synthetic-pdf')
        self.assertEqual([p['page'] for p in result['paragraphs']], [1, 2])
        self.assertEqual([r['page'] for r in result['paragraphs'][0]['rects']], [1, 2])
        self.assertEqual([p['start'] for p in result['paragraphs']], [0, 4])
        merged = ParsedPdf(2, '甲😀乙甲😀乙', 1, (line('甲😀乙甲😀乙', 0, 1, 0),))
        with patch('backend.docx_preview.parse_pdf', return_value=merged):
            result = map_preview(parsed, b'synthetic-pdf')
        self.assertTrue(result['text_matches'])
        self.assertTrue(all(p['reason'] == 'DOCX_PREVIEW_REGION_UNVERIFIED' for p in result['paragraphs']))

    def test_converter_boundary_success_missing_output_failure_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / 'fake soffice.exe'
            exe.write_bytes(b'not executed')
            def fake_run(command, **kwargs):
                self.assertEqual(command[0], str(exe.resolve()))
                self.assertNotIn('shell', kwargs)
                self.assertEqual(kwargs['timeout'], 60)
                self.assertIn('--headless', command)
                self.assertTrue(command[1].startswith('-env:UserInstallation=file:'))
                self.assertEqual(Path(command[-1]).read_bytes(), self.docx)
                (Path(command[command.index('--outdir') + 1]) / 'source.pdf').write_bytes(self.pdf)
                return SimpleNamespace(returncode=0)
            with patch('backend.docx_preview.subprocess.run', side_effect=fake_run) as run:
                content, mapping = convert_docx(self.docx, 1, executable=exe)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(content, self.pdf)
            self.assertTrue(mapping['text_matches'])
            self.assertEqual(len(mapping['source_sha256']), 64)
            for outcome, code in [(SimpleNamespace(returncode=0), 'DOCX_PREVIEW_FAILED'),
                                  (SimpleNamespace(returncode=1), 'DOCX_PREVIEW_FAILED'),
                                  (subprocess.TimeoutExpired('fake', 60), 'DOCX_PREVIEW_TIMEOUT'),
                                  (OSError('private-path'), 'DOCX_PREVIEW_FAILED')]:
                kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with patch('backend.docx_preview.subprocess.run', **kwargs):
                    with self.assertRaises(ApiError) as error:
                        convert_docx(self.docx, 1, executable=exe)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn('private-path', str(error.exception))
        with patch('backend.docx_preview.find_converter', return_value=None), patch('backend.docx_preview.subprocess.run') as run:
            with self.assertRaises(ApiError) as error:
                convert_docx(self.docx, 1)
            self.assertEqual(error.exception.code, 'DOCX_PREVIEW_DEPENDENCY_MISSING')
            run.assert_not_called()

    def test_external_and_embedded_content_never_runs_converter(self):
        for name, value in [('word/_rels/document.xml.rels', '<Relationships><Relationship TargetMode="External" Target="https://example.test"/></Relationships>'),
                            ('word/embeddings/object.bin', 'embedded'),
                            ('word/vbaProject.bin', 'macro'),
                            ('word/_rels/document.xml.rels', 'invalid-xml')]:
            buffer = io.BytesIO(self.docx)
            with zipfile.ZipFile(buffer, 'a') as archive:
                archive.writestr(name, value)
            with patch('backend.docx_preview.subprocess.run') as run:
                with self.assertRaises(ApiError) as error:
                    convert_docx(buffer.getvalue(), 1)
                self.assertEqual(error.exception.code, 'DOCX_PREVIEW_UNSUPPORTED')
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
