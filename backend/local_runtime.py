"""Factory used by the single-command local launcher."""

import os
from pathlib import Path

from backend.main import create_app


def create_local_app():
    data_root = os.environ.get('CONTRACT_LOCAL_DATA_ROOT')
    if not data_root:
        return create_app()
    root = Path(data_root)
    return create_app(database_path=root / 'contract_approval.sqlite3', upload_root=root / 'uploads')
