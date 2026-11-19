"""Sample the actual triangles of the byte-pinned SJK simulation terrain."""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

GLB_SHA256 = "722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91"
GLB_PATH = (Path(__file__).resolve().parents[2] / "frontend/public/models"
            / "sjk-hydropower-sim-v0.1/sjk_hydropower_sim_v0_1.glb")
TERRAIN_NODE = "team_fbx_terrain_129"


@dataclass
class TerrainGrid:
    x: np.ndarray
    z: np.ndarray
    y: np.ndarray
    main_diagonal: np.ndarray

    @classmethod
    def from_glb(cls, path: Path = GLB_PATH) -> TerrainGrid:
        # The pinned nodes have identity transforms; no world/geographic
        # placement is implied. Refuse a different GLB, even with the same name.
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != GLB_SHA256:
            raise ValueError("terrain clipping requires the original SJK GLB SHA-256")
        json_size, = struct.unpack_from("<I", data, 12)
        doc = json.loads(data[20:20 + json_size])
        chunk = memoryview(data)[28 + json_size:]
        terrain = next(n for n in doc["nodes"] if n.get("name") == TERRAIN_NODE)
        primitive = doc["meshes"][terrain["mesh"]]["primitives"][0]

        def packed(index: int, kind: str, n: int) -> np.ndarray:
            acc = doc["accessors"][index]
            view = doc["bufferViews"][acc["bufferView"]]
            off = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            return np.frombuffer(chunk, dtype=kind, count=acc["count"]*n, offset=off).reshape(-1,n)

        vertices = packed(primitive["attributes"]["POSITION"], "<f4", 3)
        triangles = packed(primitive["indices"], "<u4", 1).reshape(-1, 3)
        x, i = np.unique(vertices[:, 0], return_inverse=True)
        z, j = np.unique(vertices[:, 2], return_inverse=True)
        if len(vertices) != len(x)*len(z) or len(np.unique(i*len(z)+j)) != len(vertices):
            raise ValueError("terrain is not a complete XZ height grid")
        y = np.empty((len(x), len(z)), float)
        y[i, j] = vertices[:, 1]
        ix, jz = i[triangles], j[triangles]
        a, b = ix.min(axis=1), jz.min(axis=1)
        if np.any(ix.max(axis=1)-a != 1) or np.any(jz.max(axis=1)-b != 1):
            raise ValueError("terrain triangle crosses an XZ cell")
        # Corner bits: 00->1, 10->2, 01->4, 11->8. The two actual
        # triangle indices specify which diagonal to interpolate across.
        corners = (1 << ((ix-a[:,None])+2*(jz-b[:,None]))).sum(axis=1)
        cell = a*(len(z)-1)+b
        count = (len(x)-1)*(len(z)-1)
        if np.any(np.bincount(cell, minlength=count) != 2):
            raise ValueError("expected two terrain triangles per XZ cell")
        order = np.lexsort((corners, cell))
        pairs = corners[order].reshape(-1, 2)
        main = (pairs == [11, 13]).all(axis=1)
        if not (main | (pairs == [7, 14]).all(axis=1)).all():
            raise ValueError("unrecognized terrain cell triangles")
        return cls(x, z, y, main.reshape(len(x)-1, len(z)-1))

    def height(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        inside = (x >= self.x[0]) & (x <= self.x[-1]) & (z >= self.z[0]) & (z <= self.z[-1])
        i = np.clip(np.searchsorted(self.x, x, side="right")-1, 0, len(self.x)-2)
        j = np.clip(np.searchsorted(self.z, z, side="right")-1, 0, len(self.z)-2)
        u = (x-self.x[i])/(self.x[i+1]-self.x[i])
        v = (z-self.z[j])/(self.z[j+1]-self.z[j])
        a, b, c, d = self.y[i,j], self.y[i+1,j], self.y[i,j+1], self.y[i+1,j+1]
        h_main = np.where(u >= v, a*(1-u)+b*(u-v)+d*v, a*(1-v)+c*(v-u)+d*u)
        h_other = np.where(u+v <= 1, a*(1-u-v)+b*u+c*v, d*(u+v-1)+b*(1-v)+c*(1-u))
        return np.where(inside, np.where(self.main_diagonal[i,j], h_main, h_other), np.nan)


def clip_terrain(terrain: TerrainGrid, coords: list[np.ndarray], occupy: np.ndarray) -> dict:
    X, Y, Z = coords
    ix, iy, iz = np.nonzero(occupy)
    ground = terrain.height(X[ix], Z[iz])
    below = Y[iy] < ground
    occupy[ix[below], iy[below], iz[below]] = False
    return {"glb_sha256": GLB_SHA256, "method": "voxel_center_below_glb_triangle",
            "removed_voxels": int(below.sum()), "outside_terrain_voxels": int(np.isnan(ground).sum())}
