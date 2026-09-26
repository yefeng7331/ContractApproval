"""Regenerate the fixed, clear F3 raster scan from the accepted F1 text.

This fixture-only script needs Pillow and a locally available embeddable Chinese
font. Neither is needed by the backend at runtime.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 2048, 2800
LEFT, TOP, STEP = 140, 245, 190
FONT_SIZE = 44


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "f3-clear-scan.png")
    args = parser.parse_args()
    source = json.loads((ROOT / "f1_f4_expected.json").read_text(encoding="utf-8"))
    paragraphs = source["samples"]["F1"]["paragraphs"]
    font = ImageFont.truetype(str(args.font), FONT_SIZE)
    image = Image.new("L", (WIDTH, HEIGHT), 250)
    draw = ImageDraw.Draw(image)
    draw.rectangle((84, 84, WIDTH - 85, HEIGHT - 85), outline=222, width=2)
    for index, _, _, quote in paragraphs:
        y = TOP + STEP * index
        bounds = draw.textbbox((LEFT, y), quote, font=font)
        if bounds[2] >= WIDTH - 100 or bounds[3] >= HEIGHT - 100:
            raise ValueError(f"Paragraph {index} does not fit on the scan")
        draw.text((LEFT, y), quote, fill=30, font=font)
        print(index, bounds)
    image.save(args.output, format="PNG", optimize=False, compress_level=9)
    print(args.output)


if __name__ == "__main__":
    main()
