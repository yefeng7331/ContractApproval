"""Deterministic F6 attachment dependency fixture, not a task processor.

The caller supplies its persisted attempt number. Attempt 1 raises immediately;
later attempts return the accepted F1 attachment. No network or sleep is used.
"""

import hashlib
import json
from pathlib import Path


SCENARIO_ID = "F6-pending-attachment-timeout"
ATTACHMENT_PATH = Path(__file__).resolve().parent / "f1-software-purchase.docx"
ATTACHMENT_SHA256 = "5664c685de060fe11deb194bf75d1aadf628594f3b83a48780c315386c742d42"


def fetch_attachment(attempt_number: int) -> bytes:
    """Raise a synthetic timeout once per caller-owned attempt sequence."""
    if type(attempt_number) is not int or attempt_number < 1:
        raise ValueError("attempt_number must be a positive integer")
    if attempt_number == 1:
        raise TimeoutError("Synthetic pending attachment timeout (F6)")
    content = ATTACHMENT_PATH.read_bytes()
    if hashlib.sha256(content).hexdigest() != ATTACHMENT_SHA256:
        raise ValueError("F1 attachment differs from the accepted fixed sample")
    return content


def main() -> None:
    for attempt in (1, 2):
        try:
            content = fetch_attachment(attempt)
        except TimeoutError:
            result = {"dependency_outcome": "timeout", "attachment_returned": False}
        else:
            result = {"dependency_outcome": "attachment_available",
                      "attachment_returned": True,
                      "sha256": hashlib.sha256(content).hexdigest()}
        print(json.dumps({"scenario_id": SCENARIO_ID, "attempt_number": attempt,
                          "scope": "dependency_fixture_only", **result}))


if __name__ == "__main__":
    main()
