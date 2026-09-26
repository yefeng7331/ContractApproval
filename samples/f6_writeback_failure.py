"""In-memory F6 mock comment dependency for failure/retry fixture checks.

This is a scripted external dependency, not the application's writeback API.
The first write fails; subsequent writes deduplicate by the approved tuple.
"""

import json


SCENARIO_ID = "F6-writeback-failure-and-duplicate"
COMMENT = "模拟回写：合成软件采购合同需法务确认整改。"
TASK_ID = "synthetic-f6-task"
MOCK_APPROVAL_ID = "synthetic-f6-approval"


class MockCommentSink:
    def __init__(self) -> None:
        self._fail_next_write = True
        self._comments: dict[tuple[str, int, str], tuple[str, str]] = {}

    @property
    def comment_count(self) -> int:
        return len(self._comments)

    def submit(
        self, task_id: str, confirmed_review_version: int,
        mock_approval_id: str, markdown: str,
    ) -> tuple[str, bool]:
        if not task_id or not mock_approval_id or not markdown or (
            type(confirmed_review_version) is not int or confirmed_review_version < 1
        ):
            raise ValueError("A task, positive confirmed version, target, and comment are required")
        key = (task_id, confirmed_review_version, mock_approval_id)
        if key in self._comments:
            comment_id, existing_markdown = self._comments[key]
            if markdown != existing_markdown:
                raise ValueError("The existing versioned comment has different content")
            return comment_id, False
        if self._fail_next_write:
            self._fail_next_write = False
            raise TimeoutError("Synthetic first mock comment write failure (F6)")
        comment_id = f"synthetic-comment-{len(self._comments) + 1:03d}"
        self._comments[key] = (comment_id, markdown)
        return comment_id, True


def main() -> None:
    sink = MockCommentSink()
    attempts = ((1, COMMENT), (1, COMMENT), (1, COMMENT), (2, COMMENT))
    for number, (version, markdown) in enumerate(attempts, start=1):
        try:
            comment_id, created = sink.submit(
                TASK_ID, version, MOCK_APPROVAL_ID, markdown,
            )
        except TimeoutError:
            outcome = {"dependency_outcome": "failed", "comment_id": None, "created": False}
        else:
            outcome = {"dependency_outcome": "success", "comment_id": comment_id,
                       "created": created}
        print(json.dumps({"scenario_id": SCENARIO_ID, "attempt_number": number,
                          "confirmed_review_version": version,
                          "scope": "in_memory_dependency_fixture_only",
                          "comment_count": sink.comment_count, **outcome}))


if __name__ == "__main__":
    main()
