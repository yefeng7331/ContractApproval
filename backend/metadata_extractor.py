"""Conservatively extract labelled contract metadata from parsed DOCX text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.docx_parser import ParsedDocx


FIELD_NAMES = (
    "title",
    "contract_number",
    "department",
    "applicant",
    "buyer",
    "buyer_credit_code",
    "supplier",
    "supplier_credit_code",
    "amount",
    "currency",
    "performance_term",
    "effective_conditions",
)

_LABELS = {
    "合同名称": "title",
    "合同标题": "title",
    "合同编号": "contract_number",
    "送审部门": "department",
    "申请人": "applicant",
    "采购方统一社会信用代码": "buyer_credit_code",
    "供应商统一社会信用代码": "supplier_credit_code",
    "甲方统一社会信用代码": "buyer_credit_code",
    "乙方统一社会信用代码": "supplier_credit_code",
    "采购方": "buyer",
    "供应商": "supplier",
    "甲方": "buyer",
    "乙方": "supplier",
    "采购金额": "amount",
    "合同金额": "amount",
    "金额": "amount",
    "履行期限": "performance_term",
    "生效条件": "effective_conditions",
}
_LABEL = re.compile(
    r"(?:^|[；;])\s*(?P<label>"
    + "|".join(re.escape(label) for label in sorted(_LABELS, key=len, reverse=True))
    + r")\s*[：:]"
)
_AMOUNT = re.compile(
    r"(?P<currency>人民币|CNY|￥|¥)?\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?:元)?"
)
_CREDIT_CODE = re.compile(r"[0-9A-Z]{18}")
_INLINE_CREDIT_CODE = re.compile(r"[，,（(]\s*统一社会信用代码\s*[：:]")
_TITLE = re.compile(r"[^；;：:\n]{2,80}合同(?:（[^）]{1,40}）|\([^)]{1,40}\))?")
_EMPTY_VALUES = {"未约定", "待定", "未识别", "无", "暂无", "不适用"}


@dataclass(frozen=True)
class FieldAnchor:
    document_version: int
    quote: str
    start: int
    end: int
    paragraph_index: int
    page: None = None
    locatable: bool = False
    reason: str = "PREVIEW_NOT_AVAILABLE"
    rects: tuple[()] = ()


@dataclass(frozen=True)
class MetadataField:
    name: str
    value: str | None
    status: str
    anchor: FieldAnchor | None
    reason: str | None = None


@dataclass(frozen=True)
class ExtractedMetadata:
    fields: tuple[MetadataField, ...]

    def get(self, name: str) -> MetadataField:
        return next(field for field in self.fields if field.name == name)


def _validate(parsed: ParsedDocx) -> None:
    if parsed.document_version < 1:
        raise ValueError("document_version must be positive")
    previous_end = -1
    for paragraph in parsed.paragraphs:
        if (
            paragraph.document_version != parsed.document_version
            or paragraph.start < 0
            or paragraph.start < previous_end
            or paragraph.end <= paragraph.start
            or paragraph.end > len(parsed.normalized_text)
            or parsed.normalized_text[paragraph.start:paragraph.end] != paragraph.quote
        ):
            raise ValueError("paragraph spans do not match the document version and text")
        previous_end = paragraph.end


def extract_metadata(parsed: ParsedDocx) -> ExtractedMetadata:
    """Return explicit values and exact spans; absent or conflicting values stay unknown."""
    _validate(parsed)
    candidates: dict[str, list[tuple[str, FieldAnchor]]] = {name: [] for name in FIELD_NAMES}

    def add(name: str, value: str, paragraph_index: int, start: int) -> None:
        if not value or value in _EMPTY_VALUES or value.startswith(("未约定", "未识别", "暂无")):
            return
        anchor = FieldAnchor(
            document_version=parsed.document_version,
            quote=value,
            start=start,
            end=start + len(value),
            paragraph_index=paragraph_index,
        )
        candidates[name].append((value, anchor))

    for paragraph in parsed.paragraphs:
        matches = list(_LABEL.finditer(paragraph.quote))
        for index, match in enumerate(matches):
            field_name = _LABELS[match.group("label")]
            raw_end = matches[index + 1].start() if index + 1 < len(matches) else len(paragraph.quote)
            # A semicolon also ends a value when the following item has no known label.
            separator = re.search(r"[；;]", paragraph.quote[match.end():raw_end])
            if separator:
                raw_end = match.end() + separator.start()
            raw = paragraph.quote[match.end():raw_end]
            leading = len(raw) - len(raw.lstrip())
            value = raw.strip().rstrip("。.").rstrip()
            start = paragraph.start + match.end() + leading
            if field_name == "amount":
                amount = _AMOUNT.fullmatch(value)
                if amount:
                    amount_start = start + amount.start("amount")
                    add("amount", amount.group("amount"), paragraph.paragraph_index, amount_start)
                    if amount.group("currency"):
                        currency_start = start + amount.start("currency")
                        add("currency", amount.group("currency"), paragraph.paragraph_index, currency_start)
            elif field_name in {"buyer_credit_code", "supplier_credit_code"}:
                if _CREDIT_CODE.fullmatch(value):
                    add(field_name, value, paragraph.paragraph_index, start)
            elif field_name in {"buyer", "supplier"}:
                inline_code = _INLINE_CREDIT_CODE.search(value)
                if inline_code:
                    party = value[:inline_code.start()].rstrip()
                    add(field_name, party, paragraph.paragraph_index, start)
                    code_raw = value[inline_code.end():].rstrip("）)")
                    code = code_raw.strip()
                    if _CREDIT_CODE.fullmatch(code):
                        code_start = start + inline_code.end() + len(code_raw) - len(code_raw.lstrip())
                        add(field_name + "_credit_code", code, paragraph.paragraph_index, code_start)
                else:
                    add(field_name, value, paragraph.paragraph_index, start)
            else:
                add(field_name, value, paragraph.paragraph_index, start)

    # The first standalone heading is an allowed title when no labelled title exists.
    if not candidates["title"] and parsed.paragraphs:
        first = parsed.paragraphs[0]
        heading = first.quote.strip()
        if _TITLE.fullmatch(heading):
            add("title", heading, first.paragraph_index, first.start + first.quote.index(heading))

    fields: list[MetadataField] = []
    for name in FIELD_NAMES:
        found = candidates[name]
        if not found:
            fields.append(MetadataField(name, None, "unrecognized", None, "NOT_FOUND"))
        elif len({value for value, _ in found}) > 1:
            fields.append(MetadataField(name, None, "unrecognized", None, "AMBIGUOUS_VALUES"))
        else:
            value, anchor = found[0]
            fields.append(MetadataField(name, value, "identified", anchor))
    return ExtractedMetadata(tuple(fields))
