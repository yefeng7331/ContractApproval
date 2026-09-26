"""Poll durable DOCX jobs within the FastAPI service lifecycle."""

from __future__ import annotations

import logging
from threading import Event, Thread

from backend.docx_job import run_docx_once
from backend.jobs import JobStore


logger = logging.getLogger(__name__)


class DocxWorker:
    def __init__(self, jobs: JobStore, poll_seconds: float = 0.5, process_pdf: bool = False,
                 rule_snapshots=None, model_jobs=None, previews=None, process_ocr=False, reports=None, writebacks=None,
                 pending_imports=None) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.jobs = jobs
        self.process_pdf = process_pdf
        self.process_ocr = process_ocr
        self.rule_snapshots = rule_snapshots
        self.model_jobs = model_jobs
        self.previews = previews
        self.reports = reports
        self.writebacks = writebacks
        self.pending_imports = pending_imports
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
                if self.pending_imports is not None:
                    self.pending_imports.recover_expired()
                result = run_docx_once(self.jobs)
                if self.process_pdf:
                    from backend.pdf_job import run_pdf_once

                    run_pdf_once(self.jobs)
                if self.process_ocr:
                    from backend.ocr import run_ocr_once

                    run_ocr_once(self.jobs)
                if self.rule_snapshots is not None:
                    self.rule_snapshots.run_next()
                if self.model_jobs is not None:
                    self.model_jobs.run_next()
                if self.previews is not None:
                    self.previews.run_next()
                if self.reports is not None:
                    self.reports.run_next()
                if self.writebacks is not None:
                    self.writebacks.run_next()
            except Exception:
                logger.exception("DOCX parse worker failed; retrying after polling interval")
                self._stop.wait(self.poll_seconds)
                continue
            if result["status"] in ("busy", "no_pending_docx", "stale_lease"):
                self._stop.wait(self.poll_seconds)
