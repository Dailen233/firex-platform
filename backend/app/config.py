"""Backend configuration.

Paths are resolved from the repository root (not the process cwd), so starting
the service from any working directory points at the same default database.
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATA_DIR = REPO_ROOT / "runtime-data" / "backend"
DEFAULT_DB_FILENAME = "runs.sqlite3"


def data_dir() -> Path:
    return Path(os.environ.get("FIREX_BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR)))


def db_path() -> Path:
    return data_dir() / DEFAULT_DB_FILENAME
