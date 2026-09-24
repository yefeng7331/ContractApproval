"""Boundary checks for conservative fixed commercial demo rules."""

import unittest
from dataclasses import replace
from xml.sax.saxutils import escape

from backend.clause_extractor import ExtractedClauses, extract_clauses
from backend.demo_rules import evaluate_demo_rules
from backend.docx_parser import parse_docx
from tests.test_docx_parser import package


def parsed_contract(*paragraphs: str):
    body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    return parse_docx(package(body), 3)


class DemoRuleTests(unittest.TestCase):
    def test_contradictions_in_separate_clauses_do_not_raise_risks(self) -> None:
        risky = (
            "标的：乙方交付软件系统。",
            "知识产权：全部知识产权归乙方所有，甲方不享有持续使用授权。",
            "付款：软件到货后，甲方一次性支付全部合同价款。",
            "验收：双方未约定验收标准。",
        )
        for correction in (
            "知识产权：甲方享有满足项目目的的持续使用授权。",
            "付款：支付全部合同价款以验收合格为前提。",
            "验收：付款前须验收合格。",
        ):
            for paragraphs in ((*risky, correction), (correction, *risky)):
                with self.subTest(correction=correction, first=paragraphs[0]):
                    parsed = parsed_contract(*paragraphs)
                    ids = {r["rule_id"] for r in
                           evaluate_demo_rules(parsed, extract_clauses(parsed))["risks"]}
                    suppressed = "DEMO-IP-01" if correction.startswith("知识产权") else "DEMO-PAY-01"
                    self.assertNotIn(suppressed, ids)
                    self.assertIn("DEMO-PAY-01" if suppressed == "DEMO-IP-01" else "DEMO-IP-01", ids)

    def test_contradictory_license_and_acceptance_stay_for_manual_review(self) -> None:
        parsed = parsed_contract(
            "标的：乙方交付软件系统。",
            "付款：软件到货后，甲方一次性支付全部合同价款，以验收合格为前提。",
            "验收：双方未约定验收标准，但付款前须验收合格。",
            "知识产权：全部知识产权归乙方所有，甲方不享有持续使用授权；"
            "甲方享有满足项目目的的持续使用授权。",
        )
        self.assertEqual(evaluate_demo_rules(parsed, extract_clauses(parsed))["risks"], [])

    def test_unanchored_or_cross_version_evidence_is_rejected(self) -> None:
        parsed = parsed_contract("标的：乙方交付软件系统。", "知识产权：全部知识产权归乙方所有，"
                                 "甲方不享有持续使用授权。")
        clauses = extract_clauses(parsed)
        altered = replace(clauses.clauses[-1], document_version=4)
        with self.assertRaises(ValueError):
            evaluate_demo_rules(parsed, ExtractedClauses(
                (*clauses.clauses[:-1], altered), clauses.missing_types
            ))
        altered = replace(clauses.clauses[-1], quote="不存在的原文")
        with self.assertRaises(ValueError):
            evaluate_demo_rules(parsed, ExtractedClauses(
                (*clauses.clauses[:-1], altered), clauses.missing_types
            ))
        for changes in (
            {"paragraph_index": -1}, {"paragraph_index": 999},
            {"locatable": True, "page": 1, "rects": (), "reason": None},
            {"locatable": True, "page": 1,
             "rects": ({"page": 1, "x": -0.1, "y": 0, "width": 0.5, "height": 0.1},),
             "reason": None},
        ):
            with self.subTest(changes=changes):
                altered = replace(clauses.clauses[-1], **changes)
                with self.assertRaises(ValueError):
                    evaluate_demo_rules(parsed, ExtractedClauses(
                        (*clauses.clauses[:-1], altered), clauses.missing_types
                    ))

    def test_missing_license_and_acceptance_are_flagged_from_real_docx(self) -> None:
        parsed = parsed_contract(
            "标的：乙方交付软件系统。",
            "知识产权：全部知识产权归乙方所有。",
            "付款：软件到货后，甲方一次性支付全部合同价款。",
        )
        extracted = extract_clauses(parsed)
        result = evaluate_demo_rules(parsed, extracted)
        self.assertEqual({risk["rule_id"] for risk in result["risks"]},
                         {"DEMO-IP-01", "DEMO-PAY-01"})
        payment = next(risk for risk in result["risks"] if risk["rule_id"] == "DEMO-PAY-01")
        self.assertEqual(payment["missing_clause_types"], ["验收"])
        self.assertEqual(len(payment["anchors"]), 1)
        self.assertEqual(payment["anchors"][0]["clause_type"], "付款")

    def test_full_payment_without_explicit_negative_acceptance_is_not_decided(self) -> None:
        parsed = parsed_contract(
            "付款：软件到货后，甲方一次性支付全部合同价款。",
            "验收：双方另行协商验收事宜。",
        )
        self.assertEqual(evaluate_demo_rules(parsed, extract_clauses(parsed))["risks"], [])


if __name__ == "__main__":
    unittest.main()
