"""Checks for conservative headed-clause extraction and same-version anchors."""

import unittest
from dataclasses import replace

from backend.clause_extractor import CLAUSE_TYPES, extract_clauses
from backend.docx_parser import parse_docx
from backend.mock_pending import synthetic_attachment
from tests.test_docx_parser import package


class ClauseExtractorTests(unittest.TestCase):
    def test_synthetic_clauses_follow_source_order_and_mark_missing(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 2)
        result = extract_clauses(parsed)
        self.assertEqual(
            [item.clause_type for item in result.clauses],
            ["标的", "付款", "验收", "知识产权", "违约", "保密", "争议解决"],
        )
        self.assertEqual(result.missing_types, ("数据安全",))
        self.assertEqual([item.paragraph_index for item in result.clauses], list(range(5, 12)))
        for item in result.clauses:
            self.assertEqual(item.document_version, 2)
            self.assertEqual(parsed.normalized_text[item.start:item.end], item.quote)
            self.assertIsNone(item.page)
            self.assertFalse(item.locatable)
            self.assertEqual(item.reason, "PREVIEW_NOT_AVAILABLE")
            self.assertEqual(item.rects, ())

    def test_numbered_heading_continuation_and_unrelated_article(self) -> None:
        parsed = parse_docx(
            package(
                "<w:p><w:r><w:t>第1条 付款</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>分两期支付。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>第二条 签署</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>此处提到保密但不是保密条款。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>3. 数据安全：双方保护测试数据。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>保密：不得披露信息。</w:t></w:r></w:p>"
            ),
            4,
        )
        result = extract_clauses(parsed)
        self.assertEqual([c.clause_type for c in result.clauses], ["付款", "数据安全", "保密"])
        self.assertEqual(result.clauses[0].quote, "第1条 付款\n分两期支付。")
        self.assertNotIn("此处提到保密", result.clauses[0].quote)
        self.assertEqual(result.missing_types, tuple(k for k in CLAUSE_TYPES if k not in {"付款", "数据安全", "保密"}))

    def test_duplicate_clause_and_metadata_boundary(self) -> None:
        parsed = parse_docx(
            package(
                "<w:p><w:r><w:t>付款：预付款。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>采购金额：人民币十元</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>付款：尾款。</w:t></w:r></w:p>"
            ),
            1,
        )
        result = extract_clauses(parsed)
        self.assertEqual([c.quote for c in result.clauses], ["付款：预付款。", "付款：尾款。"])

    def test_clause_word_at_sentence_start_is_not_a_heading(self) -> None:
        parsed = parse_docx(
            package("<w:p><w:r><w:t>付款 是合同履行的一部分，但未列付款条款。</w:t></w:r></w:p>"),
            1,
        )
        self.assertEqual(extract_clauses(parsed).clauses, ())

    def test_inconsistent_input_cannot_create_false_anchor(self) -> None:
        parsed = parse_docx(synthetic_attachment(), 1)
        bad = replace(parsed, paragraphs=(replace(parsed.paragraphs[0], document_version=9),))
        with self.assertRaises(ValueError):
            extract_clauses(bad)


if __name__ == "__main__":
    unittest.main()
