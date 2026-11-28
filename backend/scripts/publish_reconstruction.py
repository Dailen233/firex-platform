"""Local publish command: publish one offline reconstruction frame for a run.

Reads ``summary.json`` and ``<group_id>-voxels.ply`` from ``--results-dir``,
validates the run binding (scene / asset / coordinate frame / GLB SHA) and the
PLY (format, point count, size), then atomically advances the run's reconstruction
revision. A duplicate, older-time, or malformed frame never overwrites the latest
valid result.

Usage (from repo root; uses the backend venv):
    (cd backend && .venv/bin/python scripts/publish_reconstruction.py \\
        --run-id <id> --results-dir <dir> --group-id <group_id> [--data-dir <dir>])
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import db
from app.config import db_path, reconstruction_dir, sjk_glb_sha256
from app.reconstruction import DEFAULT_SOURCE, ReconstructionError, publish_frame


def main() -> int:
    parser = argparse.ArgumentParser(description="发布一帧离线多视角重建结果到指定 run")
    parser.add_argument("--run-id", required=True, help="目标 run_id")
    parser.add_argument("--results-dir", required=True, help="含 summary.json 与 <group>-voxels.ply 的目录")
    parser.add_argument("--group-id", required=True, help="要发布的 group_id（如 group_01）")
    parser.add_argument("--data-dir", default=None, help="后端数据目录（默认取 FIREX_BACKEND_DATA_DIR 或仓库默认）")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="结果来源标注")
    parser.add_argument("--glb-sha256", default=None, help="期望的 GLB SHA（默认双江口场景 GLB）")
    args = parser.parse_args()

    if args.data_dir:
        dd = Path(args.data_dir)
        dbp = dd / "runs.sqlite3"
        recon_dir = dd / "reconstruction"
    else:
        dbp = db_path()
        recon_dir = reconstruction_dir()

    db.init_db(dbp)
    try:
        summary = publish_frame(
            db_path=dbp,
            recon_dir=recon_dir,
            run_id=args.run_id,
            results_dir=Path(args.results_dir),
            group_id=args.group_id,
            source=args.source,
            expected_glb_sha256=args.glb_sha256 or sjk_glb_sha256(),
        )
    except ReconstructionError as exc:
        print(f"发布失败：{exc}", file=sys.stderr)
        return 1
    print(
        f"已发布 run={summary.run_id} revision={summary.revision} "
        f"group={summary.group_id} t={summary.simulation_time_s}s "
        f"voxels={summary.voxel_count} bytes={summary.byte_size} "
        f"sha256={summary.ply_sha256[:16]}…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
