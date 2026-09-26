"""Build the synthetic password-protected F5 fixture, not a security utility.

Install samples/requirements-pdf-fixtures.txt into .tools/pdf-fixtures first.
The public test passwords protect synthetic data only.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / ".tools" / "pdf-fixtures"))

from pypdf import PdfWriter


def main() -> None:
    source = ROOT / "f2-text-software-purchase.pdf"
    expected = "1e57bd776b26e4b8529edecabb90fdf56c523d3bd77c530698df692b8842e98c"
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise ValueError("F2 source differs from the accepted fixed sample")
    writer = PdfWriter(clone_from=source)
    # Legacy algorithm deliberately exercises password gating without another
    # crypto dependency. This fixture is not a production encryption example.
    writer.encrypt("f5-synthetic-user", "f5-synthetic-owner", algorithm="RC4-128")
    destination = ROOT / "f5-encrypted.pdf"
    writer.write(destination)
    writer.close()
    print(hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
