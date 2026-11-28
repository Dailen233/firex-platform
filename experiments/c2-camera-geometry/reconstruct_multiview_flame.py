"""Reconstruct a simulation visual hull from two or three source views.

One separate camera measures silhouette overlap. Unity may provide binary
masks; older RGB-only captures use color proxies. The voxel occupancy is an
outer envelope estimate, not geometric ground truth or a live assessment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.optimize import linprog

from sjk_hull_terrain import GLB_SHA256, TerrainGrid, clip_terrain

REPO = Path(__file__).resolve().parents[2]
BINDING = {
    "scene_id": "sjk_hydropower_sim_v0_1",
    "asset_version": "hydro-sim-v0.1-local",
    "coordinate_frame_id": "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
}
MAX_SAMPLES = 18_000_000
AXES = np.eye(3)


def need(condition, detail: str) -> None:
    if not condition:
        raise ValueError(detail)


def complete_mask(mask: np.ndarray) -> np.ndarray:
    need(mask.any(), "empty flame mask")
    need(not (mask[[0, -1], :].any() or mask[:, [0, -1]].any()), "flame mask touches an image edge")
    return mask


def mask_for_image(image: Image.Image) -> np.ndarray:
    """Use the same bright-orange test across all simulation views."""
    r, g, b = np.moveaxis(np.asarray(image.convert("RGB"), dtype=np.int16), -1, 0)
    raw = (r >= 165) & (g >= 55) & (r-g >= 15) & (g-b >= 38) & (r-b >= 110)
    neighborhood = np.ones((3, 3), bool)
    # Close small RGB gaps without counting the dilation as observed pixels.
    labels, n = ndi.label(ndi.binary_dilation(raw, iterations=10), structure=neighborhood)
    counts = np.bincount(labels[raw], minlength=n+1)
    counts[0] = 0
    need(counts.max() >= 100, "could not isolate a flame-colored region")
    seed = raw & (labels == counts.argmax())
    return complete_mask(seed | ndi.binary_closing(seed, structure=neighborhood, iterations=4))


def read_binary_mask(raw: bytes, size: tuple[int, int]) -> np.ndarray:
    with Image.open(io.BytesIO(raw)) as image:
        need(image.format == "PNG" and image.size == size, "mask PNG dimensions must match the raw capture")
        need(image.mode in ("1", "L", "RGB", "RGBA"), "mask must be grayscale or black/white RGB(A)")
        if image.mode in ("1", "L"):
            gray = np.asarray(image.convert("L"))
        else:
            pixels = np.asarray(image)
            gray = pixels[..., 0]
            need((pixels[..., :3] == gray[..., None]).all(), "mask RGB must be black and white")
            need(image.mode != "RGBA" or (pixels[..., 3] == 255).all(), "mask PNG alpha must be opaque")
        need(((gray == 0) | (gray == 255)).all(), "mask must contain only 0 and 255")
        return complete_mask(gray == 255)


@dataclass
class View:
    camera: str
    capture: str
    role: str
    time: float
    rotation: np.ndarray
    origin: np.ndarray
    focal: np.ndarray
    center: np.ndarray
    mask: np.ndarray
    image_sha256: str
    metadata_sha256: str
    mask_sha256: str | None
    declared_glb_sha256: str | None

    def project(self, xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        camera = (xyz - self.origin) @ self.rotation
        z = camera[..., 2]
        denom = np.where(z > 0.01, z, 1)
        return self.center + self.focal * camera[..., :2] / denom[..., None], z

    def frustum_halfspaces(self) -> tuple[np.ndarray, np.ndarray]:
        # Bounds enclose all accepted pixels; full mask membership is checked
        # after making this finite search box. A @ world <= b.
        y, x = np.where(self.mask)
        fx, fy = self.focal
        cx, cy = self.center
        camera_planes = np.array([
            [fx, 0, cx-(x.max()+1)], [-fx, 0, x.min()-cx],
            [0, fy, cy-(y.max()+1)], [0, -fy, y.min()-cy], [0, 0, -1],
        ])
        A = camera_planes @ self.rotation.T
        b = A @ self.origin
        b[-1] -= 0.01
        return A, b


def read_groups(
    archive: ZipFile, require_four_view_masks: bool = False, single_group: bool = False
) -> dict[str, list[View]]:
    entries = archive.namelist()
    need(len(set(entries)) == len(entries), "duplicate ZIP path")
    manifests = [path for path in entries if PurePosixPath(path).name == "manifest.csv"]
    need(len(manifests) == 1, "expected exactly one manifest.csv")
    manifest = PurePosixPath(manifests[0])
    groups = defaultdict(list)
    captures = set()
    used = set()
    for row in csv.DictReader(io.StringIO(archive.read(str(manifest)).decode("utf-8-sig"))):
        group = row["group_id"]
        need(re.fullmatch(r"[A-Za-z0-9_-]+", group), "invalid group_id")
        def read_file(key: str, suffix: str) -> bytes:
            name = PurePosixPath(row[key])
            need(not name.is_absolute() and ".." not in name.parts and name.suffix == suffix, f"{group}: invalid {key}")
            need(name not in used, f"{group}: repeated {key}")
            used.add(name)
            return archive.read(str(manifest.parent / name))

        png = read_file("image_file", ".png")
        raw_meta = read_file("metadata_file", ".json")
        mask_png = read_file("mask_file", ".png") if row.get("mask_file") else None
        meta = json.loads(raw_meta.decode("utf-8-sig"))
        for key, expected in BINDING.items():
            need(meta.get(key) == expected, f"{group}: capture {key} mismatch")
        glb_sha = meta.get("glb_sha256")
        need(glb_sha in (None, GLB_SHA256), f"{group}: capture glb_sha256 mismatch")
        for key in ("group_id", "camera_id", "role", "capture_id"):
            need(meta.get(key) == row[key] and row[key], f"{group}: manifest {key} mismatch")
        need(meta["capture_id"] not in captures, f"{group}: duplicate capture_id")
        captures.add(meta["capture_id"])
        t = float(row["simulation_time_s"])
        need(np.isfinite(t) and t >= 0 and t == meta["simulation_time_s"], f"{group}: invalid time binding")
        need(meta["schema_version"] == "1.0" and meta["distortion_model"] == "none" and
             meta["pose_convention"] == "camera_to_world", f"{group}: unknown camera convention")
        m = np.asarray(meta["pose"]["camera_to_world"], dtype=float)
        need(m.shape in ((16,), (4, 4)), f"{group}: invalid camera matrix shape")
        m = m.reshape(4, 4)
        R = m[:3, :3]
        need(np.isfinite(m).all() and np.allclose(m[3], [0,0,0,1]) and
             np.allclose(R.T @ R, AXES, atol=1e-5) and abs(np.linalg.det(R)-1) < 1e-5,
             f"{group}: invalid local camera rotation")
        k = meta["intrinsics"]
        f = np.array([k["fx"], k["fy"]], float)
        c = np.array([k["cx"], k["cy"]], float)
        with Image.open(io.BytesIO(png)) as image:
            need(image.format == "PNG" and image.size == (meta["width"], meta["height"]),
                 f"{group}: image format or dimensions mismatch")
            need(np.isfinite(f).all() and (f > 0).all() and (c >= 0).all() and (c < image.size).all(),
                 f"{group}: invalid image intrinsics")
            try:
                mask = read_binary_mask(mask_png, image.size) if mask_png is not None else mask_for_image(image)
            except ValueError as err:
                raise ValueError(f"{group}/{row['camera_id']}: {err}") from err
        groups[group].append(View(row["camera_id"], row["capture_id"], row["role"],
                                  t, R, m[:3, 3], f, c, mask, hashlib.sha256(png).hexdigest(),
                                  hashlib.sha256(raw_meta).hexdigest(),
                                  hashlib.sha256(mask_png).hexdigest() if mask_png is not None else None,
                                  glb_sha))
    if single_group:
        need(len(groups) == 1, "single-group mode requires exactly one synchronized capture group")
    else:
        need(len(groups) >= 2, "at least two synchronized capture groups are required")
    times = set()
    for group, views in groups.items():
        roles = sorted(v.role for v in views)
        need(len(views) in (3, 4) and roles == ["reconstruction"]*(len(views)-1)+["validation"]
             and len({v.camera for v in views}) == len(views), f"{group}: expected 2+1 or 3+1 distinct cameras")
        mask_count = sum(v.mask_sha256 is not None for v in views)
        need(mask_count in (0,len(views)), f"{group}: cannot mix exported masks and RGB proxies")
        if require_four_view_masks:
            need(len(views) == mask_count == 4, f"{group}: expected 3+1 views with four binary masks")
        need(len({v.time for v in views}) == 1 and views[0].time not in times,
             f"{group}: non-synchronous group or duplicate group time")
        need(all(np.linalg.norm(v.origin - other.origin) > 1 for i, v in enumerate(views)
                 for other in views[i+1:]), f"{group}: camera positions are not distinct")
        times.add(views[0].time)
    return dict(groups)


def eligible(view: View, xyz: np.ndarray) -> np.ndarray:
    uv, z = view.project(xyz)
    x, y = np.floor(uv).astype(int).T
    h, w = view.mask.shape
    keep = (z > 0.01) & (x >= 0) & (x < w) & (y >= 0) & (y < h)
    keep[keep] = view.mask[y[keep], x[keep]]
    return keep


def build_hull(source: list[View], step: float) -> tuple[list[np.ndarray], np.ndarray, float]:
    # Only source cameras inform either the search region or the occupancy.
    rays = [np.average(np.stack(np.nonzero(v.mask)[::-1], axis=1)+0.5, axis=0) for v in source]
    dirs = [v.rotation @ np.r_[(uv-v.center)/v.focal, 1.] for uv, v in zip(rays, source)]
    unit = [d / np.linalg.norm(d) for d in dirs]
    angle = max(np.degrees(np.arccos(np.clip(abs(a @ b), 0, 1))) for a, b in combinations(unit, 2))
    need(angle >= 5, "insufficient ray intersection angle")
    parts = [v.frustum_halfspaces() for v in source]
    A = np.concatenate([p[0] for p in parts])
    b = np.concatenate([p[1] for p in parts])
    limits = []
    for axis in AXES:
        extremes = [linprog(sign * axis, A_ub=A, b_ub=b, bounds=(None, None), method="highs")
                    for sign in (1, -1)]
        need(all(e.success for e in extremes), "no bounded overlap of the source image frustums")
        lo, hi = (e.x @ axis for e in extremes)
        limits.append((int(np.floor(lo/step))-1, int(np.ceil(hi/step))+2))
    dims = tuple(hi-lo for lo, hi in limits)
    need(np.prod(dims, dtype=float) <= MAX_SAMPLES, f"search grid {dims} too large; increase --voxel-m")
    coords = [np.arange(lo, hi) * step for lo, hi in limits]
    occupy = np.zeros(dims, dtype=bool)
    slab = max(1, 280_000 // (dims[1]*dims[2]))
    for start in range(0, dims[0], slab):
        block_x = coords[0][start:start+slab]
        xyz = np.stack(np.meshgrid(block_x, *coords[1:], indexing="ij"), axis=-1).reshape(-1, 3)
        keep = eligible(source[0], xyz)
        for view in source[1:]:
            keep[keep] = eligible(view, xyz[keep])
        occupy[start:start+slab] = keep.reshape(len(block_x), *dims[1:])
    need(occupy.any(), "source masks have no occupied voxel at the chosen resolution")
    return coords, occupy, float(angle)


def world_points(coords: list[np.ndarray], occupied: np.ndarray) -> np.ndarray:
    return np.column_stack([axis[ids] for axis, ids in zip(coords, np.nonzero(occupied))])


def silhouette(view: View, coords: list[np.ndarray], occupy: np.ndarray, step: float) -> np.ndarray:
    """Project every exposed square face of the voxel union into the held-out image."""
    h, w = view.mask.shape
    rendered = Image.new("1", (w, h))
    pen = ImageDraw.Draw(rendered)
    padded = np.pad(occupy, 1)
    for i, axis in enumerate(AXES):
        a, b = AXES[(i+1) % 3], AXES[(i+2) % 3]
        square = np.stack([-a-b, a-b, a+b, -a+b])
        for sign in (-1, 1):
            near = [slice(1, -1)] * 3
            near[i] = slice(0, -2) if sign < 0 else slice(2, None)
            points = world_points(coords, occupy & ~padded[tuple(near)])
            corners = points[:, None, :] + (sign*axis+square) * (step/2)
            uv, depth = view.project(corners)
            for xy in uv[(depth > 0.01).all(axis=1)]:
                pen.polygon(list(map(tuple, xy-0.5)), fill=1)
    return np.asarray(rendered, dtype=bool)


def write_ply(path: Path, points: np.ndarray) -> None:
    with path.open("wb") as f:
        f.write(("ply\nformat binary_little_endian 1.0\n"
                 "comment Fire-X simulated flame envelope; local metres; voxel centers only\n"
                 f"element vertex {len(points)}\n"
                 "property float x\nproperty float y\nproperty float z\nend_header\n").encode("ascii"))
        f.write(points.astype("<f4").tobytes())


def run(zip_path: Path, out: Path, step: float, *, terrain_clip: bool = False,
        require_four_view_masks: bool = False, single_group: bool = False) -> dict:
    with ZipFile(zip_path) as archive:
        groups = read_groups(archive, require_four_view_masks, single_group)
    terrain = TerrainGrid.from_glb() if terrain_clip else None
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for group, views in sorted(groups.items(), key=lambda pair: pair[1][0].time):
        source = [v for v in views if v.role == "reconstruction"]
        target = next(v for v in views if v.role == "validation")
        coords, occupy, angle = build_hull(source, step)
        clipped = clip_terrain(terrain, coords, occupy) if terrain is not None else None
        need(occupy.any(), f"{group}: all candidate voxel centers are below the GLB terrain")
        points = world_points(coords, occupy)
        prediction = silhouette(target, coords, occupy, step)
        observed = target.mask
        intersection = int((prediction & observed).sum())
        union = int((prediction | observed).sum())
        pred = int(prediction.sum())
        obs = int(observed.sum())
        overlay = np.zeros((*observed.shape, 3), dtype=np.uint8)
        overlay[observed & ~prediction] = (255, 143, 66)     # observed only
        overlay[prediction & ~observed] = (78, 165, 249)     # prediction only
        overlay[observed & prediction] = (101, 226, 145)     # overlap
        Image.fromarray(overlay).save(out / f"{group}-holdout-masks.png")
        write_ply(out / f"{group}-voxels.ply", points)
        summaries.append({
            "group_id": group, "simulation_time_s": target.time,
            "views": [{"camera_id": v.camera, "capture_id": v.capture, "role": v.role,
                       "mask_pixels": int(v.mask.sum()), "png_sha256": v.image_sha256,
                       "metadata_sha256": v.metadata_sha256, "mask_png_sha256": v.mask_sha256,
                       "declared_glb_sha256": v.declared_glb_sha256} for v in views],
            "source_camera_count": len(source),
            "mask_source": "binary_png" if target.mask_sha256 is not None else "rgb_proxy",
            "build_camera_ray_angle_deg": round(angle, 3),
            "terrain_clip": clipped,
            "candidate_voxel_count": len(points),
            "candidate_bounds_xyz_m": [(points.min(axis=0)-step/2).tolist(), (points.max(axis=0)+step/2).tolist()],
            "holdout": {"camera": target.camera, "intersection_pixels": intersection,
                        "predicted_pixels": pred, "observed_pixels": obs,
                        "iou": intersection/union, "precision": intersection/pred if pred else 0.0,
                        "recall": intersection/obs},
        })
    report = {
        **BINDING, "input_zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "voxel_size_m": step, "status": "experimental_visual_hull",
        "scope": "local frame declared by capture; silhouette comparison only; no surveyed geometry or ground-truth volume",
        "groups": summaries,
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Unity capture ZIP containing manifest.csv")
    parser.add_argument("--out", type=Path, default=REPO/"runtime-data/e3-multiview-flame")
    parser.add_argument("--voxel-m", type=float, default=4.0)
    parser.add_argument("--terrain-clip", action="store_true", help="drop voxel centers below the pinned GLB terrain")
    parser.add_argument("--require-four-view-masks", action="store_true",
                        help="require 3 build views and 1 held-out view, each with a binary mask_file")
    parser.add_argument("--single-group", action="store_true",
                        help="require exactly one synchronized capture group (one ZIP = one time point)")
    args = parser.parse_args()
    if not np.isfinite(args.voxel_m) or args.voxel_m < .1:
        parser.error("--voxel-m must be finite and at least 0.1 m")
    try:
        result = run(args.archive, args.out, args.voxel_m, terrain_clip=args.terrain_clip,
                     require_four_view_masks=args.require_four_view_masks,
                     single_group=args.single_group)
    except (KeyError, ValueError, OSError, BadZipFile) as err:
        parser.exit(2, f"capture rejected: {err}\n")
    for group in result["groups"]:
        print(f"{group['group_id']} t={group['simulation_time_s']:g}s | "
              f"{group['candidate_voxel_count']} voxels | holdout IoU={group['holdout']['iou']:.3f}")
    print(f"summary: {args.out / 'summary.json'}")
