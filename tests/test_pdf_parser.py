"""Standalone F2 text-PDF parser smoke against the checked-in oracle."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from backend.pdf_parser import PdfParseError, parse_pdf


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class PdfParserSmokeTests(unittest.TestCase):
    def test_f2_text_pdf_parser_smoke(self) -> None:
        oracle = json.loads((SAMPLES / "f2_expected.json").read_text(encoding="utf-8"))
        f1 = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])

        parsed = parse_pdf(content, oracle["document_version"])
        self.assertEqual((parsed.document_version, parsed.page_count), (1, oracle["page_count"]))
        self.assertEqual(parsed.normalized_text, "\n".join(row[3] for row in f1["paragraphs"]))
        self.assertEqual(len(parsed.paragraphs), len(f1["paragraphs"]))
        page_by_index = {index: row["page"] for row in oracle["pages"]
                         for index in row["paragraph_indexes"]}
        for paragraph, (index, start, end, quote) in zip(
                parsed.paragraphs, f1["paragraphs"], strict=True):
            self.assertEqual((paragraph.paragraph_index, paragraph.start, paragraph.end,
                              paragraph.quote, paragraph.page),
                             (index, start, end, quote, page_by_index[index]))
            self.assertEqual(parsed.normalized_text[start:end], quote)
            self.assertTrue(paragraph.locatable)
            self.assertIsNone(paragraph.reason)
            self.assertEqual(len(paragraph.rects), 1)
            rect = paragraph.rects[0]
            self.assertEqual(rect["page"], paragraph.page)
            self.assertTrue(0 <= rect["x"] < rect["x"] + rect["width"] <= 1)
            self.assertTrue(0 <= rect["y"] < rect["y"] + rect["height"] <= 1)
            self.assertAlmostEqual(rect["x"], 48 / 595, places=4)

        for name, index, start, end, quote in f1["clauses"]:
            self.assertEqual(parsed.normalized_text[start:end], quote)
            self.assertEqual(parsed.paragraphs[index].page, oracle["clause_pages"][name])
        for name in f1["missing_clause_types"]:
            self.assertIsNone(oracle["clause_pages"][name])

        encrypted = (SAMPLES / "f5-encrypted.pdf").read_bytes()
        with self.assertRaises(PdfParseError) as caught:
            parse_pdf(encrypted, 1)
        self.assertEqual(caught.exception.code, "PDF_ENCRYPTED")
        for bad_content in (b"", b"not a pdf", b"%PDF-1.4\ninvalid"):
            with self.subTest(content=bad_content[:16]):
                with self.assertRaises(PdfParseError) as caught:
                    parse_pdf(bad_content, 1)
                self.assertEqual(caught.exception.code, "PDF_UNREADABLE")
        with self.assertRaises(ValueError):
            parse_pdf(content, 0)


if __name__ == "__main__":
    unittest.main()
