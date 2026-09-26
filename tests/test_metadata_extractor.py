"""Synthetic DOCX metadata extraction and source-anchor checks."""

import unittest
from dataclasses import replace
from xml.sax.saxutils import escape

from backend.docx_parser import parse_docx
from backend.metadata_extractor import FIELD_NAMES, extract_metadata
from backend.mock_pending import synthetic_attachment
from tests.test_docx_parser import package


def parsed_paragraphs(*texts: str, version: int = 2):
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in texts)
    return parse_docx(package(body), version)


class MetadataExtractorTests(unittest.TestCase):
    def test_heading_suffix_spacing_preserves_source_anchor(self) -> None:
        for heading in ("合成软件采购合同 (仅供演示，非真实交易)",
                        "合成软件采购合同　（仅供演示）"):
            parsed = parsed_paragraphs(heading)
            field = extract_metadata(parsed).get("title")
            self.assertEqual(field.value, parsed.paragraphs[0].quote)
            self.assertEqual(parsed.normalized_text[field.anchor.start:field.anchor.end], field.value)
        parsed = parsed_paragraphs("软件采购合同 已经完成签署")
        self.assertIsNone(extract_metadata(parsed).get("title").value)

    def test_synthetic_fields_and_exact_anchors(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 3)
        result = extract_metadata(parsed)
        self.assertEqual(tuple(field.name for field in result.fields), FIELD_NAMES)
        expected = {
            "title": "合成软件采购合同（仅供演示，非真实交易）",
            "contract_number": "SYN-2026-001",
            "department": "采购部",
            "applicant": "张三",
            "buyer": "甲方演示科技有限公司",
            "supplier": "乙方演示软件有限公司",
            "amount": "100000",
            "currency": "人民币",
            "performance_term": "2026年10月1日至2026年12月31日",
        }
        for name, value in expected.items():
            field = result.get(name)
            self.assertEqual(field.status, "identified", name)
            self.assertEqual(field.value, value, name)
            self.assertIsNotNone(field.anchor, name)
            anchor = field.anchor
            self.assertEqual(anchor.document_version, 3)
            self.assertEqual(parsed.normalized_text[anchor.start:anchor.end], value)
            self.assertEqual(anchor.quote, value)
            paragraph = next(
                p for p in parsed.paragraphs if p.paragraph_index == anchor.paragraph_index
            )
            self.assertIn(value, paragraph.quote)
            self.assertIsNone(anchor.page)
            self.assertFalse(anchor.locatable)
            self.assertEqual(anchor.reason, "PREVIEW_NOT_AVAILABLE")
            self.assertEqual(anchor.rects, ())
        for name in ("buyer_credit_code", "supplier_credit_code", "effective_conditions"):
            field = result.get(name)
            self.assertEqual((field.status, field.value, field.anchor, field.reason),
                             ("unrecognized", None, None, "NOT_FOUND"))

    def test_explicit_credit_codes_conditions_and_amount(self) -> None:
        parsed = parsed_paragraphs(
            "软件采购合同",
            "采购方统一社会信用代码：91310000MA12345678；供应商统一社会信用代码：91310000MA87654321",
            "合同金额：CNY 10,000.50元；生效条件：双方签字盖章",
        )
        result = extract_metadata(parsed)
        self.assertEqual(result.get("buyer_credit_code").value, "91310000MA12345678")
        self.assertEqual(result.get("supplier_credit_code").value, "91310000MA87654321")
        self.assertEqual(result.get("amount").value, "10,000.50")
        self.assertEqual(result.get("currency").value, "CNY")
        self.assertEqual(result.get("effective_conditions").value, "双方签字盖章")
        for name in ("buyer_credit_code", "supplier_credit_code", "amount", "currency", "effective_conditions"):
            anchor = result.get(name).anchor
            self.assertEqual(parsed.normalized_text[anchor.start:anchor.end], anchor.quote)

    def test_unlabelled_prose_placeholders_and_conflict_remain_unknown(self) -> None:
        parsed = parsed_paragraphs(
            "本合同提到甲方与付款金额，但没有明确字段。",
            "合同编号：A-1；合同编号：B-2",
            "生效条件：未约定；采购金额：待定",
            "供应商统一社会信用代码：12345",
            "金额：1000元；附注：人民币只是说明",
        )
        result = extract_metadata(parsed)
        self.assertEqual(result.get("title").status, "unrecognized")
        self.assertEqual(result.get("buyer").status, "unrecognized")
        self.assertEqual(result.get("contract_number").reason, "AMBIGUOUS_VALUES")
        self.assertEqual(result.get("effective_conditions").status, "unrecognized")
        self.assertEqual(result.get("supplier_credit_code").status, "unrecognized")
        self.assertEqual(result.get("amount").value, "1000")
        self.assertEqual(result.get("currency").status, "unrecognized")

    def test_inline_party_credit_code_does_not_pollute_party_name(self) -> None:
        parsed = parsed_paragraphs(
            "采购方：甲方科技有限公司（统一社会信用代码：91310000MA12345678）；"
            "供应商：乙方软件有限公司，统一社会信用代码：错误代码"
        )
        result = extract_metadata(parsed)
        self.assertEqual(result.get("buyer").value, "甲方科技有限公司")
        self.assertEqual(result.get("buyer_credit_code").value, "91310000MA12345678")
        self.assertEqual(result.get("supplier").value, "乙方软件有限公司")
        self.assertEqual(result.get("supplier_credit_code").status, "unrecognized")
        code_anchor = result.get("buyer_credit_code").anchor
        self.assertEqual(parsed.normalized_text[code_anchor.start:code_anchor.end], code_anchor.quote)

    def test_inconsistent_version_or_span_is_rejected(self) -> None:
        parsed = parsed_paragraphs("合同编号：A-1")
        bad_version = replace(parsed, paragraphs=(replace(parsed.paragraphs[0], document_version=9),))
        with self.assertRaises(ValueError):
            extract_metadata(bad_version)
        bad_quote = replace(parsed, paragraphs=(replace(parsed.paragraphs[0], quote="合同编号：B-2"),))
        with self.assertRaises(ValueError):
            extract_metadata(bad_quote)

    def test_paragraph_index_tracks_word_body_when_blank_paragraph_is_skipped(self) -> None:
        parsed = parsed_paragraphs("", "合同编号：A-1")
        self.assertEqual(len(parsed.paragraphs), 1)
        field = extract_metadata(parsed).get("contract_number")
        self.assertEqual(field.anchor.paragraph_index, 1)
        self.assertEqual(parsed.normalized_text[field.anchor.start:field.anchor.end], "A-1")


if __name__ == "__main__":
    unittest.main()
