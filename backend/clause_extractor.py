"""Identify explicitly headed clauses in a parsed synthetic DOCX contract."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.docx_parser import ParsedDocx, ParagraphSpan


CLAUSE_TYPES = (
    "标的",
    "付款",
    "验收",
    "违约",
    "保密",
    "数据安全",
    "知识产权",
    "争议解决",
)

_PREFIX = r"\s*(?:(?:第[一二三四五六七八九十百千\d]+条|\d+[.、．)])\s*)?"
_HEADING = re.compile(
    _PREFIX + r"(?P<kind>知识产权|争议解决|数据安全|标的|付款|验收|违约|保密)"
    r"(?=\s*(?:[：:、]|$))"
)
_OTHER_ARTICLE = re.compile(r"\s*(?:第[一二三四五六七八九十百千\d]+条|\d+[.、．)])")
_METADATA = re.compile(r"\s*(?:合同编号|送审部门|申请人|采购方|供应商|采购金额|履行期限|生效条件)\s*[：:]")


@dataclass(frozen=True)
class ClauseSpan:
    clause_type: str
    document_version: int
    quote: str
    start: int
    end: int
    paragraph_index: int
    page: int | None = None
    locatable: bool = False
    reason: str | None = "PREVIEW_NOT_AVAILABLE"
    rects: tuple[dict[str, int | float], ...] = ()


@dataclass(frozen=True)
class ExtractedClauses:
    clauses: tuple[ClauseSpan, ...]
    missing_types: tuple[str, ...]


def _validate(parsed: ParsedDocx) -> None:
    previous_end = -1
    for paragraph in parsed.paragraphs:
        if (
            paragraph.document_version != parsed.document_version
            or paragraph.start < 0
            or paragraph.start < previous_end
            or paragraph.end > len(parsed.normalized_text)
            or paragraph.end <= paragraph.start
            or parsed.normalized_text[paragraph.start:paragraph.end] != paragraph.quote
        ):
            raise ValueError("paragraph spans do not match the document version and text")
        previous_end = paragraph.end


def extract_clauses(parsed: ParsedDocx) -> ExtractedClauses:
    """Return headed clauses in source order; never infer an absent clause from prose."""
    _validate(parsed)
    found: list[ClauseSpan] = []
    current_kind: str | None = None
    current_first: ParagraphSpan | None = None
    current_last: ParagraphSpan | None = None

    def finish() -> None:
        if current_kind is None or current_first is None or current_last is None:
            return
        found.append(
            ClauseSpan(
                clause_type=current_kind,
                document_version=parsed.document_version,
                quote=parsed.normalized_text[current_first.start:current_last.end],
                start=current_first.start,
                end=current_last.end,
                paragraph_index=current_first.paragraph_index,
            )
        )

    for paragraph in parsed.paragraphs:
        heading = _HEADING.match(paragraph.quote)
        if heading:
            finish()
            current_kind = heading.group("kind")
            current_first = paragraph
            current_last = paragraph
        elif _OTHER_ARTICLE.match(paragraph.quote) or _METADATA.match(paragraph.quote):
            finish()
            current_kind = None
            current_first = None
            current_last = None
        elif current_kind is not None:
            current_last = paragraph
    finish()
    present = {clause.clause_type for clause in found}
    return ExtractedClauses(tuple(found), tuple(kind for kind in CLAUSE_TYPES if kind not in present))
