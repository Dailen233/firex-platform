"""Processing provider interface, the fixture provider, and the YOLO provider.

The provider turns a stored capture (record + normalized metadata + original
bytes + observation time) into a structured result. The service configuration
selects which provider (if any) runs; ``unconfigured`` means no provider, so
queued captures stay queued and no results are produced.

Two result shapes are supported (A2):

- 3D patch (fixture): ``patch_id`` + closed local ``geometry`` ring. The map
  treats a published patch as positive fire evidence.
- 2D detections (yolo): image-plane boxes with class/confidence, no world
  geometry. ``fire_detected`` is the explicit 2D verdict; ``None`` is never
  produced by yolo — an inference failure raises, so the capture fails instead
  of being mistaken for "no detection".
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .capture_metadata import CaptureMetadata
from .models import Detection2D

# Class names that count as positive fire evidence (same rule as C1).
FIRE_LABELS = {"fire", "flame", "fires"}


@dataclass
class ProcessingResult:
    result_origin: str
    provider_version: str
    patch_id: str | None = None
    geometry: list[list[float]] | None = None
    detections: list[Detection2D] = field(default_factory=list)
    fire_detected: bool | None = None
    model_ref: str | None = None
    threshold: float | None = None


class ProcessingProvider:
    name: str = ""
    version: str = ""

    def process(
        self,
        capture_id: str,
        meta: CaptureMetadata,
        original_bytes: bytes,
        observation_time_s: float,
    ) -> ProcessingResult:
        raise NotImplementedError


class FixtureProvider(ProcessingProvider):
    """Fixed, clearly-labeled fixture data — NOT an image reconstruction.

    Produces one stable ``patch_id`` whose geometry varies deterministically
    with the observation time, so two captures at different times yield two
    different contours for the same patch. ``result_origin="fixture"`` marks
    every result as interface test data (see also contracts/README.md).
    """

    name = "fixture"
    version = "1.0"
    PATCH_ID = "fixture-patch-1"

    def process(
        self,
        capture_id: str,
        meta: CaptureMetadata,
        original_bytes: bytes,
        observation_time_s: float,
    ) -> ProcessingResult:
        return ProcessingResult(
            result_origin="fixture",
            provider_version=self.version,
            patch_id=self.PATCH_ID,
            geometry=_fixture_geometry(observation_time_s),
        )


def _fixture_geometry(observation_time_s: float) -> list[list[float]]:
    """Preset square centered at a fixed local point; the half-extent grows with
    the observation time so distinct times produce distinct (closed) contours."""
    half = 5.0 + (observation_time_s % 20.0)
    x0, z0 = 100.0, 200.0
    return [
        [x0 - half, z0 - half],
        [x0 + half, z0 - half],
        [x0 + half, z0 + half],
        [x0 - half, z0 + half],
        [x0 - half, z0 - half],
    ]


def result_from_inference(payload: dict, weights_path: str) -> ProcessingResult:
    """Map one successful inference JSON payload to a ProcessingResult.

    ``fire_detected`` is derived from the model's own class names via the same
    fire-label rule as C1; zero fire-class boxes is a valid "no detection", not
    an error.
    """
    if payload.get("status") != "ok":
        raise ValueError(f"inference payload is not ok: {payload.get('errors') or payload}")
    raw_boxes = payload.get("raw_boxes") or []
    detections = [
        Detection2D(
            class_id=int(b["class_id"]),
            class_name=str(b["class_name"]),
            confidence=float(b["conf"]),
            bbox=[float(v) for v in b["xyxy"]],
        )
        for b in raw_boxes
    ]
    fire_detected = any(d.class_name.lower() in FIRE_LABELS for d in detections)
    model = payload.get("model") or {}
    sha = str(model.get("weights_sha256") or "")
    weight_name = Path(str(model.get("weights") or weights_path)).name
    model_ref = f"{weight_name}#{sha[:12]}" if sha else weight_name
    return ProcessingResult(
        result_origin="yolo",
        provider_version=YoloProvider.version,
        patch_id=None,
        geometry=None,
        detections=detections,
        fire_detected=fire_detected,
        model_ref=model_ref,
        threshold=float(model.get("conf")) if model.get("conf") is not None else None,
    )


class YoloProvider(ProcessingProvider):
    """Real 2D flame detection on the uploaded image (C1 environment).

    The uploaded bytes (hash-verified on receipt) are written to a temp file and
    passed to ``scripts/yolo_predict_single.py`` running in the C1 interpreter,
    which reuses C1's validated weight check and box extraction. Any weight or
    inference failure raises — the capture is marked failed and the previous
    observation (and its produced_at) stays untouched. There is no fixture
    fallback and no fabricated geometry.
    """

    name = "yolo"
    version = "1.0"
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "yolo_predict_single.py"

    def __init__(
        self,
        python: str | None = None,
        weights: str | None = None,
        weights_sha256: str | None = None,
        conf: float | None = None,
        imgsz: int | None = None,
        iou: float | None = None,
        device: str | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self._python = python or config.yolo_python()
        self._weights = weights or config.yolo_weights()
        self._weights_sha256 = weights_sha256 or config.yolo_weights_sha256()
        self._conf = config.yolo_conf() if conf is None else conf
        self._imgsz = config.yolo_imgsz() if imgsz is None else imgsz
        self._iou = config.yolo_iou() if iou is None else iou
        self._device = device or config.yolo_device()
        self._timeout_s = config.yolo_timeout_s() if timeout_s is None else timeout_s

    def process(
        self,
        capture_id: str,
        meta: CaptureMetadata,
        original_bytes: bytes,
        observation_time_s: float,
    ) -> ProcessingResult:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="firex-yolo-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(original_bytes)
            proc = subprocess.run(
                [
                    self._python,
                    str(self.SCRIPT),
                    tmp_path,
                    "--weights", self._weights,
                    "--weights-sha256", self._weights_sha256,
                    "--conf", str(self._conf),
                    "--imgsz", str(self._imgsz),
                    "--iou", str(self._iou),
                    "--device", self._device,
                ],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        stdout = (proc.stdout or "").strip()
        if proc.returncode != 0:
            detail = (proc.stderr or stdout or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit={proc.returncode}"
            raise RuntimeError(f"YOLO 推理失败（exit {proc.returncode}）: {tail[:400]}")
        if not stdout:
            raise RuntimeError("YOLO 推理无输出")
        try:
            payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"YOLO 推理输出不是合法 JSON: {exc}") from exc
        return result_from_inference(payload, self._weights)


def make_provider(mode: str) -> ProcessingProvider | None:
    if mode == "fixture":
        return FixtureProvider()
    if mode == "yolo":
        return YoloProvider()
    return None
