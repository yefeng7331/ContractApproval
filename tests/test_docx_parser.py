"""DOCX body extraction and Unicode span checks with synthetic packages."""

import io
import unittest
import zipfile

from backend.docx_parser import DocxParseError, parse_docx
from backend.mock_pending import synthetic_attachment


def package(body: str) -> bytes:
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


class DocxParserTests(unittest.TestCase):
    def test_paragraph_order_and_unicode_offsets(self) -> None:
        content = package(
            '<w:p><w:r><w:t>甲😀</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>  </w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:hyperlink><w:r><w:t>付é款</w:t>'
            '</w:r></w:hyperlink><w:r><w:tab/><w:t>十元</w:t><w:br/>'
            '<w:t>截止</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        )
        parsed = parse_docx(content, 3)
        self.assertEqual(parsed.normalized_text, "甲😀\n付é款\t十元\n截止")
        self.assertEqual(
            [(p.paragraph_index, p.start, p.end, p.quote) for p in parsed.paragraphs],
            [(0, 0, 2, "甲😀"), (2, 3, 12, "付é款\t十元\n截止")],
        )
        for paragraph in parsed.paragraphs:
            self.assertEqual(parsed.normalized_text[paragraph.start:paragraph.end], paragraph.quote)
            self.assertEqual(paragraph.document_version, 3)
            self.assertIsNone(paragraph.page)
            self.assertFalse(paragraph.locatable)
            self.assertEqual(paragraph.reason, "PREVIEW_NOT_AVAILABLE")
            self.assertEqual(paragraph.rects, ())

    def test_synthetic_pending_attachment_has_nonempty_text(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 1)
        self.assertEqual(len(parsed.paragraphs), 12)
        self.assertIn("合同编号：SYN-2026-001", parsed.normalized_text)
        self.assertEqual(parsed.paragraphs[-1].paragraph_index, 11)

    def test_empty_and_unreadable_docx_report_specific_errors(self) -> None:
        cases = [
            (package("<w:p><w:r><w:t>  </w:t></w:r></w:p>"), "DOCX_EMPTY"),
            (package(""), "DOCX_EMPTY"),
            (b"not a DOCX", "DOCX_UNREADABLE"),
            (package("<w:p>"), "DOCX_UNREADABLE"),
        ]
        for content, code in cases:
            with self.subTest(code=code, length=len(content)):
                with self.assertRaises(DocxParseError) as caught:
                    parse_docx(content, 1)
                self.assertEqual(caught.exception.code, code)

    def test_rejects_invalid_version(self) -> None:
        with self.assertRaises(ValueError):
            parse_docx(synthetic_attachment(), 0)

    def test_rejects_entity_declarations(self) -> None:
        xml = (
            '<!DOCTYPE w:document [<!ENTITY fake "text">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>&fake;</w:t></w:r></w:p></w:body>'
            '</w:document>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", xml)
        with self.assertRaises(DocxParseError) as caught:
            parse_docx(output.getvalue(), 1)
        self.assertEqual(caught.exception.code, "DOCX_UNREADABLE")


if __name__ == "__main__":
    unittest.main()
