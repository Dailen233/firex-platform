"""A changing image produces changing local geometry; absent/failing geometry is optional."""
from __future__ import annotations

import base64
import io
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import flame_surface
from app.capture_metadata import CaptureMetadata
from app.main import create_app
from app.models import Detection2D
from app.provider import ProcessingResult

RUN = dict(
    zip(("scene_id", "asset_version", "coordinate_frame_id"), flame_surface.SCENE_BINDING),
    plant_id=flame_surface.PLANT_ID, input_source="simulation", simulation_time_origin_s=0,
)
BOX = Detection2D(class_id=0, class_name="fire", confidence=0.7, bbox=[85, 40, 235, 170])
POSE = [
    [1, 0, 0, 0],
    [0, -0.8, -0.6, 330],
    [0, 0.6, -0.8, 400],
    [0, 0, 0, 1],
]


def meta(capture_id: str, t: float) -> CaptureMetadata:
    return CaptureMetadata(
        **{key: RUN[key] for key in ("scene_id", "asset_version", "coordinate_frame_id")},
        schema_version="1.0", capture_id=capture_id, simulation_time_s=t,
        width=320, height=240, intrinsics={"fx": 280, "fy": 280, "cx": 160, "cy": 120},
        pose={"camera_to_world": POSE},
    )


def image(tip_row: int | None) -> bytes:
    src = Image.new("RGB", (320, 240), (42, 45, 43))
    if tip_row is not None:
        draw = ImageDraw.Draw(src)
        draw.polygon([(112, 153), (140, 90), (165, tip_row), (181, 96), (214, 151)], fill=(247, 135, 17))
    out = io.BytesIO()
    src.save(out, "PNG")
    return out.getvalue()


def test_real_terrain_intersection_and_new_image_change_the_projected_surface():
    assert flame_surface._terrain_hit((0, 4000, 0), (0, -1, 0)) == pytest.approx((0, 34.895088, 0), abs=1e-4)
    a = flame_surface.estimate_flame(meta("a", 1), image(70), BOX)
    b = flame_surface.estimate_flame(meta("b", 2), image(47), BOX)
    assert a is not None and b is not None
    assert a.glb_sha256 == flame_surface.GLB_SHA256 and a.capture_id == "a"
    with Image.open(io.BytesIO(base64.b64decode(a.texture_png_base64))) as texture:
        assert max(texture.size) <= 128
        assert texture.getchannel("A").getextrema() == (0, 255)
        assert (247, 135, 17, 255) in list(zip(*(channel.tobytes() for channel in texture.split())))
    assert max(v[1] for v in b.vertices) > max(v[1] for v in a.vertices)
    # All surface samples are on the vertical plane through the terrain anchor.
    x, _, z = a.anchor_xyz_m
    nx, nz = POSE[0][3] - x, POSE[2][3] - z
    assert all((v[0] - x) * nx + (v[2] - z) * nz == pytest.approx(0, abs=1e-6) for v in a.vertices)


def test_wrong_binding_or_no_usable_pixels_has_no_section():
    assert flame_surface.estimate_flame(meta("a", 1), image(None), BOX) is None
    wrong_asset = meta("b", 2).model_copy(update={"asset_version": "other"})
    assert flame_surface.estimate_flame(wrong_asset, image(70), BOX) is None
    clipped = BOX.model_copy(update={"bbox": [85, 40, 235, 240]})
    assert flame_surface.estimate_flame(meta("c", 3), image(70), clipped) is None


def test_upload_publishes_frame_bound_geometry_and_new_negative_clears_it(tmp_path, monkeypatch):
    class RecordedProvider:
        def process(self, capture_id, metadata, original, observation_time_s):
            fire = capture_id != "negative"
            return ProcessingResult(
                result_origin="yolo", provider_version="1.0",
                detections=[BOX] if fire else [], fire_detected=fire,
            )

    monkeypatch.setattr("app.main.make_provider", lambda mode: RecordedProvider())
    monkeypatch.setenv("FIREX_FIRE_STATUS_FRESH_S", "90")
    with TestClient(create_app(tmp_path / "runs.sqlite3", tmp_path / "captures", "yolo")) as client:
        created = client.post("/api/v1/runs", json=RUN)
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        base = f"/api/v1/runs/{run_id}"

        def upload(capture_id: str, t: float, pixels: bytes):
            data = meta(capture_id, t)
            response = client.post(
                f"{base}/captures",
                files={"file": ("capture.png", pixels, "image/png")},
                data={"metadata": data.model_dump_json(exclude_none=True)},
            )
            assert response.status_code == 202, response.text
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                record = client.get(f"/api/v1/captures/{capture_id}").json()
                if record["status"] in {"completed", "failed"}:
                    assert record["status"] == "completed", record["processing_error"]
                    return client.get(f"{base}/state").json()
                time.sleep(0.02)
            pytest.fail(f"{capture_id} did not finish processing")

        a = upload("positive-1", 1, image(70))
        assert a["patches"] == [] and a["revision"] == 1
        assert a["flame"]["capture_id"] == a["evidence_capture_ids"][0] == "positive-1"
        expires, produced = [datetime.fromisoformat(a[k]) for k in ("observation_expires_at", "produced_at")]
        assert (expires - produced).total_seconds() == 90

        b = upload("positive-2", 2, image(47))
        assert b["revision"] == 2 and b["flame"]["capture_id"] == "positive-2"
        assert b["flame"]["vertices"] != a["flame"]["vertices"]
        assert upload("older", 1.5, image(75)) == b

        # A malformed/unavailable asset must not make the YOLO observation fail.
        def missing_terrain(*args):
            raise FileNotFoundError("test: terrain did not load")

        monkeypatch.setattr(flame_surface, "estimate_flame", missing_terrain)
        missing = upload("positive-without-geometry", 3, image(60))
        assert missing["revision"] == 3 and missing["fire_detected"] and missing["flame"] is None
        no_fire = upload("negative", 4, image(None))
        assert no_fire["revision"] == 4 and not no_fire["fire_detected"] and no_fire["flame"] is None
