"""Render a lightweight v0.4 contact sheet for visual QA of pencil-new.pen."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "pencil-new.pen").read_text(encoding="utf-8"))
FONT = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


def get_font(node):
    size = round(node.get("fontSize", 14))
    file = FONT_BOLD if node.get("fontWeight") in {"600", "700"} and FONT_BOLD.exists() else FONT
    return ImageFont.truetype(str(file), size) if file.exists() else ImageFont.load_default(size=size)


def wrap(draw, value, font, width):
    out = []
    for paragraph in value.split("\n"):
        line = ""
        for char in paragraph:
            if draw.textlength(line + char, font=font) > width and line:
                out.append(line)
                line = char
            else:
                line += char
        out.append(line)
    return out


def render_node(draw, node):
    x, y = node.get("x", 0), node.get("y", 0)
    w, h = node.get("width", 0), node.get("height", 0)
    if node["type"] in {"rectangle", "frame"} and "fill" in node:
        box = (x, y, x + w, y + h)
        radius = node.get("cornerRadius", 0)
        outline = node.get("stroke")
        draw.rounded_rectangle(box, radius=radius, fill=node["fill"], outline=outline,
                               width=node.get("strokeWidth", 1))
    if node["type"] == "text":
        font = get_font(node)
        line_height = round(node.get("fontSize", 14) * node.get("lineHeight", 1.4))
        for i, line in enumerate(wrap(draw, node.get("content", ""), font, max(w, 1))):
            draw.text((x, y + i * line_height), line, font=font, fill=node.get("fill", "#000000"))
    for child in node.get("children", []):
        render_node(draw, child)


images = []
for number, board in enumerate(DATA["children"], start=1):
    canvas = Image.new("RGB", (board["width"], board["height"]), "#FFFFFF")
    render_node(ImageDraw.Draw(canvas), board)
    if number in {2, 3, 8, 10}:
        canvas.save(ROOT / "design" / f"v0.4-board-{number:02d}.png")
    canvas.thumbnail((720, 450), Image.Resampling.LANCZOS)
    images.append((board["name"], canvas))

sheet = Image.new("RGB", (1500, ((len(images) + 1) // 2) * 510 + 20), "#E9EDE9")
draw = ImageDraw.Draw(sheet)
label_font = ImageFont.truetype(str(FONT), 20) if FONT.exists() else ImageFont.load_default(size=20)
for i, (name, canvas) in enumerate(images):
    x = 20 + (i % 2) * 750
    y = 20 + (i // 2) * 510
    draw.text((x, y), name, font=label_font, fill="#142522")
    sheet.paste(canvas, (x, y + 38))

out = ROOT / "design" / "v0.4-preview.png"
sheet.save(out)
print(out)
