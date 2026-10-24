"""Backend configuration.

Paths are resolved from the repository root (not the process cwd), so starting
the service from any working directory points at the same default database and
capture storage.
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATA_DIR = REPO_ROOT / "runtime-data" / "backend"
DEFAULT_DB_FILENAME = "runs.sqlite3"
CAPTURES_DIRNAME = "captures"

# Upload limits (env-overridable; defaults documented in backend/README.md).
DEFAULT_MAX_CAPTURE_BYTES = 50 * 1024 * 1024  # 50 MiB per image
DEFAULT_MAX_METADATA_BYTES = 1 * 1024 * 1024  # 1 MiB metadata JSON
DEFAULT_MAX_CAPTURE_PIXELS = 100_000_000  # width * height


def data_dir() -> Path:
    return Path(os.environ.get("FIREX_BACKEND_DATA_DIR", str(DEFAULT_DATA_DIR)))


def db_path() -> Path:
    return data_dir() / DEFAULT_DB_FILENAME


def captures_dir() -> Path:
    return data_dir() / CAPTURES_DIRNAME


def max_capture_bytes() -> int:
    return int(os.environ.get("FIREX_CAPTURE_MAX_BYTES", str(DEFAULT_MAX_CAPTURE_BYTES)))


def max_metadata_bytes() -> int:
    return int(os.environ.get("FIREX_CAPTURE_MAX_METADATA_BYTES", str(DEFAULT_MAX_METADATA_BYTES)))


def max_capture_pixels() -> int:
    return int(os.environ.get("FIREX_CAPTURE_MAX_PIXELS", str(DEFAULT_MAX_CAPTURE_PIXELS)))
