"""Standalone smoke tests for checked-in synthetic contract fixtures."""

import hashlib
import json
import re
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth import AuthStore
from backend.clause_extractor import extract_clauses
from backend.demo_rules import evaluate_demo_rules
from backend.docx_job import run_docx_once
from backend.docx_parser import DocxParseError, parse_docx
from backend.main import create_app
from backend.metadata_extractor import extract_metadata
from backend.mock_pending import synthetic_attachment, synthetic_revised_attachment


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def read_grayscale_png(content: bytes) -> tuple[int, int, list[bytes]]:
    """Decode the fixed scan's 8-bit grayscale PNG without an OCR dependency."""
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("Invalid PNG signature")
    offset, compressed, dimensions, ended = 8, bytearray(), None, False
    while offset < len(content):
        if offset + 12 > len(content):
            raise AssertionError("Truncated PNG chunk")
        size = struct.unpack_from(">I", content, offset)[0]
        kind = content[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(content):
            raise AssertionError("Truncated PNG data")
        data = content[offset + 8:offset + 8 + size]
        crc = struct.unpack_from(">I", content, offset + 8 + size)[0]
        if zlib.crc32(kind + data) != crc:
            raise AssertionError("Invalid PNG checksum")
        if kind in (b"tEXt", b"iTXt", b"zTXt"):
            raise AssertionError("F3 scan must have no embedded text metadata")
        if kind == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if (depth, color, compression, filtering, interlace) != (8, 0, 0, 0, 0):
                raise AssertionError("F3 scan must be non-interlaced grayscale")
            dimensions = (width, height)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            ended = True
            if end != len(content):
                raise AssertionError("Data after PNG end")
        offset = end
    if dimensions is None or not ended:
        raise AssertionError("Incomplete PNG")
    width, height = dimensions
    raw = zlib.decompress(compressed)
    if len(raw) != height * (width + 1):
        raise AssertionError("Unexpected PNG image length")
    rows = []
    previous = bytes(width)
    for y in range(height):
        start = y * (width + 1)
        filter_type = raw[start]
        row = bytearray(raw[start + 1:start + 1 + width])
        if filter_type not in range(5):
            raise AssertionError("Unknown PNG filter")
        for x in range(width):
            left = row[x - 1] if x else 0
            above = previous[x]
            upper_left = previous[x - 1] if x else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        previous = bytes(row)
        rows.append(previous)
    return width, height, rows


def read_f2_fixture_pages(content: bytes) -> list[list[str]]:
    """Decode this fixture's plain PDF objects and explicit ToUnicode map.

    This is a fixture integrity check, not the future general PDF parser.
    """
    if not content.startswith(b"%PDF-1.4\n") or not content.endswith(b"%%EOF\n"):
        raise AssertionError("Invalid F2 PDF envelope")
    objects = {int(match[1]): match[2] for match in re.finditer(
        rb"(?ms)^(\d+) 0 obj\n(.*?)\nendobj\n", content
    )}
    if not objects or b"/FontFile2 " not in content or b"/ToUnicode " not in content:
        raise AssertionError("F2 needs an embedded TrueType font and ToUnicode map")
    cmap_id = int(re.search(rb"/ToUnicode (\d+) 0 R", content)[1])
    cmap = {int(cid, 16): bytes.fromhex(code.decode("ascii")).decode("utf-16-be")
            for cid, code in re.findall(rb"<([0-9A-F]{4})> <([0-9A-F]{4})>", objects[cmap_id])}
    if not cmap:
        raise AssertionError("F2 ToUnicode map is empty")
    pages = []
    for number in sorted(objects):
        page = objects[number]
        if b"/Type /Page " not in page:
            continue
        content_id = int(re.search(rb"/Contents (\d+) 0 R", page)[1])
        lines = []
        for encoded in re.findall(rb"<([0-9A-F]+)> Tj", objects[content_id]):
            glyphs = bytes.fromhex(encoded.decode("ascii"))
            if len(glyphs) % 2:
                raise AssertionError("Odd-length CID stream")
            lines.append("".join(cmap[int.from_bytes(glyphs[pos:pos + 2], "big")]
                                 for pos in range(0, len(glyphs), 2)))
        pages.append(lines)
    return pages


class FixedSampleSmokeTests(unittest.TestCase):
    def test_f5_blurred_scan_fixed_sample_smoke(self) -> None:
        """The severe-blur fixture is valid but cannot yet be classified by OCR."""
        oracle = json.loads((SAMPLES / "f5_blurred_expected.json").read_text(encoding="utf-8"))
        self.assertEqual((oracle["schema_version"], oracle["sample_id"]),
                         (1, "F5-severe-blur-scan"))
        self.assertEqual((oracle["document_version"], oracle["page_count"]), (1, 1))
        self.assertEqual((oracle["expected_machine_status_after_ocr"],
                          oracle["expected_recovery_action_after_ocr"]),
                         ("blocked", "replace_attachment"))
        self.assertEqual((oracle["expected_parsed_document_count_after_ocr"],
                          oracle["expected_risk_draft_count_after_ocr"]), (0, 0))
        self.assertEqual((oracle["current_machine_status"], oracle["ocr_status"]),
                         ("pending", "NOT_IMPLEMENTED"))
        source = (SAMPLES / oracle["source_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), oracle["source_sha256"])
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        width, height, rows = read_grayscale_png(content)
        self.assertEqual([width, height], oracle["image_size"])
        self.assertEqual(oracle["fixture_effect"], "severe_gaussian_blur")
        self.assertGreaterEqual(min(min(row) for row in rows), 220)
        self.assertLess(min(min(row) for row in rows), 245)
        self.assertEqual(max(max(row) for row in rows), 250)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f5-blur-smoke.sqlite3")
            store.initialize()
            try:
                for name, role in (("f5-blur-owner", "business"),
                                   ("f5-blur-other", "business"),
                                   ("f5-blur-legal", "legal")):
                    store.create_user(name, role, "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(username: str) -> dict[str, str]:
                        response = client.post("/api/v1/sessions", json={
                            "username": username, "password": "synthetic-password"})
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}

                    owner, other, legal = (login(name) for name in
                                           ("f5-blur-owner", "f5-blur-other", "f5-blur-legal"))
                    created = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "Synthetic", "applicant": "F5"},
                                          files={"file": (oracle["file"], content, "image/png")})
                    self.assertEqual(created.status_code, 201, created.text)
                    task_id = created.json()["task_id"]
                    state = client.get(f"/api/v1/tasks/{task_id}", headers=owner)
                    self.assertEqual(state.status_code, 200, state.text)
                    self.assertEqual((state.json()["document_version"],
                                      state.json()["machine_status"]), (1, "pending"))
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}").status_code, 401)
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code, 404)
                    for endpoint in ("document", "risks"):
                        response = client.get(f"/api/v1/tasks/{task_id}/{endpoint}", headers=legal)
                        self.assertEqual((response.status_code, response.json()["code"]),
                                         (409, "DOCUMENT_NOT_READY"))
                    for table in ("parsed_documents", "rule_draft_snapshots"):
                        self.assertEqual(store.connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task_id,)
                        ).fetchone()[0], 0)
                    invalid = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "Synthetic", "applicant": "F5"},
                                          files={"file": ("invalid.png", b"not-a-png", "image/png")})
                    self.assertEqual((invalid.status_code, invalid.json()["code"]),
                                     (422, "INVALID_FILE"))
            finally:
                store.close()

    def test_f3_clear_scan_fixed_sample_smoke(self) -> None:
        """F3 has a real raster page and fixed source-image coordinate oracle."""
        oracle = json.loads((SAMPLES / "f3_expected.json").read_text(encoding="utf-8"))
        f1 = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        self.assertEqual((oracle["schema_version"], oracle["sample_id"]), (1, "F3-clear-scan"))
        self.assertEqual((oracle["document_version"], oracle["page_count"]), (1, 1))
        self.assertEqual(oracle["ocr_status"], "NOT_IMPLEMENTED")
        self.assertEqual(oracle["preview_regions_status"], "UNVERIFIED")
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        width, height, rows = read_grayscale_png(content)
        self.assertEqual([width, height], oracle["image_size"])
        self.assertEqual([box[0] for box in oracle["paragraph_boxes"]], list(range(12)))
        allowed = [None] * height
        for index, x0, y0, x1, y1 in oracle["paragraph_boxes"]:
            self.assertTrue(0 < x0 < x1 < width and 0 < y0 < y1 < height)
            self.assertEqual(f1["paragraphs"][index][0], index)
            self.assertGreater(sum(pixel < 128 for row in rows[y0:y1]
                                   for pixel in row[x0:x1]), 100)
            for y in range(y0, y1):
                self.assertIsNone(allowed[y], "Paragraph boxes overlap")
                allowed[y] = (x0, x1)
        for y, row in enumerate(rows):
            bounds = allowed[y]
            if bounds is None:
                self.assertFalse(any(pixel < 128 for pixel in row))
            else:
                x0, x1 = bounds
                self.assertFalse(any(pixel < 128 for pixel in row[:x0] + row[x1:]))

        normalized_text = "\n".join(item[3] for item in f1["paragraphs"])
        for index, start, end, quote in f1["paragraphs"]:
            self.assertEqual(normalized_text[start:end], quote)
        self.assertEqual(set(oracle["field_pages"]), set(f1["fields"]))
        for name, field in f1["fields"].items():
            self.assertEqual(oracle["field_pages"][name], 1 if field else None)
            if field:
                self.assertEqual(normalized_text[field[2]:field[3]], field[0])
                self.assertIn(field[1], [box[0] for box in oracle["paragraph_boxes"]])
        self.assertEqual(set(oracle["clause_pages"]),
                         {clause[0] for clause in f1["clauses"]} | set(f1["missing_clause_types"]))
        for name, index, start, end, quote in f1["clauses"]:
            self.assertEqual(oracle["clause_pages"][name], 1)
            self.assertEqual(normalized_text[start:end], quote)
            self.assertIn(index, [box[0] for box in oracle["paragraph_boxes"]])
        for name in f1["missing_clause_types"]:
            self.assertIsNone(oracle["clause_pages"][name])
        self.assertEqual(oracle["enabled_rule_risk_summary"], f1["enabled_rule_risk_summary"])
        self.assertEqual(oracle["machine_suggestion"], f1["machine_suggestion"])
        for risk, expected in zip(oracle["risks"], f1["risks"], strict=True):
            for key in ("rule_id", "rule_version", "risk_level", "suggestion", "anchor_clause_types"):
                self.assertEqual(risk[key], expected[key])
            self.assertEqual(risk["anchor_pages"], [1] * len(expected["anchor_clause_types"]))
            self.assertEqual(risk["anchor_paragraph_indexes"], [
                clause[1] for name in expected["anchor_clause_types"]
                for clause in f1["clauses"] if clause[0] == name
            ])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f3-smoke.sqlite3")
            store.initialize()
            try:
                for name, role in (("f3-owner", "business"), ("f3-other", "business"),
                                   ("f3-legal", "legal")):
                    store.create_user(name, role, "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(username: str) -> dict[str, str]:
                        response = client.post("/api/v1/sessions", json={
                            "username": username, "password": "synthetic-password"})
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}

                    owner, other, legal = (login(name) for name in
                                           ("f3-owner", "f3-other", "f3-legal"))
                    created = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "采购部", "applicant": "合成用户"},
                                          files={"file": (oracle["file"], content, "image/png")})
                    self.assertEqual(created.status_code, 201, created.text)
                    task_id = created.json()["task_id"]
                    state = client.get(f"/api/v1/tasks/{task_id}", headers=owner)
                    self.assertEqual(state.status_code, 200, state.text)
                    self.assertEqual((state.json()["document_version"], state.json()["machine_status"]),
                                     (1, "pending"))
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code, 404)
                    for endpoint in ("document", "risks"):
                        response = client.get(f"/api/v1/tasks/{task_id}/{endpoint}", headers=legal)
                        self.assertEqual((response.status_code, response.json()["code"]),
                                         (409, "DOCUMENT_NOT_READY"))
                    for table in ("parsed_documents", "rule_draft_snapshots"):
                        self.assertEqual(store.connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task_id,)
                        ).fetchone()[0], 0)
                    invalid = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "采购部", "applicant": "合成用户"},
                                          files={"file": ("invalid.png", b"not-a-png", "image/png")})
                    self.assertEqual((invalid.status_code, invalid.json()["code"]),
                                     (422, "INVALID_FILE"))
            finally:
                store.close()

    def test_f2_text_pdf_fixed_sample_smoke(self) -> None:
        """F2 has the F1 contract text but its own three-page evidence map."""
        oracle = json.loads((SAMPLES / "f2_expected.json").read_text(encoding="utf-8"))
        f1 = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))["samples"]["F1"]
        self.assertEqual((oracle["schema_version"], oracle["sample_id"]), (1, "F2-text-pdf"))
        self.assertEqual(oracle["document_version"], 1)
        self.assertEqual(oracle["pdf_parser_status"], "COMPONENT_PENDING_ACCEPTANCE")
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        pages = read_f2_fixture_pages(content)
        self.assertEqual(len(pages), oracle["page_count"])
        indexes = [index for page in oracle["pages"] for index in page["paragraph_indexes"]]
        self.assertEqual(indexes, list(range(len(f1["paragraphs"]))))
        for page, actual in zip(oracle["pages"], pages):
            self.assertEqual(actual, [f1["paragraphs"][index][3]
                                      for index in page["paragraph_indexes"]])
        paragraph_page = {index: page["page"] for page in oracle["pages"]
                          for index in page["paragraph_indexes"]}
        normalized_text = "\n".join(line for page in pages for line in page)
        for index, start, end, quote in f1["paragraphs"]:
            self.assertEqual(normalized_text[start:end], quote)
            self.assertIn(paragraph_page[index], (1, 2, 3))
        self.assertEqual(set(oracle["field_pages"]), set(f1["fields"]))
        for name, field in f1["fields"].items():
            self.assertEqual(oracle["field_pages"][name],
                             paragraph_page[field[1]] if field else None)
            if field:
                self.assertEqual(normalized_text[field[2]:field[3]], field[0])
        self.assertEqual(set(oracle["clause_pages"]),
                         {clause[0] for clause in f1["clauses"]} | set(f1["missing_clause_types"]))
        for name, index, start, end, quote in f1["clauses"]:
            self.assertEqual(oracle["clause_pages"][name], paragraph_page[index])
            self.assertEqual(normalized_text[start:end], quote)
        for name in f1["missing_clause_types"]:
            self.assertIsNone(oracle["clause_pages"][name])
        self.assertEqual(oracle["enabled_rule_risk_summary"], f1["enabled_rule_risk_summary"])
        self.assertEqual(oracle["machine_suggestion"], f1["machine_suggestion"])
        self.assertEqual(len(oracle["risks"]), 2)
        for actual, target in zip(oracle["risks"], f1["risks"]):
            for key in ("rule_id", "rule_version", "risk_level", "suggestion", "anchor_clause_types"):
                self.assertEqual(actual[key], target[key])
            self.assertEqual(actual["anchor_pages"],
                             [oracle["clause_pages"][name] for name in actual["anchor_clause_types"]])
        self.assertEqual([oracle["clause_pages"][name]
                          for name in ("付款", "验收", "知识产权")], [2, 2, 3])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f2-smoke.sqlite3")
            store.initialize()
            try:
                store.create_user("f2-owner", "business", "synthetic-password")
                store.create_user("f2-other", "business", "synthetic-password")
                store.create_user("f2-legal", "legal", "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(username: str) -> dict[str, str]:
                        response = client.post("/api/v1/sessions", json={
                            "username": username, "password": "synthetic-password"})
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}

                    owner, other, legal = (login(name) for name in ("f2-owner", "f2-other", "f2-legal"))
                    created = client.post("/api/v1/tasks", headers=owner,
                                          data={"department": "采购部", "applicant": "合成用户"},
                                          files={"file": (oracle["file"], content, "application/pdf")})
                    self.assertEqual(created.status_code, 201, created.text)
                    task_id = created.json()["task_id"]
                    state = client.get(f"/api/v1/tasks/{task_id}", headers=owner)
                    self.assertEqual(state.status_code, 200, state.text)
                    self.assertEqual(state.json()["machine_status"], "pending")
                    self.assertEqual(state.json()["document_version"], 1)
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code, 404)
                    pending = client.get(f"/api/v1/tasks/{task_id}/document", headers=legal)
                    self.assertEqual((pending.status_code, pending.json()["code"]),
                                     (409, "DOCUMENT_NOT_READY"))
                    risks = client.get(f"/api/v1/tasks/{task_id}/risks", headers=legal)
                    self.assertEqual((risks.status_code, risks.json()["code"]),
                                     (409, "DOCUMENT_NOT_READY"))
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], 0)
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM rule_draft_snapshots WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], 0)
            finally:
                store.close()

    def test_f1_f4_fixed_sample_smoke(self) -> None:
        expected = json.loads((SAMPLES / "f1_f4_expected.json").read_text(encoding="utf-8"))
        self.assertEqual(expected["schema_version"], 1)
        self.assertEqual(expected["preview_status"], "UNVERIFIED")
        self.assertEqual(set(expected["samples"]), {"F1", "F4"})

        for sample_id, source in (
            ("F1", synthetic_attachment()),
            ("F4", synthetic_revised_attachment()),
        ):
            with self.subTest(sample=sample_id):
                oracle = expected["samples"][sample_id]
                content = (SAMPLES / oracle["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
                parsed = parse_docx(content, oracle["document_version"])
                # The generator writes ZIP timestamps, so compare contract text, not archive bytes.
                self.assertEqual(
                    parse_docx(source, oracle["document_version"]).normalized_text,
                    parsed.normalized_text,
                )
                paragraphs = [
                    [item.paragraph_index, item.start, item.end, item.quote]
                    for item in parsed.paragraphs
                ]
                self.assertEqual(paragraphs, oracle["paragraphs"])
                self.assertEqual(
                    parsed.normalized_text,
                    "\n".join(item[3] for item in oracle["paragraphs"]),
                )
                for paragraph in parsed.paragraphs:
                    self.assertEqual(parsed.normalized_text[paragraph.start:paragraph.end], paragraph.quote)
                    self.assertIsNone(paragraph.page)
                    self.assertFalse(paragraph.locatable)
                    self.assertEqual(paragraph.reason, "PREVIEW_NOT_AVAILABLE")

                metadata = extract_metadata(parsed)
                self.assertEqual({field.name for field in metadata.fields}, set(oracle["fields"]))
                for field in metadata.fields:
                    target = oracle["fields"][field.name]
                    if target is None:
                        self.assertEqual(field.status, "unrecognized")
                        self.assertIsNone(field.anchor)
                        self.assertIsNone(field.value)
                    else:
                        quote, paragraph_index, start, end = target
                        self.assertEqual(field.status, "identified")
                        self.assertEqual(field.value, quote)
                        self.assertEqual(
                            [field.anchor.paragraph_index, field.anchor.start, field.anchor.end],
                            [paragraph_index, start, end],
                        )
                        self.assertEqual(parsed.normalized_text[start:end], quote)
                        self.assertIsNone(field.anchor.page)
                        self.assertFalse(field.anchor.locatable)

                clauses = extract_clauses(parsed)
                self.assertEqual(
                    [
                        [item.clause_type, item.paragraph_index, item.start, item.end, item.quote]
                        for item in clauses.clauses
                    ],
                    oracle["clauses"],
                )
                self.assertEqual(list(clauses.missing_types), oracle["missing_clause_types"])
                for clause in clauses.clauses:
                    self.assertEqual(parsed.normalized_text[clause.start:clause.end], clause.quote)
                    self.assertIsNone(clause.page)
                    self.assertFalse(clause.locatable)
                    self.assertEqual(clause.reason, "PREVIEW_NOT_AVAILABLE")

                rules = evaluate_demo_rules(parsed, clauses)
                self.assertEqual(rules["document_version"], oracle["document_version"])
                self.assertEqual(rules["enabled_rule_risk_summary"], oracle["enabled_rule_risk_summary"])
                self.assertEqual(rules["machine_suggestion"], oracle["machine_suggestion"])
                self.assertEqual(len(rules["risks"]), len(oracle["risks"]))
                for risk, target in zip(rules["risks"], oracle["risks"]):
                    for key in ("rule_id", "rule_version", "risk_level", "suggestion"):
                        self.assertEqual(risk[key], target[key])
                    self.assertEqual(risk["source"], "rule")
                    self.assertEqual(risk["status"], "machine_draft")
                    self.assertEqual(risk["legal_basis_status"], "pending_legal_verification")
                    self.assertEqual(
                        [anchor["clause_type"] for anchor in risk["anchors"]],
                        target["anchor_clause_types"],
                    )
                    for anchor in risk["anchors"]:
                        self.assertEqual(anchor["document_version"], oracle["document_version"])
                        self.assertEqual(parsed.normalized_text[anchor["start"]:anchor["end"]], anchor["quote"])
                        self.assertIsNone(anchor["page"])
                        self.assertFalse(anchor["locatable"])
                        self.assertEqual(anchor["reason"], "PREVIEW_NOT_AVAILABLE")

        f1 = expected["samples"]["F1"]["paragraphs"]
        f4 = expected["samples"]["F4"]["paragraphs"]
        self.assertEqual([index for index, (left, right) in enumerate(zip(f1, f4))
                          if left[3] != right[3]], [6, 7, 8])
        self.assertNotEqual(expected["samples"]["F1"]["sha256"],
                            expected["samples"]["F4"]["sha256"])

    def test_f5_empty_docx_fixed_sample_smoke(self) -> None:
        """A fixed F5 empty document blocks without evidence and can be replaced."""
        oracle = json.loads((SAMPLES / "f5_empty_expected.json").read_text(encoding="utf-8"))
        self.assertEqual(oracle["schema_version"], 1)
        self.assertEqual(oracle["sample_id"], "F5-empty-docx")
        content = (SAMPLES / oracle["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), oracle["sha256"])
        with self.assertRaises(DocxParseError) as caught:
            parse_docx(content, oracle["document_version"])
        self.assertEqual(caught.exception.code, oracle["expected_parse_code"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AuthStore(root / "f5-smoke.sqlite3")
            store.initialize()
            try:
                store.create_user("f5-owner", "business", "synthetic-password")
                store.create_user("f5-other", "business", "synthetic-password")
                store.create_user("f5-legal", "legal", "synthetic-password")
                with TestClient(create_app(auth_store=store, upload_root=root / "uploads")) as client:
                    def login(username: str) -> dict[str, str]:
                        response = client.post(
                            "/api/v1/sessions",
                            json={"username": username, "password": "synthetic-password"},
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": f"Bearer {response.json()['access_token']}"}

                    owner = login("f5-owner")
                    other = login("f5-other")
                    legal = login("f5-legal")
                    create = client.post(
                        "/api/v1/tasks", headers=owner,
                        data={"department": "采购部", "applicant": "合成用户"},
                        files={"file": (oracle["file"], content)},
                    )
                    self.assertEqual(create.status_code, 201, create.text)
                    task_id = create.json()["task_id"]
                    self.assertEqual(create.json()["document_version"], oracle["document_version"])
                    blocked = run_docx_once(client.app.state.task_store.jobs)
                    self.assertEqual(blocked["status"], oracle["machine_status"])
                    self.assertEqual(blocked["code"], oracle["expected_parse_code"])
                    state_response = client.get(f"/api/v1/tasks/{task_id}", headers=owner)
                    self.assertEqual(state_response.status_code, 200, state_response.text)
                    state = state_response.json()
                    for key in ("machine_status", "legal_status", "writeback_status", "recovery_action"):
                        self.assertEqual(state[key], oracle[key])
                    self.assertEqual(state["blocked_code"], oracle["expected_parse_code"])
                    self.assertTrue(state["blocked_reason"])
                    self.assertIsNone(state["review_version"])
                    self.assertEqual(client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code, 404)
                    document = client.get(f"/api/v1/tasks/{task_id}/document", headers=legal)
                    self.assertEqual(document.status_code, 409)
                    self.assertEqual(document.json()["code"], "DOCUMENT_NOT_READY")
                    risks = client.get(f"/api/v1/tasks/{task_id}/risks", headers=legal)
                    self.assertEqual(risks.status_code, 409)
                    self.assertEqual(risks.json()["code"], "DOCUMENT_NOT_READY")
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM parsed_documents WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], oracle["parsed_document_count"])
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM rule_draft_snapshots WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], oracle["risk_draft_count"])
                    self.assertEqual(run_docx_once(client.app.state.task_store.jobs),
                                     {"status": "no_pending_docx"})

                    revision = client.post(
                        f"/api/v1/tasks/{task_id}/documents", headers=owner,
                        data={"base_document_version": 1},
                        files={"file": ("f1-software-purchase.docx",
                                        (SAMPLES / "f1-software-purchase.docx").read_bytes())},
                    )
                    self.assertEqual(revision.status_code, 201, revision.text)
                    self.assertEqual(revision.json()["document_version"], 2)
                    self.assertEqual(tuple(store.connection.execute(
                        "SELECT machine_status, blocked_code FROM document_state_history "
                        "WHERE task_id = ? AND version = 1", (task_id,)
                    ).fetchone()), ("blocked", oracle["expected_parse_code"]))
                    self.assertEqual(run_docx_once(client.app.state.task_store.jobs)["status"], "reviewing")
                    self.assertEqual(store.connection.execute(
                        "SELECT document_version FROM parsed_documents WHERE task_id = ?", (task_id,)
                    ).fetchone()[0], 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
