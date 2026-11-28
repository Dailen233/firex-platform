"""Offline tests for true mask input, untouched holdout, and pinned terrain."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageDraw

from reconstruct_multiview_flame import BINDING, run
from sjk_hull_terrain import TerrainGrid, clip_terrain


def png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def write_capture(path, holdout_shift=0, wrong_mask_size=False):
    size = (128, 96)
    out = io.StringIO()
    columns = ("group_id", "camera_id", "role", "capture_id", "simulation_time_s",
               "image_file", "metadata_file", "mask_file")
    writer = csv.DictWriter(out, columns)
    writer.writeheader()
    positions = [(-22, 10, -12), (15, 8, -18), (0, 19, 25), (15, 15, 19)]
    with ZipFile(path, "w") as archive:
        for t in (1800, 3600):
            for index, position in enumerate(positions):
                group, cam = f"group-{t}", f"cam-{index+1}"
                stem = f"{group}/{cam}"
                role = "reconstruction" if index < 3 else "validation"
                forward = np.array([0, 9, 0])-position
                forward = forward / np.linalg.norm(forward)
                right = np.cross(forward, [0, 1, 0])
                right /= np.linalg.norm(right)
                pose = np.eye(4)
                pose[:3, :3] = np.column_stack((right, np.cross(forward,right), forward))
                pose[:3, 3] = position
                ids = {"group_id": group, "camera_id": cam, "role": role,
                       "capture_id": stem.replace("/", "-"), "simulation_time_s": t}
                row = dict(ids, image_file=stem+".png", metadata_file=stem+".json", mask_file=stem+"-mask.png")
                mask = Image.new("L", size if not (wrong_mask_size and index == 0) else (127, 96))
                shift = holdout_shift if index == 3 else 0
                ImageDraw.Draw(mask).ellipse((54+shift,38,74+shift,58), fill=255)
                meta = dict(BINDING, **ids, width=size[0], height=size[1], schema_version="1.0",
                            distortion_model="none", pose_convention="camera_to_world",
                            intrinsics={"fx":96,"fy":96,"cx":64,"cy":48},
                            pose={"camera_to_world":pose.tolist()})
                archive.writestr(row["image_file"], png(Image.new("RGB", size)))
                archive.writestr(row["metadata_file"], json.dumps(meta))
                archive.writestr(row["mask_file"], png(mask))
                writer.writerow(row)
        archive.writestr("manifest.csv", out.getvalue())


def write_single_group_capture(path, n_build=3, n_validate=1, sim_time=1800):
    """Write one synchronized group (n_build reconstruction + n_validate validation)."""
    size = (128, 96)
    out = io.StringIO()
    columns = ("group_id", "camera_id", "role", "capture_id", "simulation_time_s",
               "image_file", "metadata_file", "mask_file")
    writer = csv.DictWriter(out, columns)
    writer.writeheader()
    positions = [(-22, 10, -12), (15, 8, -18), (0, 19, 25), (15, 15, 19)]
    total = n_build + n_validate
    group = "group_01"
    with ZipFile(path, "w") as archive:
        for index in range(total):
            position = positions[index % len(positions)]
            cam = f"cam-{index+1}"
            stem = f"{group}/{cam}"
            role = "reconstruction" if index < n_build else "validation"
            forward = np.array([0, 9, 0])-position
            forward = forward / np.linalg.norm(forward)
            right = np.cross(forward, [0, 1, 0])
            right /= np.linalg.norm(right)
            pose = np.eye(4)
            pose[:3, :3] = np.column_stack((right, np.cross(forward, right), forward))
            pose[:3, 3] = position
            ids = {"group_id": group, "camera_id": cam, "role": role,
                   "capture_id": stem.replace("/", "-"), "simulation_time_s": sim_time}
            row = dict(ids, image_file=stem+".png", metadata_file=stem+".json", mask_file=stem+"-mask.png")
            mask = Image.new("L", size)
            ImageDraw.Draw(mask).ellipse((54, 38, 74, 58), fill=255)
            meta = dict(BINDING, **ids, width=size[0], height=size[1], schema_version="1.0",
                        distortion_model="none", pose_convention="camera_to_world",
                        intrinsics={"fx": 96, "fy": 96, "cx": 64, "cy": 48},
                        pose={"camera_to_world": pose.tolist()})
            archive.writestr(row["image_file"], png(Image.new("RGB", size)))
            archive.writestr(row["metadata_file"], json.dumps(meta))
            archive.writestr(row["mask_file"], png(mask))
            writer.writerow(row)
        archive.writestr("manifest.csv", out.getvalue())


class MultiviewInputTests(unittest.TestCase):
    def test_changing_holdout_mask_cannot_change_3d_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            a, b = root/"a.zip", root/"b.zip"
            write_capture(a)
            write_capture(b, holdout_shift=9)
            a_out, b_out = root/"a", root/"b"
            first = run(a,a_out,1.0,require_four_view_masks=True)["groups"]
            second = run(b,b_out,1.0,require_four_view_masks=True)["groups"]
            self.assertEqual(len(first), 2)
            for prior, changed in zip(first, second, strict=True):
                self.assertEqual((prior["source_camera_count"], prior["mask_source"]), (3,"binary_png"))
                self.assertGreater(prior["candidate_voxel_count"], 0)
                self.assertGreater(prior["holdout"]["iou"], changed["holdout"]["iou"])
                name = prior["group_id"]+"-voxels.ply"
                self.assertEqual((a_out/name).read_bytes(), (b_out/name).read_bytes())

    def test_rejects_wrong_mask_image_dimensions_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write_capture(root/"bad.zip", wrong_mask_size=True)
            with self.assertRaisesRegex(ValueError, "mask PNG dimensions"):
                run(root/"bad.zip",root/"out",1.0,require_four_view_masks=True)
            self.assertFalse((root/"out").exists())

    def test_actual_glb_ground_clip_keeps_unknown_coverage_separate(self):
        ground = TerrainGrid.from_glb()
        self.assertAlmostEqual(ground.height(np.array([0.]), np.array([0.]))[0], 34.895088, places=4)
        coords = [np.array([0.,5001.]), np.array([15.,40.]), np.array([0.])]
        keep = np.ones((2,2,1), dtype=bool)
        report = clip_terrain(ground, coords, keep)
        self.assertEqual(report["removed_voxels"], 1)
        self.assertEqual(report["outside_terrain_voxels"], 2)
        self.assertEqual(keep[...,0].tolist(), [[False,True],[True,True]])

    def test_single_group_requires_explicit_flag(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write_single_group_capture(root/"one.zip")
            with self.assertRaisesRegex(ValueError, "at least two synchronized capture groups"):
                run(root/"one.zip", root/"out", 1.0)

    def test_single_group_mode_reconstructs_one_group(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write_single_group_capture(root/"one.zip")
            report = run(root/"one.zip", root/"out", 1.0, single_group=True)
            self.assertEqual(len(report["groups"]), 1)
            group = report["groups"][0]
            self.assertEqual(group["simulation_time_s"], 1800)
            self.assertEqual(group["source_camera_count"], 3)
            self.assertEqual(group["mask_source"], "binary_png")
            self.assertGreater(group["candidate_voxel_count"], 0)

    def test_single_group_mode_rejects_multiple_groups(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write_capture(root/"two.zip")
            with self.assertRaisesRegex(ValueError, "exactly one synchronized capture group"):
                run(root/"two.zip", root/"out", 1.0, single_group=True)


if __name__ == "__main__":
    unittest.main()
