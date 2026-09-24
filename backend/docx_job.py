"""Run one queued DOCX parse using the current version's exclusive lease."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread

from backend.auth import AuthStore
from backend.clause_extractor import extract_clauses
from backend.docx_parser import MAX_DOCX_BYTES, DocxParseError, parse_docx
from backend.jobs import JobStore
from backend.main import default_database_path, default_upload_root
from backend.metadata_extractor import extract_metadata
from backend.tasks import TaskStore


logger = logging.getLogger(__name__)


@contextmanager
def _renew_lease(jobs: JobStore, lease, interval_seconds: float = 20):
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    stop = Event()

    def heartbeat() -> None:
        while not stop.wait(interval_seconds):
            try:
                if not jobs.renew(lease):
                    return
            except Exception:
                logger.exception("DOCX parse lease renewal failed")
                return

    thread = Thread(target=heartbeat, name="docx-lease-heartbeat")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def run_docx_once(jobs: JobStore) -> dict:
    lease = jobs.claim_next(file_format="docx")
    if lease is None:
        return {"status": "busy" if jobs.has_unfinished(file_format="docx") else "no_pending_docx"}
    with _renew_lease(jobs, lease):
        return _process_claimed_docx(jobs, lease)


def _process_claimed_docx(jobs: JobStore, lease) -> dict:
    try:
        path = Path(lease.file_path)
        if path.stat().st_size > MAX_DOCX_BYTES:
            content = None
        else:
            content = path.read_bytes()
    except OSError:
        code, reason = "ATTACHMENT_UNREADABLE", "DOCX 原件无法读取，请重新上传"
    else:
        if content is None or len(content) > MAX_DOCX_BYTES:
            code, reason = "DOCX_UNREADABLE", "DOCX 原件已超出大小限制，请重新上传"
        elif hashlib.sha256(content).hexdigest() != lease.sha256:
            code, reason = "ATTACHMENT_CHANGED", "DOCX 原件与提交时的摘要不一致，请重新上传"
        else:
            try:
                parsed = parse_docx(content, lease.document_version)
                metadata = extract_metadata(parsed)
                clauses = extract_clauses(parsed)
            except DocxParseError as error:
                code, reason = error.code, str(error)
            else:
                saved = jobs.complete_docx(lease, parsed, metadata, clauses)
                return {
                    "task_id": lease.task_id,
                    "document_version": lease.document_version,
                    "status": "reviewing" if saved else "stale_lease",
                }
    blocked = jobs.block_parse(lease, code, reason)
    return {
        "task_id": lease.task_id,
        "document_version": lease.document_version,
        "status": "blocked" if blocked else "stale_lease",
        "code": code if blocked else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one pending synthetic DOCX parse job")
    parser.add_argument("--database", type=Path, default=default_database_path())
    parser.add_argument("--uploads", type=Path, default=default_upload_root())
    args = parser.parse_args()
    store = AuthStore(args.database)
    try:
        store.initialize()
        tasks = TaskStore(store, args.uploads)
        tasks.initialize()
        print(json.dumps(run_docx_once(tasks.jobs), ensure_ascii=False))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
