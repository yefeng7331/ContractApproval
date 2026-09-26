"""Rebuild the checked-in, synthetic F2 text PDF (fixture tooling only).

Requires fontTools and a local, embeddable Noto Sans SC TrueType font. This
script is not part of the backend runtime or the fixed-sample smoke test.
"""

import argparse
import io
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


ROOT = Path(__file__).resolve().parent
PAGE_PARAGRAPHS = ((0, 1, 2, 3, 4, 5), (6, 7), (8, 9, 10, 11))


def pdf_object(value: bytes | str) -> bytes:
    return value.encode("ascii") if isinstance(value, str) else value


def build_pdf(font_path: Path) -> bytes:
    source = json.loads((ROOT / "f1_f4_expected.json").read_text(encoding="utf-8"))
    paragraphs = [row[3] for row in source["samples"]["F1"]["paragraphs"]]
    font = TTFont(font_path, recalcTimestamp=False)
    if font["OS/2"].fsType & 0x000E:
        raise ValueError("The selected font does not permit PDF embedding")
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": 400}, inplace=True)
    options = subset.Options()
    options.recalc_timestamp = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text="".join(paragraphs))
    subsetter.subset(font)
    font["head"].created = 0
    font["head"].modified = 0
    font_bytes = io.BytesIO()
    font.save(font_bytes)
    cmap = font.getBestCmap()
    chars = sorted(set("".join(paragraphs)))
    missing = [char for char in chars if ord(char) not in cmap]
    if missing:
        raise ValueError(f"Missing font glyphs: {missing}")
    gids = {char: font.getGlyphID(cmap[ord(char)]) for char in chars}
    if len(set(gids.values())) != len(gids):
        raise ValueError("Distinct fixture characters must have distinct glyph IDs")
    units = font["head"].unitsPerEm
    widths = sorted((gid, round(font["hmtx"][cmap[ord(char)]][0] * 1000 / units))
                    for char, gid in gids.items())

    def stream(data: bytes, extra: str = "") -> bytes:
        return pdf_object(f"<< /Length {len(data)} {extra} >>\nstream\n") + data + b"\nendstream"

    objects: list[bytes] = []

    def add(value: bytes | str) -> int:
        objects.append(pdf_object(value))
        return len(objects)

    catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    assert (catalog_id, pages_id) == (1, 2)
    page_ids = []
    for indexes in PAGE_PARAGRAPHS:
        commands = []
        for row, index in enumerate(indexes):
            encoded = "".join(f"{gids[char]:04X}" for char in paragraphs[index])
            commands.append(f"BT /F1 12 Tf 48 {770 - row * 38} Td <{encoded}> Tj ET")
        content_id = add(stream("\n".join(commands).encode("ascii")))
        page_ids.append(add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 0 0 R >> >> /Contents {content_id} 0 R >>"
        ))

    font_file_id = add(stream(font_bytes.getvalue(), f"/Length1 {len(font_bytes.getvalue())}"))
    scale = lambda value: round(value * 1000 / units)
    head = font["head"]
    descriptor_id = add(
        f"<< /Type /FontDescriptor /FontName /NotoSansSCSubset /Flags 4 "
        f"/FontBBox [{scale(head.xMin)} {scale(head.yMin)} {scale(head.xMax)} {scale(head.yMax)}] "
        f"/Ascent {scale(font['hhea'].ascent)} /Descent {scale(font['hhea'].descent)} "
        f"/CapHeight {scale(font['hhea'].ascent)} /ItalicAngle 0 /StemV 80 "
        f"/FontFile2 {font_file_id} 0 R >>"
    )
    cmap_lines = [
        "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /F2Unicode def", "/CMapType 2 def",
        "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
    ]
    pairs = [(gids[char], char) for char in chars]
    for start in range(0, len(pairs), 100):
        chunk = pairs[start:start + 100]
        cmap_lines.append(f"{len(chunk)} beginbfchar")
        cmap_lines.extend(f"<{gid:04X}> <{char.encode('utf-16-be').hex().upper()}>"
                          for gid, char in chunk)
        cmap_lines.append("endbfchar")
    cmap_lines.extend(["endcmap", "CMapName currentdict /CMap defineresource pop",
                       "end", "end"])
    unicode_id = add(stream("\n".join(cmap_lines).encode("ascii")))
    width_entries = " ".join(f"{gid} [{width}]" for gid, width in widths)
    descendant_id = add(
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /NotoSansSCSubset "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor_id} 0 R /DW 1000 /W [{width_entries}] "
        f"/CIDToGIDMap /Identity >>"
    )
    font_id = add(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /NotoSansSCSubset "
        f"/Encoding /Identity-H /DescendantFonts [{descendant_id} 0 R] "
        f"/ToUnicode {unicode_id} 0 R >>"
    )
    objects[pages_id - 1] = pdf_object(
        f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in page_ids)}] "
        f"/Count {len(page_ids)} >>"
    )
    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace(b"/F1 0 0 R", pdf_object(f"/F1 {font_id} 0 R"))

    output = bytearray(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(pdf_object(f"{number} 0 obj\n") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(pdf_object(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n"))
    for offset in offsets[1:]:
        output.extend(pdf_object(f"{offset:010d} 00000 n \n"))
    output.extend(pdf_object(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ))
    return bytes(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    args = parser.parse_args()
    result = build_pdf(args.font)
    target = ROOT / "f2-text-software-purchase.pdf"
    target.write_bytes(result)
    print(f"{target.name}: {len(result)} bytes")
