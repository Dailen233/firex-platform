"""Estimate a visible flame section for the pinned Shuangjiangkou simulation.

The image supplies a silhouette, and an anchor ray supplies its approximate
depth on the existing terrain. There is no estimate of depth behind the
silhouette or of a closed flame volume.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import struct
from collections import deque
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .capture_metadata import CaptureMetadata
from .models import Detection2D, FlameEstimate

PLANT_ID = "GEM_HYDRO_SHUANGJIANGKOU"
SCENE_BINDING = (
    "sjk_hydropower_sim_v0_1",
    "hydro-sim-v0.1-local",
    "SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1",
)
TERRAIN_NODE = "team_fbx_terrain_129"
GLB_SHA256 = "722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91"
GLB_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend/public/models/sjk-hydropower-sim-v0.1/sjk_hydropower_sim_v0_1.glb"
)

Vec3 = tuple[float, float, float]
TerrainTriangle = tuple[Vec3, Vec3, Vec3]  # vertex followed by its two edges


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _along(origin: Vec3, direction: Vec3, t: float) -> Vec3:
    return (origin[0] + t * direction[0], origin[1] + t * direction[1], origin[2] + t * direction[2])


@lru_cache(maxsize=1)
def _terrain() -> tuple[TerrainTriangle, ...]:
    # Restrict this small GLB reader to the byte-pinned asset. Its terrain node
    # and parent have identity transforms, and the two accessors are packed.
    data = GLB_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != GLB_SHA256:
        raise ValueError("Shuangjiangkou terrain hash does not match the capture frame")
    json_size, = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20:20 + json_size])
    binary = memoryview(data)[28 + json_size:]
    node = next(n for n in doc["nodes"] if n.get("name") == TERRAIN_NODE)
    primitive = doc["meshes"][node["mesh"]]["primitives"][0]

    def accessor(index: int, fmt: str, component_type: int, shape: str):
        a = doc["accessors"][index]
        view = doc["bufferViews"][a["bufferView"]]
        step = struct.calcsize(fmt)
        if (
            a["type"] != shape or a["componentType"] != component_type or "sparse" in a
            or view["buffer"] != 0 or view.get("byteStride", step) != step
        ):
            raise ValueError("unexpected Shuangjiangkou terrain accessor")
        start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        return struct.iter_unpack(fmt, binary[start:start + a["count"] * step])

    vertices = list(accessor(primitive["attributes"]["POSITION"], "<fff", 5126, "VEC3"))
    indices = iter(i for i, in accessor(primitive["indices"], "<I", 5125, "SCALAR"))
    return tuple(
        (vertices[a], _sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        for a, b, c in zip(indices, indices, indices)
    )


def _terrain_hit(origin: Vec3, direction: Vec3) -> Vec3 | None:
    """Nearest positive two-sided ray hit, in the versioned local asset axes."""
    nearest = math.inf
    for vertex, edge1, edge2 in _terrain():
        p = _cross(direction, edge2)
        det = _dot(edge1, p)
        if abs(det) < 1e-9:
            continue
        delta = _sub(origin, vertex)
        u = _dot(delta, p) / det
        if u < -1e-9 or u > 1 + 1e-9:
            continue
        q = _cross(delta, edge1)
        v = _dot(direction, q) / det
        if v < -1e-9 or u + v > 1 + 1e-9:
            continue
        t = _dot(edge2, q) / det
        if 1e-6 < t < nearest:
            nearest = t
    return _along(origin, direction, nearest) if math.isfinite(nearest) else None


def _largest_component(image: Image.Image) -> list[tuple[int, int]]:
    width, height = image.size
    rgb = image.tobytes()
    # Restricted to the same visual cues used in the offline Unity diagnostics.
    # This is a heuristic silhouette, not a trained segmentation model.
    pixels = bytearray(
        r >= 165 and g >= 55 and r - g >= 15 and g - b >= 38 and r - b >= 110
        for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3])
    )
    best: list[tuple[int, int]] = []
    for i in range(len(pixels)):
        if not pixels[i]:
            continue
        pending = deque([i])
        pixels[i] = 0
        component = []
        while pending:
            y, x = divmod(pending.popleft(), width)
            component.append((x, y))
            for ry in range(max(0, y - 1), min(height, y + 2)):
                for cx in range(max(0, x - 1), min(width, x + 2)):
                    j = ry * width + cx
                    if pixels[j]:
                        pixels[j] = 0
                        pending.append(j)
        if len(component) > len(best):
            best = component
    return best


def estimate_flame(meta: CaptureMetadata, original: bytes, detection: Detection2D) -> FlameEstimate | None:
    """Project one connected flame-colored region onto a vertical section.

    No color anchor, no terrain hit or unusable perspective produces no
    estimate. The caller still publishes the unmodified 2D result.
    """
    if (meta.scene_id, meta.asset_version, meta.coordinate_frame_id) != SCENE_BINDING:
        return None

    x1, y1, x2, y2 = detection.bbox
    left, top = max(0, math.floor(x1)), max(0, math.floor(y1))
    right, bottom = min(meta.width, math.ceil(x2)), min(meta.height, math.ceil(y2))
    # A flame cut off by the bottom of the image has no usable base.
    if right <= left or bottom <= top or bottom == meta.height:
        return None
    with Image.open(io.BytesIO(original)) as image:
        if image.size != (meta.width, meta.height):
            return None
        crop = image.crop((left, top, right, bottom)).convert("RGB")
    crop.thumbnail((320, 320), Image.Resampling.BILINEAR)
    points = _largest_component(crop)
    if len(points) < 100:
        return None

    m = meta.pose.camera_to_world
    origin = (m[0][3], m[1][3], m[2][3])
    k = meta.intrinsics
    sx, sy = (right - left) / crop.width, (bottom - top) / crop.height

    def direction(x: float, y: float) -> Vec3:
        cx = (left + (x + 0.5) * sx - k.cx) / k.fx
        cy = (top + (y + 0.5) * sy - k.cy) / k.fy
        return (
            m[0][0] * cx + m[0][1] * cy + m[0][2],
            m[1][0] * cx + m[1][1] * cy + m[1][2],
            m[2][0] * cx + m[2][1] * cy + m[2][2],
        )

    rows = sorted(y for _, y in points)
    bottom_row = rows[int(0.95 * (len(rows) - 1))]
    lower_x = sorted(x for x, y in points if y >= bottom_row - 4 / sy)
    anchor = _terrain_hit(origin, direction(lower_x[len(lower_x) // 2], bottom_row))
    if anchor is None:
        return None

    nx, nz = origin[0] - anchor[0], origin[2] - anchor[2]
    length = math.hypot(nx, nz)
    if length < 1e-3:
        return None
    normal = (nx / length, 0.0, nz / length)
    plane_dist = _dot(_sub(anchor, origin), normal)

    def project(x: float, y: float) -> Vec3 | None:
        ray = direction(x, y)
        den = _dot(ray, normal)
        if abs(den) < 1e-6:
            return None
        t = plane_dist / den
        if not 0.0 < t <= 20_000:
            return None
        return _along(origin, ray, t)

    # Approximate the outline by pairs across up to 32 rows. This avoids
    # passing the entire color mask over the wire, and keeps a thin surface.
    # Trim the few rows below the anchor percentile, which are unreliable as
    # ground evidence. Let the existing scene occlude the resulting section.
    bounds: dict[int, tuple[int, int]] = {}
    for x, y in points:
        if y <= bottom_row:
            lo, hi = bounds.get(y, (x, x))
            bounds[y] = (min(lo, x), max(hi, x))
    usable_rows = sorted(y for y, (lo, hi) in bounds.items() if hi - lo >= 1)
    if len(usable_rows) < 2:
        return None
    n = min(32, len(usable_rows))
    # Keep the source flame colors and alpha only inside the chosen region;
    # this texture is not the source screenshot or an invented particle effect.
    tx0 = min(bounds[y][0] for y in usable_rows)
    tx1 = max(bounds[y][1] for y in usable_rows) + 1
    ty0, ty1 = usable_rows[0], usable_rows[-1] + 1
    texture = crop.crop((tx0, ty0, tx1, ty1)).convert("RGBA")
    mask = Image.new("L", texture.size)
    alpha = mask.load()
    for x, y in points:
        if tx0 <= x < tx1 and ty0 <= y < ty1:
            alpha[x - tx0, y - ty0] = 255
    texture.putalpha(mask)
    texture.thumbnail((128, 128), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    texture.save(encoded, "PNG")

    vertices: list[Vec3] = []
    uv: list[tuple[float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for i in range(n):
        y = usable_rows[i * (len(usable_rows) - 1) // (n - 1)]
        lo, hi = bounds[y]
        a, b = project(lo - 0.5, y), project(hi + 0.5, y)
        if a is None or b is None:
            return None
        vertices.extend((a, b))
        v = 1 - (y + 0.5 - ty0) / (ty1 - ty0)
        uv.extend((((lo - tx0) / (tx1 - tx0), v), ((hi + 1 - tx0) / (tx1 - tx0), v)))
        j = 2 * i
        if i:
            triangles.extend(((j - 2, j - 1, j), (j - 1, j + 1, j)))
    return FlameEstimate(
        method="single_view_flame_silhouette", capture_id=meta.capture_id, glb_sha256=GLB_SHA256, anchor_xyz_m=anchor,
        camera_xyz_m=origin, vertices=vertices, triangles=triangles, uv=uv,
        texture_png_base64=base64.b64encode(encoded.getvalue()).decode("ascii"),
    )
