"""Pydantic request/response models for the B1 API surface."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .time_contract import TIME_BASIS

InputSource = Literal["simulation", "real"]
ProcessingMode = Literal["unconfigured", "fixture", "yolo"]

SCHEMA_VERSION = "1.0"

# Simulation clock range: origin must be finite and non-negative (simulator clock).
MAX_SIM_TIME_S = 1e12


class RunCreate(BaseModel):
    plant_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    asset_version: str = Field(min_length=1)
    coordinate_frame_id: str | None = None
    input_source: InputSource
    simulation_time_origin_s: float | None = None
    time_origin_utc: datetime | None = None

    @field_validator("simulation_time_origin_s")
    @classmethod
    def _validate_sim_origin(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not math.isfinite(v) or v < 0 or v > MAX_SIM_TIME_S:
            raise ValueError("simulation_time_origin_s must be a finite number in [0, 1e12]")
        return v

    @field_validator("time_origin_utc")
    @classmethod
    def _validate_time_origin_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("time_origin_utc must be timezone-aware (UTC offset required)")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_time_config(self) -> "RunCreate":
        if self.input_source == "simulation":
            if self.simulation_time_origin_s is None:
                raise ValueError("simulation_time_origin_s is required when input_source='simulation'")
            if self.time_origin_utc is not None:
                raise ValueError("time_origin_utc must not be set when input_source='simulation'")
        else:  # real
            if self.time_origin_utc is None:
                raise ValueError("time_origin_utc is required when input_source='real'")
            if self.simulation_time_origin_s is not None:
                raise ValueError("simulation_time_origin_s must not be set when input_source='real'")
        return self


class RunRecord(BaseModel):
    run_id: str
    plant_id: str
    scene_id: str
    asset_version: str
    coordinate_frame_id: str | None
    input_source: InputSource
    created_at: datetime
    schema_version: str
    simulation_time_origin_s: float | None
    time_origin_utc: datetime | None


class FirePatch(BaseModel):
    """A fire polygon in minimal local XZ coordinates.

    ``geometry`` is an ordered ring of ``[x, z]`` pairs that closes on itself
    (first vertex == last vertex). All values must be finite. This is the local
    surface frame; world meaning comes from ``coordinate_frame_id``.
    """

    patch_id: str
    geometry: list[list[float]]

    @field_validator("patch_id")
    @classmethod
    def _validate_patch_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("patch_id must be non-empty")
        return v

    @field_validator("geometry")
    @classmethod
    def _validate_geometry(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 4:
            raise ValueError("patch geometry must be a closed ring with at least 3 vertices")
        for p in v:
            if len(p) != 2 or not all(math.isfinite(x) for x in p):
                raise ValueError("patch geometry vertices must be finite [x, z] pairs")
        if v[0] != v[-1]:
            raise ValueError("patch geometry must be closed (first vertex == last vertex)")
        return v


class Detection2D(BaseModel):
    """A single 2D detection box in original image pixels (A2 YOLO output).

    ``bbox`` is ``[x1, y1, x2, y2]`` with ``x2 > x1``, ``y2 > y1`` and all values
    finite. This is image-plane evidence only — it never claims world position.
    """

    class_id: int
    class_name: str
    confidence: float
    bbox: list[float]

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be a finite number in [0, 1]")
        return v

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, v: list[float]) -> list[float]:
        if len(v) != 4 or not all(math.isfinite(x) for x in v):
            raise ValueError("bbox must be four finite numbers [x1, y1, x2, y2]")
        x1, y1, x2, y2 = v
        if not (x2 > x1 and y2 > y1):
            raise ValueError("bbox must have positive area (x2 > x1 and y2 > y1)")
        return v


class RunState(BaseModel):
    run_id: str
    plant_id: str
    scene_id: str
    asset_version: str
    coordinate_frame_id: str | None
    input_source: InputSource
    schema_version: str
    state_status: str
    revision: int
    observation_time_s: float | None
    result_origin: str | None
    provider_version: str | None
    evidence_capture_ids: list[str]
    patches: list[FirePatch]
    produced_at: datetime
    time_basis: str
    simulation_time_origin_s: float | None
    time_origin_utc: datetime | None
    # A2: 2D observation fields. ``fire_detected`` is the explicit 2D verdict from
    # a detection provider (None for providers that only publish 3D patches, e.g.
    # fixture, and for snapshots written before A2 — the map then falls back to
    # patches). Detections are image-plane boxes, never world geometry.
    detections: list[Detection2D] = []
    fire_detected: bool | None = None
    model_ref: str | None = None
    threshold: float | None = None


class CaptureRecord(BaseModel):
    """A received capture and its processing status (queued/processing/completed/failed)."""

    capture_id: str
    run_id: str
    received_at: datetime
    observation_time_s: float
    content_sha256: str
    byte_size: int
    status: str
    schema_version: str
    storage_key: str
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    processing_error: str | None = None
    provider_version: str | None = None


AlertStatus = Literal["no_observation", "no_detection", "fire", "stale"]


class AtlasFireStatusItem(BaseModel):
    """Per-run map feedback summary (A1).

    ``alert_status`` is the derived display state; ``fire_detected``/``is_fresh``
    expose the two raw inputs it is computed from. Only ``fire`` is a current
    alert; ``stale`` observations stay visible but are historical.
    """

    plant_id: str
    run_id: str
    scene_id: str
    asset_version: str
    coordinate_frame_id: str | None
    input_source: InputSource
    state_status: str
    alert_status: AlertStatus
    fire_detected: bool
    is_fresh: bool
    revision: int
    observation_time_s: float | None
    time_basis: str
    result_origin: str | None
    provider_version: str | None
    produced_at: datetime | None
    evidence_capture_ids: list[str]
    patch_count: int
    detection_count: int
    model_ref: str | None
    threshold: float | None


class AtlasFireStatus(BaseModel):
    generated_at: datetime
    fresh_after_s: int
    monitored_run_ids: list[str]
    items: list[AtlasFireStatusItem]


class HealthResponse(BaseModel):
    status: str
    algorithm_mode: str
    service: str = "firex-backend"
    processing_mode: str = "unconfigured"


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
