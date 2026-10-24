"""Serial background worker: claims queued captures and processes them one at a time.

The worker runs in its own thread so processing never blocks the HTTP event
loop. ``stop`` stops claiming new tasks and waits for the current one to finish,
so no background unit keeps writing the database after shutdown.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import results
from .config import WORKER_POLL_INTERVAL_S
from .provider import ProcessingProvider


class Worker:
    def __init__(self, db_path: Path, captures_dir: Path, provider: ProcessingProvider) -> None:
        self._db_path = db_path
        self._captures_dir = captures_dir
        self._provider = provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="firex-worker", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """Stop claiming new tasks and wait until the worker thread has actually exited.

        Blocks until the in-flight task truly finishes; only then is the thread
        reference cleared. A timeout that returned early would leave a live
        thread that can still write the database after shutdown.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            capture_id = results.claim_next_queued(self._db_path)
            if capture_id is None:
                if self._stop.wait(timeout=WORKER_POLL_INTERVAL_S):
                    break
                continue
            self._process(capture_id)

    def _process(self, capture_id: str) -> None:
        try:
            task, meta, original = results.load_for_processing(self._db_path, self._captures_dir, capture_id)
            outcome = self._provider.process(capture_id, meta, original, task.observation_time_s)
            results.complete_and_publish(self._db_path, task, outcome)
        except Exception as exc:  # noqa: BLE001 - worker must keep running on per-task failure
            results.fail_task(self._db_path, capture_id, f"{type(exc).__name__}: {exc}")
