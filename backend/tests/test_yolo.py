"""A2 YOLO provider: inference mapping, 2D snapshot persistence, and failure isolation.

The real model is only exercised by the live acceptance run; these tests cover
the pure mapping, the snapshot/state round-trip, ordering rules, and the
requirement that an inference failure is recorded as a failed capture (never as
"no detection" and never refreshing the previous observation).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from app import db, results
from app.atlas import derive_fire_status_item
from app.capture_metadata import CaptureMetadata
from app.capture_store import get_capture, save_capture
from app.models import Detection2D, FirePatch, RunCreate, RunRecord, RunState
from app.provider import ProcessingResult, YoloProvider, result_from_inference
from app.store import create_run
from app.worker import Worker

NOW = datetime.now(timezone.utc)
WEIGHTS = "/home/dailen/vggt/runs/detect/train_full_v1/weights/best.pt"


def _fire_payload(conf: float = 0.864) -> dict:
    return {
        "status": "ok",
        "width": 1100,
        "height": 492,
        "num_raw": 1,
        "num_fire": 1,
        "raw_boxes": [{"class_id": 0, "class_name": "fire", "conf": conf, "xyxy": [512.0, 200.0, 604.0, 352.0]}],
        "fire_boxes": [{"class_id": 0, "class_name": "fire", "conf": conf, "xyxy": [512.0, 200.0, 604.0, 352.0]}],
        "inference_seconds": 1.2,
        "model": {
            "weights": WEIGHTS,
            "weights_sha256": "69b1f5c11edc646274c9fbb1ac4879d2874ad627b571c156ece45452b612087a",
            "task": "detect",
            "names": {"0": "fire"},
            "conf": 0.25,
            "imgsz": 640,
            "iou": 0.45,
            "device": "cpu",
        },
    }


class TestInferenceMapping:
    def test_fire_payload_maps_to_positive_yolo_result(self):
        r = result_from_inference(_fire_payload(), WEIGHTS)
        assert r.result_origin == "yolo"
        assert r.patch_id is None and r.geometry is None
        assert r.fire_detected is True
        assert len(r.detections) == 1
        d = r.detections[0]
        assert isinstance(d, Detection2D)
        assert (d.class_id, d.class_name, d.confidence) == (0, "fire", 0.864)
        assert d.bbox == [512.0, 200.0, 604.0, 352.0]
        assert r.model_ref == "best.pt#69b1f5c11edc"
        assert r.threshold == 0.25

    def test_zero_boxes_is_valid_no_detection(self):
        payload = _fire_payload()
        payload["raw_boxes"] = []
        payload["fire_boxes"] = []
        payload["num_raw"] = payload["num_fire"] = 0
        r = result_from_inference(payload, WEIGHTS)
        assert r.fire_detected is False
        assert r.detections == []
        assert r.patch_id is None

    def test_error_payload_is_rejected_not_mapped_to_no_detection(self):
        payload = {"status": "error", "errors": ["权重 SHA256 不符"], "model": {}}
        with pytest.raises(ValueError, match="权重"):
            result_from_inference(payload, WEIGHTS)


class TestAtlasDerive:
    @staticmethod
    def _run() -> RunRecord:
        return RunRecord(
            run_id="r", plant_id="p", scene_id="s", asset_version="v",
            coordinate_frame_id=None, input_source="simulation",
            created_at=NOW, schema_version="1.0",
            simulation_time_origin_s=10.0, time_origin_utc=None,
        )

    @staticmethod
    def _state(fire: bool | None, boxes: int) -> RunState:
        return RunState(
            run_id="r", plant_id="p", scene_id="s", asset_version="v",
            coordinate_frame_id=None, input_source="simulation", schema_version="1.0",
            state_status="observation", revision=2, observation_time_s=7.0,
            result_origin="yolo", provider_version="1.0", evidence_capture_ids=["c"],
            patches=[], produced_at=NOW,
            time_basis="simulation_relative", simulation_time_origin_s=10.0, time_origin_utc=None,
            detections=[
                Detection2D(class_id=0, class_name="fire", confidence=0.9, bbox=[1.0, 2.0, 3.0, 4.0])
                for _ in range(boxes)
            ],
            fire_detected=fire,
            model_ref="best.pt#69b1f5c11edc",
            threshold=0.25,
        )

    def test_yolo_fire(self):
        item = derive_fire_status_item(self._run(), self._state(True, 1), 120, NOW)
        assert item.alert_status == "fire"
        assert item.fire_detected is True
        assert item.patch_count == 0
        assert item.detection_count == 1
        assert item.model_ref == "best.pt#69b1f5c11edc"
        assert item.threshold == 0.25

    def test_yolo_no_detection(self):
        item = derive_fire_status_item(self._run(), self._state(False, 0), 120, NOW)
        assert item.alert_status == "no_detection"
        assert item.fire_detected is False
        assert item.detection_count == 0

    def test_patch_provider_without_verdict_falls_back_to_patches(self):
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        state = self._state(None, 0).model_copy(
            update={
                "result_origin": "fixture",
                "patches": [FirePatch(patch_id="p1", geometry=ring)],
            }
        )
        item = derive_fire_status_item(self._run(), state, 120, NOW)
        assert item.alert_status == "fire"  # patch evidence still counts


class TestSnapshotPersistence:
    @staticmethod
    def _setup(tmp_path: Path) -> Path:
        path = tmp_path / "runs.sqlite3"
        db.init_db(path)
        conn = db.connect(path)
        conn.execute(
            "INSERT INTO runs (run_id, plant_id, scene_id, asset_version, coordinate_frame_id, "
            "input_source, created_at, schema_version, simulation_time_origin_s, time_origin_utc) "
            "VALUES ('r1', 'GEM_HYDRO_SHUANGJIANGKOU', 'scene', 'v1', 'F1', 'simulation', ?, '1.0', 10.0, NULL)",
            (NOW.isoformat(),),
        )
        conn.commit()
        conn.close()
        return path

    @staticmethod
    def _task(capture_id: str, observation_time_s: float) -> results.CaptureTask:
        return results.CaptureTask(
            capture_id=capture_id, run_id="r1", plant_id="GEM_HYDRO_SHUANGJIANGKOU",
            scene_id="scene", asset_version="v1", coordinate_frame_id="F1",
            input_source="simulation", observation_time_s=observation_time_s,
            content_sha256="a" * 64, byte_size=1, metadata_sha256="b" * 64, storage_key="k",
        )

    @staticmethod
    def _yolo_result(fire: bool, conf: float = 0.8) -> ProcessingResult:
        boxes = (
            [Detection2D(class_id=0, class_name="fire", confidence=conf, bbox=[10.0, 20.0, 30.0, 40.0])]
            if fire
            else []
        )
        return ProcessingResult(
            result_origin="yolo", provider_version="1.0", detections=boxes,
            fire_detected=fire, model_ref="best.pt#69b1f5c11edc", threshold=0.25,
        )

    def test_yolo_snapshot_round_trip_without_patch(self, tmp_path: Path):
        path = self._setup(tmp_path)
        results.complete_and_publish(path, self._task("c1", 6.0), self._yolo_result(True))
        snap = results.get_snapshot(path, "r1")
        assert snap is not None
        assert snap.patches == []  # no fabricated 3D geometry for the map
        assert len(snap.detections) == 1
        assert snap.fire_detected is True
        assert snap.model_ref == "best.pt#69b1f5c11edc"
        assert snap.threshold == 0.25

    def test_newer_no_detection_ends_alert_older_cannot_overwrite(self, tmp_path: Path):
        path = self._setup(tmp_path)
        results.complete_and_publish(path, self._task("c-fire", 6.0), self._yolo_result(True))
        results.complete_and_publish(path, self._task("c-none", 7.0), self._yolo_result(False))
        snap = results.get_snapshot(path, "r1")
        assert snap is not None and snap.observation_time_s == 7.0 and snap.fire_detected is False
        # an older capture (t=5) must not roll the snapshot back
        results.complete_and_publish(path, self._task("c-old", 5.0), self._yolo_result(True))
        snap = results.get_snapshot(path, "r1")
        assert snap is not None and snap.observation_time_s == 7.0 and snap.fire_detected is False

    @staticmethod
    def _png() -> bytes:
        img = Image.new("RGB", (8, 6), (10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _metadata(capture_id: str, simulation_time_s: float) -> CaptureMetadata:
        return CaptureMetadata(
            schema_version="1.0", capture_id=capture_id, scene_id="scene", asset_version="v1",
            coordinate_frame_id="F1", width=8, height=6,
            intrinsics={"fx": 5.0, "fy": 5.0, "cx": 4.0, "cy": 3.0},
            distortion_model="none",
            pose={"camera_to_world": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]},
            simulation_time_s=simulation_time_s,
        )

    def test_inference_failure_is_failed_capture_not_no_detection(self, tmp_path: Path):
        path = self._setup(tmp_path)
        captures_dir = tmp_path / "captures"
        captures_dir.mkdir()

        run = create_run(path, RunCreate(
            plant_id="GEM_HYDRO_SHUANGJIANGKOU", scene_id="scene", asset_version="v1",
            coordinate_frame_id="F1", input_source="simulation", simulation_time_origin_s=10.0,
        ))
        results.complete_and_publish(path, self._task("c-fire", 6.0), self._yolo_result(True))
        before = results.get_snapshot(path, "r1")
        assert before is not None and before.fire_detected is True

        meta = self._metadata("c-boom", 17.0)
        record, _is_new = save_capture(
            path, captures_dir, run, meta, meta.model_dump_json(), self._png()
        )

        class Boom(YoloProvider):
            def process(self, capture_id, meta, original_bytes, observation_time_s):
                raise RuntimeError("权重 SHA256 不符：期望 ... 实际 ...")

        Worker(path, captures_dir, Boom())._process(record.capture_id)

        failed = get_capture(path, record.capture_id)
        assert failed is not None and failed.status == "failed"
        assert failed.processing_error and "权重" in failed.processing_error
        after = results.get_snapshot(path, "r1")
        assert after is not None
        # previous observation untouched: same revision, time, verdict and produced_at
        assert (after.revision, after.observation_time_s, after.fire_detected) == (
            before.revision, before.observation_time_s, before.fire_detected
        )
        assert after.produced_at == before.produced_at
        assert after.observation_time_s == 6.0  # not refreshed, not treated as no-detection


def test_yolo_provider_defaults_from_config():
    p = YoloProvider()
    assert p._conf == 0.25 and p._imgsz == 640 and p._iou == 0.45
    assert p._device == "cpu" and p._timeout_s >= 1
    assert p.SCRIPT.exists()
