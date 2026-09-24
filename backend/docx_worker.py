"""Poll durable DOCX jobs within the FastAPI service lifecycle."""

from __future__ import annotations

import logging
from threading import Event, Thread

from backend.docx_job import run_docx_once
from backend.jobs import JobStore


logger = logging.getLogger(__name__)


class DocxWorker:
    def __init__(self, jobs: JobStore, poll_seconds: float = 0.5) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.jobs = jobs
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, name="docx-parse-worker")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = run_docx_once(self.jobs)
            except Exception:
                logger.exception("DOCX parse worker failed; retrying after polling interval")
                self._stop.wait(self.poll_seconds)
                continue
            if result["status"] in ("busy", "no_pending_docx", "stale_lease"):
                self._stop.wait(self.poll_seconds)
