"""Conservative commercial demo rules over same-version DOCX clause evidence.

These fixed-sample rules create machine drafts, not legal conclusions. Explicit
missing clause markers are reported with available same-version evidence.
"""

from __future__ import annotations

import re
from math import isfinite
from dataclasses import asdict

from backend.clause_extractor import ExtractedClauses, ClauseSpan
from backend.docx_parser import ParagraphSpan, ParsedDocx


RULE_VERSION = "demo-v2"
_FULL_PAYMENT_ON_DELIVERY = re.compile(
    r"(?:到货后.{0,16}一次性支付全部|到货即付全款|交付后.{0,16}一次性支付全部)"
)
_NO_EXECUTABLE_ACCEPTANCE = re.compile(
    r"(?:未约定|没有约定|无).{0,35}(?:验收标准|验收程序|验收条件)"
)
_SUPPLIER_OWNS_IP = re.compile(r"(?:全部)?知识产权归(?:乙方|供应商)所有")
_USE_RIGHT_GRANTED = re.compile(r"甲方享有.{0,20}(?:持续)?使用(?:权|授权)")
_PAYMENT_GATED_BY_ACCEPTANCE = re.compile(
    r"(?:验收(?:合格|通过)后|付款前.{0,12}验收(?:合格|通过)|以验收(?:合格|通过)为前提)"
)


def _check_clause(parsed: ParsedDocx, clause: ClauseSpan) -> None:
    if (
        clause.document_version != parsed.document_version
        or type(clause.paragraph_index) is not int
        or clause.paragraph_index < 0
        or clause.start < 0
        or clause.end <= clause.start
        or clause.end > len(parsed.normalized_text)
        or parsed.normalized_text[clause.start:clause.end] != clause.quote
    ):
        raise ValueError("rule evidence does not match the parsed document version and text")
    if parsed.paragraphs and not any(
        paragraph.paragraph_index == clause.paragraph_index
        and paragraph.start <= clause.start < paragraph.end
        for paragraph in parsed.paragraphs
    ):
        raise ValueError("rule evidence has no matching source paragraph")
    if type(clause.locatable) is not bool:
        raise ValueError("rule evidence has invalid location state")
    if clause.locatable:
        if (type(clause.page) is not int or clause.page < 1 or not clause.rects
                or clause.reason not in (None, "")):
            raise ValueError("locatable rule evidence has no valid preview location")
        for rect in clause.rects:
            if not isinstance(rect, dict) or type(rect.get("page")) is not int or rect["page"] < 1:
                raise ValueError("rule evidence has an invalid preview rectangle")
            values = tuple(rect.get(key) for key in ("x", "y", "width", "height"))
            if any(type(value) not in (int, float) or not isfinite(value) for value in values):
                raise ValueError("rule evidence has an invalid preview rectangle")
            x, y, width, height = values
            if (x < 0 or y < 0 or width <= 0 or height <= 0
                    or x + width > 1 or y + height > 1):
                raise ValueError("rule evidence has an invalid preview rectangle")
        if clause.rects[0]["page"] != clause.page:
            raise ValueError("rule evidence page does not match its preview rectangle")
    elif clause.page is not None or clause.rects or not clause.reason:
        raise ValueError("unlocatable rule evidence must give a reason and no rectangles")


def _draft(rule_id: str, risk_type: str, clause_type: str, reason: str,
           suggestion: str, evidence: tuple[ClauseSpan, ...], version: int,
           missing_clause_types: tuple[str, ...] = ()) -> dict:
    draft = {
        "source": "rule",
        "rule_id": rule_id,
        "rule_version": RULE_VERSION,
        "document_version": version,
        "review_version": None,
        "clause_type": clause_type,
        "risk_type": risk_type,
        "risk_level": "high",
        "trigger_reason": reason,
        "evidence_source": "contract_original",
        "anchors": [asdict(clause) for clause in evidence],
        "suggestion": suggestion,
        "legal_basis_status": "pending_legal_verification",
        "status": "machine_draft",
    }
    if missing_clause_types:
        draft["missing_clause_types"] = list(missing_clause_types)
    return draft


