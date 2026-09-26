"""Extract explicit PDF fields and clauses, preserving source-page evidence."""

from dataclasses import replace

from backend.clause_extractor import ExtractedClauses, extract_clauses
from backend.metadata_extractor import ExtractedMetadata, extract_metadata


def extract_pdf_structure(parsed, region_prefix='PDF'):
    metadata = extract_metadata(parsed)
    clauses = extract_clauses(parsed)
    fields = []
    for field in metadata.fields:
        if field.anchor is None:
            fields.append(field)
            continue
        anchor = field.anchor
        paragraph = next(p for p in parsed.paragraphs
                         if p.start <= anchor.start and anchor.end <= p.end)
        # A whole line is not a precise box for a value contained within that line.
        whole_line = anchor.start == paragraph.start and anchor.end == paragraph.end
        located = whole_line and paragraph.locatable
        fields.append(replace(field, anchor=replace(
            anchor, page=paragraph.page, locatable=located,
            rects=paragraph.rects if located else (),
            reason=None if located else f"{region_prefix}_FIELD_REGION_UNVERIFIED",
        )))
    located_clauses = []
    for clause in clauses.clauses:
        source = [p for p in parsed.paragraphs if p.start < clause.end and p.end > clause.start]
        located = (bool(source) and source[0].start == clause.start
                   and source[-1].end == clause.end and all(p.locatable for p in source))
        rects = tuple(rect for p in source for rect in p.rects) if located else ()
        located_clauses.append(replace(
            clause, page=rects[0]["page"] if rects else None,
            locatable=located, rects=rects,
            reason=None if located else f"{region_prefix}_REGION_UNRELIABLE",
        ))
    return ExtractedMetadata(tuple(fields)), ExtractedClauses(tuple(located_clauses), clauses.missing_types)
