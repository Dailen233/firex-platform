"""Capture metadata contract (B2).

Camera conventions (pixel + camera axes + pose). World axes, units and elevation
semantics are defined by ``coordinate_frame_id`` and are NOT inferred from its
name here.

- Pixel coordinate origin: top-left corner; x right (columns), y down (rows).
- Intrinsics in pixels: ``fx``, ``fy`` focal lengths; ``cx``, ``cy`` principal point.
- Camera axes: x right, y down, z forward (right-handed).
- Pose: ``camera_to_world`` 4x4, row-major storage, column-vector convention:
  ``p_world = T_camera_to_world @ p_camera``. The rotation part must be a proper
  rotation (orthonormal with determinant ~= +1); mirror/reflection transforms
  (determinant -1) are rejected.

Only distortion_model ``"none"`` (already undistorted) is accepted in this first
version; any other model is rejected rather than silently ignored.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

METADATA_SCHEMA_VERSION = "1.0"

_SAFE_ID = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


class Intrinsics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fx: float
    fy: float
    cx: float
    cy: float

    @model_validator(mode="after")
    def _validate(self) -> "Intrinsics":
        for name in ("fx", "fy", "cx", "cy"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"intrinsics.{name} must be finite")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("intrinsics.fx and intrinsics.fy must be positive")
        return self


class CameraPose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_to_world: list[list[float]]

    @field_validator("camera_to_world")
    @classmethod
    def _validate_matrix(cls, m: list[list[float]]) -> list[list[float]]:
        if len(m) != 4 or any(len(row) != 4 for row in m):
            raise ValueError("camera_to_world must be a 4x4 matrix")
        for row in m:
            for v in row:
                if not math.isfinite(v):
                    raise ValueError("camera_to_world values must be finite")
        if m[3] != [0.0, 0.0, 0.0, 1.0]:
            raise ValueError("camera_to_world last row must be [0,0,0,1]")
        # rotation part (top-left 3x3) must be orthonormal AND a proper rotation:
        # reject reflections (det = -1), do not silently fix the client matrix.
        for i in range(3):
            for j in range(3):
                dot = sum(m[i][k] * m[j][k] for k in range(3))
                expected = 1.0 if i == j else 0.0
                if abs(dot - expected) > 1e-4:
                    raise ValueError("camera_to_world rotation part must be orthonormal")
        det = (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )
        if abs(det - 1.0) > 1e-4:
            raise ValueError("camera_to_world rotation part must be a proper rotation (determinant ~= +1)")
        return m


class CaptureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    capture_id: str
    scene_id: str
    asset_version: str
    coordinate_frame_id: str
    width: int
    height: int
    intrinsics: Intrinsics
    distortion_model: Literal["none"] = "none"
    pose: CameraPose
    simulation_time_s: float | None = None
    captured_at: datetime | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, v: str) -> str:
        if v != METADATA_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be '{METADATA_SCHEMA_VERSION}'")
        return v

    @field_validator("capture_id")
    @classmethod
    def _validate_capture_id(cls, v: str) -> str:
        if not (1 <= len(v) <= 128 and all(c in _SAFE_ID for c in v)):
            raise ValueError("capture_id must be 1-128 chars of [A-Za-z0-9_-]")
        return v

    @field_validator("width", "height")
    @classmethod
    def _validate_dim(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("width/height must be positive")
        return v

    @field_validator("simulation_time_s")
    @classmethod
    def _validate_sim_time(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("simulation_time_s must be finite")
        return v

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware (UTC offset required)")
        return v.astimezone(timezone.utc)


def canonical_metadata_json(meta: CaptureMetadata) -> str:
    """Deterministic JSON (sorted keys, compact) for stable hashing."""
    return json.dumps(meta.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def camera_position_world(pose: CameraPose) -> list[float]:
    """Camera position in world coordinates = translation part of camera_to_world."""
    return [pose.camera_to_world[i][3] for i in range(3)]


def center_ray_world(pose: CameraPose) -> list[float]:
    """Center ray direction in world = R @ [0,0,1] (forward axis)."""
    return [pose.camera_to_world[i][2] for i in range(3)]
