"""Regenerate the synthetic F5 severe-blur scan from the fixed F3 image.

This fixture-only script uses Pillow; the backend has no Pillow dependency.
"""

import hashlib
from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parent
SOURCE_SHA256 = "c7cf33fff294b6842b679d99d99fdd3a411e6e551a52b8c547dcd2f06cc12548"
BLUR_RADIUS = 22


def main() -> None:
    source = ROOT / "f3-clear-scan.png"
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != SOURCE_SHA256:
        raise ValueError("F3 source image differs from the accepted fixed sample")
    with Image.open(source) as image:
        if image.mode != "L" or image.size != (2048, 2800):
            raise ValueError("F3 source must be the fixed grayscale page")
        blurred = image.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    destination = ROOT / "f5-blurred-scan.png"
    blurred.save(destination, format="PNG", optimize=False, compress_level=9)
    print(destination)
    print(hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
