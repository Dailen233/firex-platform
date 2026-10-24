"""Offline test upload for the captures endpoint (B2/B3).

Generates a clearly-labeled interface-test image and same-frame metadata, then
uploads them via multipart/form-data. The client verifies the backend's
``service`` identity on /health before sending any write request, so a wrong
target (e.g. another project on the same port) exits without POSTing.

Different captures use different ids and simulation times so the fixture worker
can produce distinct observations; retrying with the same id is idempotent.

This is interface-contract test data only — NOT a real inspection photo or a
reconstruction result.

Usage (from repo root; verified with the server on 127.0.0.1:8002):
    uv --directory backend run --locked python scripts/upload_test_capture.py \
        --base-url http://127.0.0.1:8002 --frame 1 <run_id>
    uv --directory backend run --locked python scripts/upload_test_capture.py \
        --base-url http://127.0.0.1:8002 --frame 2 <run_id>
"""
from __future__ import annotations

import argparse
import io
import json

import httpx
from PIL import Image

from app.upload_client import WrongServiceError, upload_capture

SCENE_ID = "shuangjiangkou_reference_terrain"
ASSET_VERSION = "reference-v1"
COORDINATE_FRAME_ID = "SJK_REFERENCE_UTM47N_EGM2008_v1"


def make_test_image(width: int = 32, height: int = 24) -> bytes:
    img = Image.new("RGB", (width, height), (200, 60, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_metadata(capture_id: str, width: int, height: int, simulation_time_s: float) -> dict:
    return {
        "schema_version": "1.0",
        "capture_id": capture_id,
        "scene_id": SCENE_ID,
        "asset_version": ASSET_VERSION,
        "coordinate_frame_id": COORDINATE_FRAME_ID,
        "width": width,
        "height": height,
        "intrinsics": {"fx": 60.0, "fy": 60.0, "cx": width / 2, "cy": height / 2},
        "distortion_model": "none",
        "pose": {"camera_to_world": [[1, 0, 0, 100], [0, 1, 0, 200], [0, 0, 1, 300], [0, 0, 0, 1]]},
        "simulation_time_s": simulation_time_s,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Backend base URL, e.g. http://127.0.0.1:8002")
    parser.add_argument("--capture-id", default=None, help="Capture id (defaults to cap-<run_id>-f<frame>)")
    parser.add_argument("--frame", type=int, default=1, help="Frame index used to derive the capture id and simulation time")
    parser.add_argument("--simulation-time", type=float, default=None, help="Simulation time in seconds (defaults to 15 + frame)")
    parser.add_argument("run_id", help="Existing run_id to attach the capture to")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    capture_id = args.capture_id or f"cap-{args.run_id}-f{args.frame:03d}"
    simulation_time_s = args.simulation_time if args.simulation_time is not None else 15.0 + args.frame

    image = make_test_image()
    metadata = json.dumps(make_metadata(capture_id, 32, 24, simulation_time_s))

    with httpx.Client(timeout=10.0) as client:
        try:
            resp = upload_capture(client, base_url, args.run_id, image, metadata)
        except WrongServiceError as exc:
            print(f"ERROR: {exc}")
            raise SystemExit(1)

    print(f"HTTP {resp.status_code}")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
