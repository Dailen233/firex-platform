"""Export the currently-implemented OpenAPI snapshot to contracts/openapi.json.

Run from the repo root (``--directory`` sets the working directory to backend/):
``uv --directory backend run --locked python scripts/export_openapi.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "contracts" / "openapi.json"


def main() -> None:
    # Use a throwaway db so the export has no side effects on runtime-data.
    app = create_app(db_path_override=Path("/tmp/firex-openapi-export.sqlite3"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
