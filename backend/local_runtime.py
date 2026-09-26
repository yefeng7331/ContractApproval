"""Factory used by the single-command local launcher."""

import os
from pathlib import Path

from backend.main import create_app


def create_local_app():
    data_root = os.environ.get('CONTRACT_LOCAL_DATA_ROOT')
    processing = os.environ.get('CONTRACT_LOCAL_PROCESSING') == '1'
    storage = {} if not data_root else {
        'database_path': Path(data_root) / 'contract_approval.sqlite3',
        'upload_root': Path(data_root) / 'uploads',
    }
    if not processing:
        return create_app(**storage)
    return create_app(**storage, auto_process_docx=True, auto_process_pdf=True,
                      auto_process_ocr=True, auto_process_rules=True,
                      auto_process_models=True, auto_process_previews=True,
                      auto_process_reports=True, auto_process_writebacks=True)
