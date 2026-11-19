"""Serial reconstruction worker: claims queued ZIP jobs and reconstructs them one at a time.

Runs in its own thread so reconstruction never blocks the HTTP event loop and
never shares the YOLO worker queue. Each job validates the ZIP (zip-bomb guard),
runs the offline reconstruction script in single-group mode with terrain clip,
then publishes the frame via ``reconstruction.publish_frame``. A failure marks
the job failed and never changes the published revision.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from . import reconstruction, reconstruction_jobs
from .config import (
    WORKER_POLL_INTERVAL_S,
    recon_python,
    recon_run_timeout_s,
    recon_script,
    recon_unzip_max_bytes,
    recon_unzip_max_entries,
    recon_voxel_m,
)
from .reconstruction import ReconstructionError

logger = logging.getLogger(__name__)


class ReconstructionWorker:
    def __init__(self, db_path: Path, jobs_dir: Path, recon_dir: Path) -> None:
        self._db_path = db_path
        self._jobs_dir = jobs_dir
        self._recon_dir = recon_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="firex-reconstruction-worker", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = reconstruction_jobs.claim_next_job(self._db_path)
            if job_id is None:
                if self._stop.wait(timeout=WORKER_POLL_INTERVAL_S):
                    break
                continue
            self._process(job_id)

    def _process(self, job_id: str) -> None:
        started = time.monotonic()
        try:
            task = reconstruction_jobs.load_job(self._db_path, self._jobs_dir, job_id)
            self._validate_zip(task.zip_path)
            with tempfile.TemporaryDirectory(prefix="firex-recon-") as tmp:
                out = Path(tmp) / "out"
                self._run_script(task.zip_path, out)
                group_id, sim_time, voxel_count, mask_source = self._read_summary(out)
                published = reconstruction.publish_frame(
                    self._db_path, self._recon_dir, task.run_id, out, group_id,
                    source=reconstruction_jobs.SOURCE_UPLOADED_ZIP,
                )
                reconstruction_jobs.complete_job(
                    self._db_path, job_id,
                    simulation_time_s=sim_time, group_id=group_id,
                    voxel_count=voxel_count, mask_source=mask_source,
                    revision=published.revision,
                )
            logger.info(
                "Reconstruction job %s completed in %.1fs (revision=%d, voxels=%d)",
                job_id, time.monotonic() - started, published.revision, voxel_count,
            )
        except Exception as exc:  # noqa: BLE001 - worker must keep running on per-job failure
            logger.warning("Reconstruction job %s failed: %s", job_id, exc)
            reconstruction_jobs.fail_job(self._db_path, job_id, f"{type(exc).__name__}: {exc}")

    def _validate_zip(self, zip_path: Path) -> None:
        try:
            with ZipFile(zip_path) as archive:
                infos = archive.infolist()
                if len(infos) > recon_unzip_max_entries():
                    raise ValueError(f"ZIP 条目数 {len(infos)} 超过上限 {recon_unzip_max_entries()}")
                total = sum(info.file_size for info in infos)
                if total > recon_unzip_max_bytes():
                    raise ValueError(f"ZIP 解压总量 {total} 字节超过上限 {recon_unzip_max_bytes()}")
        except BadZipFile as exc:
            raise ValueError(f"不是有效的 ZIP：{exc}") from exc

    def _run_script(self, zip_path: Path, out: Path) -> None:
        proc = subprocess.run(
            [
                recon_python(), str(recon_script()), str(zip_path),
                "--voxel-m", str(recon_voxel_m()),
                "--terrain-clip", "--single-group",
                "--out", str(out),
            ],
            capture_output=True,
            text=True,
            timeout=recon_run_timeout_s(),
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit={proc.returncode}"
            raise RuntimeError(f"重建失败（exit {proc.returncode}）: {tail[:400]}")

    def _read_summary(self, out: Path) -> tuple[str, float, int, str | None]:
        summary_path = out / "summary.json"
        if not summary_path.is_file():
            raise ReconstructionError("重建未产出 summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        groups = summary.get("groups") or []
        if len(groups) != 1:
            raise ReconstructionError(f"单组模式应恰好一个分组，实际 {len(groups)} 个")
        group = groups[0]
        group_id = group.get("group_id")
        sim_time = group.get("simulation_time_s")
        voxel_count = group.get("candidate_voxel_count")
        mask_source = group.get("mask_source") or None
        if not isinstance(group_id, str) or not isinstance(sim_time, (int, float)) or not isinstance(voxel_count, int):
            raise ReconstructionError("重建摘要字段缺失或类型错误")
        return group_id, float(sim_time), voxel_count, mask_source