def evaluate_persisted_rule_evidence(
    document_version: int, normalized_text: str, paragraphs_data: list,
    clauses_data: list, missing_clause_types: list,
) -> dict:
    """Decode stored parse evidence once for both rule-reading paths."""
    if (not isinstance(normalized_text, str) or not isinstance(paragraphs_data, list)
            or not isinstance(clauses_data, list) or not isinstance(missing_clause_types, list)
            or any(not isinstance(item, dict) for item in (*paragraphs_data, *clauses_data))
            or any(not isinstance(item, str) for item in missing_clause_types)):
        raise ValueError("stored rule evidence has an invalid shape")
    parsed = ParsedDocx(
        document_version, normalized_text,
        tuple(ParagraphSpan(**item) for item in paragraphs_data),
    )
    if clauses_data and not parsed.paragraphs:
        raise ValueError("stored rule evidence has no source paragraphs")
    for paragraph in parsed.paragraphs:
        if (paragraph.document_version != document_version
                or type(paragraph.paragraph_index) is not int
                or paragraph.paragraph_index < 0
                or type(paragraph.start) is not int or type(paragraph.end) is not int
                or paragraph.start < 0 or paragraph.end <= paragraph.start
                or paragraph.end > len(normalized_text)
                or normalized_text[paragraph.start:paragraph.end] != paragraph.quote):
            raise ValueError("stored paragraph evidence does not match the document")
    extracted = ExtractedClauses(
        tuple(ClauseSpan(**item) for item in clauses_data),
        tuple(missing_clause_types),
    )
    return evaluate_demo_rules(parsed, extracted)


def evaluate_demo_rules(parsed: ParsedDocx, extracted: ExtractedClauses) -> dict:
    """Evaluate bounded F1/F4-style evidence; do not infer legal safety."""
    if parsed.document_version < 1:
        raise ValueError("document version must be positive")
    for clause in extracted.clauses:
        _check_clause(parsed, clause)
    by_type: dict[str, list[ClauseSpan]] = {}
    for clause in extracted.clauses:
        by_type.setdefault(clause.clause_type, []).append(clause)

    risks: list[dict] = []
    software_subject = any("软件" in c.quote for c in by_type.get("标的", []))
    # Conflicting evidence may occur in a separate clause, in either order.
    # Leave that rule undecided rather than selecting only the adverse clause.
    use_right_granted = any(_USE_RIGHT_GRANTED.search(c.quote) for c in extracted.clauses)
    payment_gated = any(
        _PAYMENT_GATED_BY_ACCEPTANCE.search(c.quote)
        for c in extracted.clauses
    )
    for ip in by_type.get("知识产权", []):
        if software_subject and _SUPPLIER_OWNS_IP.search(ip.quote) and not use_right_granted:
            risks.append(_draft(
                "DEMO-IP-01", "software_use_rights", "知识产权",
                "交付软件权属归供应商，已识别条款未安排采购方持续使用授权",
                "请法务协商权属、满足项目目的的许可、源代码交付及第三方权利保证；不预设采购方取得全部著作权。",
                (ip,), parsed.document_version,
            ))
            break

    for payment in by_type.get("付款", []):
        if (not _FULL_PAYMENT_ON_DELIVERY.search(payment.quote)
                or payment_gated):
            continue
        if "验收" in extracted.missing_types and not by_type.get("验收"):
            risks.append(_draft(
                "DEMO-PAY-01", "payment_before_acceptance", "付款",
                "到货后一次性付全款，未找到可执行的付款前验收条款",
                "请法务协商按可核验的交付与验收里程碑付款；具体比例由法务确定。",
                (payment,), parsed.document_version, ("验收",),
            ))
            break
        for acceptance in by_type.get("验收", []):
            if (_NO_EXECUTABLE_ACCEPTANCE.search(acceptance.quote)
                    and not _PAYMENT_GATED_BY_ACCEPTANCE.search(acceptance.quote)):
                risks.append(_draft(
                    "DEMO-PAY-01", "payment_before_acceptance", "付款",
                    "到货后一次性付全款，验收条款明确未约定可执行的付款前验收条件",
                    "请法务协商按可核验的交付与验收里程碑付款；具体比例由法务确定。",
                    (payment, acceptance), parsed.document_version,
                ))
                break
        if any(item["rule_id"] == "DEMO-PAY-01" for item in risks):
            break

    return {
        "document_version": parsed.document_version,
        "review_version": None,
        "status": "machine_draft",
        "risks": risks,
        "enabled_rule_risk_summary": "high" if risks else "未发现已启用规则风险",
        "machine_suggestion": "建议拒绝并整改" if len(risks) == 2 else (
            "建议整改，待法务复核" if risks else "待法务复核"
        ),
    }


def main() -> None:
    """Print inspectable F1/F4 candidate rule drafts without changing task data."""
    from backend.clause_extractor import extract_clauses
    from backend.docx_parser import parse_docx
    from backend.mock_pending import synthetic_attachment, synthetic_revised_attachment

    for name, content in (("F1 candidate", synthetic_attachment()),
                          ("F4 candidate", synthetic_revised_attachment())):
        parsed = parse_docx(content, 1)
        result = evaluate_demo_rules(parsed, extract_clauses(parsed))
        print(name, result["enabled_rule_risk_summary"])
        for risk in result["risks"]:
            print(risk["rule_id"], risk["risk_level"],
                  [anchor["quote"] for anchor in risk["anchors"]])


if __name__ == "__main__":
    main()
