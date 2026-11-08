// CPU triangle-mesh adapter for terrain assets (Shuangjiangkou 129×129 terrain
// and future terrain GLBs). Operates on the flat xyz position array plus the
// optional flat triangle-index array, in the GLB's file-metre coordinates — the
// caller must NOT pre-scale or shift.
//
// No Vue / DOM / network / import.meta, so it is shared between the viewer and
// Node verification scripts (mirrors terrain-sampling.ts). Import uses an
// explicit `.ts` extension so Node's --experimental-strip-types can resolve it.

import { sampleHeightOnTerrain, validateTerrainMesh } from './terrain-sampling.ts'

export type Vec3 = readonly [number, number, number]

export interface TerrainRayHit {
  /** Hit point in file metres. */
  point: [number, number, number]
  /** Distance along the (normalised) ray, in metres. */
  distance: number
  /** Triangle index in the index buffer (or unindexed vertex stream). */
  triangle: number
  /** Barycentric vertex weights (w0, w1, w2); always sums to ~1. */
  barycentric: [number, number, number]
}

const EPS_DET = 1e-12
const EPS_BARY = 1e-9
const EPS_T = 1e-9

/**
 * Nearest-hit Möller–Trumbore ray/triangle intersection over the whole mesh.
 * The direction is normalised internally so `distance` is a true metre length.
 * Returns null on miss, on a non-finite origin/direction, or on a zero/non-finite
 * length direction; throws on an ill-formed mesh (see validateTerrainMesh).
 * Ray/triangle tests honour the actual index buffer, so a quad split along
 * either diagonal is respected (no assumed triangulation). Successful hits are
 * guaranteed finite (point, distance and barycentric weights).
 */
export function raycastTerrain(
  origin: Vec3,
  direction: Vec3,
  positions: ArrayLike<number>,
  indices: ArrayLike<number> | null,
): TerrainRayHit | null {
  if (!Number.isFinite(origin[0]) || !Number.isFinite(origin[1]) || !Number.isFinite(origin[2])) return null
  let dx = direction[0]; let dy = direction[1]; let dz = direction[2]
  if (!Number.isFinite(dx) || !Number.isFinite(dy) || !Number.isFinite(dz)) return null
  const len = Math.hypot(dx, dy, dz)
  if (!(len > 0) || !Number.isFinite(len)) return null
  validateTerrainMesh(positions, indices)
  dx /= len; dy /= len; dz /= len
  const ox = origin[0]; const oy = origin[1]; const oz = origin[2]
  const triCount = indices ? Math.floor(indices.length / 3) : Math.floor(positions.length / 9)
  let best: TerrainRayHit | null = null
  for (let t = 0; t < triCount; t++) {
    const i0 = indices ? indices[t * 3]! : t * 3
    const i1 = indices ? indices[t * 3 + 1]! : t * 3 + 1
    const i2 = indices ? indices[t * 3 + 2]! : t * 3 + 2
    const ax = positions[i0 * 3]!; const ay = positions[i0 * 3 + 1]!; const az = positions[i0 * 3 + 2]!
    const bx = positions[i1 * 3]!; const by = positions[i1 * 3 + 1]!; const bz = positions[i1 * 3 + 2]!
    const cx = positions[i2 * 3]!; const cy = positions[i2 * 3 + 1]!; const cz = positions[i2 * 3 + 2]!
    const e1x = bx - ax; const e1y = by - ay; const e1z = bz - az
    const e2x = cx - ax; const e2y = cy - ay; const e2z = cz - az
    const px = dy * e2z - dz * e2y
    const py = dz * e2x - dx * e2z
    const pz = dx * e2y - dy * e2x
    const det = e1x * px + e1y * py + e1z * pz
    if (Math.abs(det) < EPS_DET) continue
    const invDet = 1 / det
    const tx = ox - ax; const ty = oy - ay; const tz = oz - az
    const u = (tx * px + ty * py + tz * pz) * invDet
    if (u < -EPS_BARY || u > 1 + EPS_BARY) continue
    const qx = ty * e1z - tz * e1y
    const qy = tz * e1x - tx * e1z
    const qz = tx * e1y - ty * e1x
    const v = (dx * qx + dy * qy + dz * qz) * invDet
    if (v < -EPS_BARY || u + v > 1 + EPS_BARY) continue
    const dist = (e2x * qx + e2y * qy + e2z * qz) * invDet
    if (dist <= EPS_T) continue
    if (!best || dist < best.distance) {
      best = {
        point: [ox + dx * dist, oy + dy * dist, oz + dz * dist],
        distance: dist,
        triangle: t,
        barycentric: [1 - u - v, u, v],
      }
    }
  }
  return best
}

/**
 * Terrain triangle mesh in file-metre coordinates. Wraps the shared
 * `sampleHeightOnTerrain` (barycentric XZ height sampling) and adds CPU ray
 * intersection for camera-ray / click-to-pick workflows.
 *
 * IMPORTANT: this works purely on the handed-off GLB vertices/indices and does
 * NOT bake in a Unity transform. Until the teammate supplies the real
 * localToWorld (or 4+1 fit points), the terrain stays unregistered and no
 * identity transform is assumed.
 */
export class TerrainMesh {
  readonly positions: ArrayLike<number>
  readonly indices: ArrayLike<number> | null
  readonly triangleCount: number
  constructor(positions: ArrayLike<number>, indices: ArrayLike<number> | null) {
    validateTerrainMesh(positions, indices)
    this.positions = positions
    this.indices = indices
    this.triangleCount = indices ? Math.floor(indices.length / 3) : Math.floor(positions.length / 9)
  }
  sampleHeight(x: number, z: number): number | null {
    return sampleHeightOnTerrain(x, z, this.positions, this.indices)
  }
  raycast(origin: Vec3, direction: Vec3): TerrainRayHit | null {
    return raycastTerrain(origin, direction, this.positions, this.indices)
  }
}
