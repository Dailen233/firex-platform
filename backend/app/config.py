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

# Background processing. Default is "unconfigured": captures stay queued and no
# result is produced. "fixture" must be explicitly enabled to run the fixture
# provider. Unknown values fall back to "unconfigured" (fail-safe: no processing).
PROCESSING_MODES = ("unconfigured", "fixture", "yolo")
DEFAULT_PROCESSING_MODE = "unconfigured"
WORKER_POLL_INTERVAL_S = 0.1

# A2 YOLO detection (C1-verified local environment). Inference runs in a separate
# interpreter that already has ultralytics/torch/cv2; the backend venv does not.
# The weights SHA is checked before every predict — a mismatch or missing file is
# a hard inference failure, never a fixture fallback.
DEFAULT_YOLO_PYTHON = "/home/dailen/vggt/vggt-env/bin/python"
DEFAULT_YOLO_WEIGHTS = "/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt"
DEFAULT_YOLO_WEIGHTS_SHA256 = "69b1f5c11edc646274c9fbb1ac4879d2874ad627b571c156ece45452b612087a"
DEFAULT_YOLO_CONF = 0.25
DEFAULT_YOLO_IMGSZ = 640
DEFAULT_YOLO_IOU = 0.45
DEFAULT_YOLO_DEVICE = "cpu"
DEFAULT_YOLO_TIMEOUT_S = 120

# A1 map feedback: seconds a published snapshot stays "fresh" (counts as a current
# alert). Older observations are kept but reported as stale/historical.
DEFAULT_FIRE_STATUS_FRESH_S = 120


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


def processing_mode() -> str:
    mode = os.environ.get("FIREX_PROCESSING_MODE", DEFAULT_PROCESSING_MODE).strip().lower()
    return mode if mode in PROCESSING_MODES else DEFAULT_PROCESSING_MODE


def monitored_run_ids() -> list[str]:
    """Explicitly monitored run_ids (comma-separated) for the map feedback loop.

    The map never hardcodes a run id and does not scan history for any red
    snapshot; only runs listed here enter the monitoring scope.
    """
    raw = os.environ.get("FIREX_MONITORED_RUN_IDS", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def fire_status_fresh_s() -> int:
    """Freshness window (seconds) for the atlas fire-status endpoint."""
    try:
        return max(1, int(os.environ.get("FIREX_FIRE_STATUS_FRESH_S", str(DEFAULT_FIRE_STATUS_FRESH_S))))
    except ValueError:
        return DEFAULT_FIRE_STATUS_FRESH_S


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def yolo_python() -> str:
    return _env_str("FIREX_YOLO_PYTHON", DEFAULT_YOLO_PYTHON)


def yolo_weights() -> str:
    return _env_str("FIREX_YOLO_WEIGHTS", DEFAULT_YOLO_WEIGHTS)


def yolo_weights_sha256() -> str:
    return _env_str("FIREX_YOLO_WEIGHTS_SHA256", DEFAULT_YOLO_WEIGHTS_SHA256)


def yolo_conf() -> float:
    return _env_float("FIREX_YOLO_CONF", DEFAULT_YOLO_CONF)


def yolo_imgsz() -> int:
    return _env_int("FIREX_YOLO_IMGSZ", DEFAULT_YOLO_IMGSZ)


def yolo_iou() -> float:
    return _env_float("FIREX_YOLO_IOU", DEFAULT_YOLO_IOU)


def yolo_device() -> str:
    return _env_str("FIREX_YOLO_DEVICE", DEFAULT_YOLO_DEVICE)


def yolo_timeout_s() -> int:
    return _env_int("FIREX_YOLO_TIMEOUT_S", DEFAULT_YOLO_TIMEOUT_S)
