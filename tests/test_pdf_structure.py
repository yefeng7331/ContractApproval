"""PDF structure mapping boundaries independent of fixed layout."""

import unittest
from dataclasses import replace

from backend.pdf_parser import ParsedPdf, PdfParagraph
from backend.pdf_structure import extract_pdf_structure
from tests.test_pdf_job import SAMPLES
from backend.pdf_parser import parse_pdf


class PdfStructureTests(unittest.TestCase):
    def test_legacy_pdf_rows_remain_unstructured(self):
        import tempfile
        from pathlib import Path
        from backend.auth import AuthStore
        from backend.tasks import TaskStore
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(Path(directory) / "old.sqlite3")
            try:
                store.initialize()
                with store.connection:
                    store.connection.execute("""CREATE TABLE parsed_documents (
                        task_id TEXT, document_version INTEGER, normalized_text TEXT,
                        paragraphs_json TEXT, fields_json TEXT, clauses_json TEXT,
                        missing_clause_types_json TEXT, created_at TEXT, page_count INTEGER)""")
                    store.connection.execute("INSERT INTO parsed_documents VALUES ('old-pdf', 1, 'original', '[]', '[]', '[]', '[]', 'old', 3)")
                    store.connection.execute("INSERT INTO parsed_documents VALUES ('old-docx', 1, 'original', '[]', '[]', '[]', '[]', 'old', NULL)")
                tasks = TaskStore(store, Path(directory) / "uploads")
                tasks.initialize()
                tasks.initialize()
                rows = store.connection.execute("SELECT task_id, normalized_text, structured_extraction_status FROM parsed_documents ORDER BY task_id").fetchall()
                self.assertEqual([tuple(row) for row in rows], [
                    ("old-docx", "original", "available"),
                    ("old-pdf", "original", "not_implemented"),
                ])
            finally:
                store.close()

    def test_cross_page_clause_and_unreliable_region(self):
        lines = ("付款：软件到货后，", "甲方一次性支付全部合同价款。")
        paragraphs = []
        offset = 0
        for index, quote in enumerate(lines):
            rect = {"page": index + 1, "x": .1, "y": .1, "width": .7, "height": .1}
            paragraphs.append(PdfParagraph(2, index, quote, offset, offset + len(quote),
                                            index + 1, True, None, (rect,)))
            offset += len(quote) + 1
        parsed = ParsedPdf(2, "\n".join(lines), 2, tuple(paragraphs))
        _, clauses = extract_pdf_structure(parsed)
        self.assertEqual(clauses.clauses[0].quote, parsed.normalized_text)
        self.assertEqual([r["page"] for r in clauses.clauses[0].rects], [1, 2])
        bad = replace(paragraphs[1], locatable=False, rects=(), reason="PDF_REGION_UNRELIABLE")
        _, clauses = extract_pdf_structure(replace(parsed, paragraphs=(paragraphs[0], bad)))
        self.assertFalse(clauses.clauses[0].locatable)
        self.assertEqual(clauses.clauses[0].rects, ())

    def test_values_and_clauses_match_fixed_oracle(self):
        import json
        parsed = parse_pdf((SAMPLES / "f2-text-software-purchase.pdf").read_bytes(), 1)
        metadata, clauses = extract_pdf_structure(parsed)
        expected = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        self.assertEqual(len(metadata.fields), 12)
        # Oracle values are checked separately from extraction output.
        for name, value in (("contract_number", "SYN-2026-001"), ("amount", "100000"), ("currency", "人民币")):
            self.assertEqual(metadata.get(name).value, value)
        self.assertEqual([c.quote for c in clauses.clauses], [c[4] for c in expected["clauses"]])
