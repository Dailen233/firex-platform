// Pure terrain height sampling on the actual triangle mesh (barycentric in the
// XZ plane). Works for any indexed or non-indexed triangle mesh; the caller
// supplies the flat position array (x, y, z per vertex) and optional flat index
// array. No Vue / DOM / network / import.meta, so it is shared between the
// viewer and scripts/check-data.ts (and unit-testable in Node).

/**
 * Validate a triangle-mesh buffer pair and throw an explicit error on any
 * structural problem (bad length, out-of-range index, non-finite coordinate).
 * Returns the vertex count. Shared by sampling and ray-casting so that a
 * corrupt mesh fails loudly instead of yielding NaN results.
 */
export function validateTerrainMesh(positions: ArrayLike<number>, indices: ArrayLike<number> | null): number {
  const n = positions.length
  if (n < 9 || n % 3 !== 0) throw new Error(`非法地形网格：positions 长度 ${n}（须≥9 且为 3 的倍数）`)
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(positions[i]!)) throw new Error(`非法地形网格：positions[${i}] 非有限值`)
  }
  const vertexCount = n / 3
  if (indices) {
    if (indices.length < 3 || indices.length % 3 !== 0) throw new Error(`非法地形网格：indices 长度 ${indices.length}（须为 3 的倍数）`)
    for (let i = 0; i < indices.length; i++) {
      const idx = indices[i]!
      if (!Number.isInteger(idx) || idx < 0 || idx >= vertexCount) {
        throw new Error(`非法地形网格：indices[${i}] = ${idx} 越界（顶点数 ${vertexCount}）`)
      }
    }
  }
  return vertexCount
}

/**
 * Sample the height of the terrain triangle surface at (x, z).
 * Returns null when x/z are not finite, or when no triangle contains the point.
 * Throws on an ill-formed mesh (see validateTerrainMesh).
 */
export function sampleHeightOnTerrain(
  x: number,
  z: number,
  positions: ArrayLike<number>,
  indices: ArrayLike<number> | null,
): number | null {
  if (!Number.isFinite(x) || !Number.isFinite(z)) return null
  validateTerrainMesh(positions, indices)
  const triCount = indices ? indices.length / 3 : Math.floor(positions.length / 9)
  for (let t = 0; t < triCount; t++) {
    const i0 = indices ? indices[t * 3]! : t * 3
    const i1 = indices ? indices[t * 3 + 1]! : t * 3 + 1
    const i2 = indices ? indices[t * 3 + 2]! : t * 3 + 2
    const ax = positions[i0 * 3]!
    const az = positions[i0 * 3 + 2]!
    const ay = positions[i0 * 3 + 1]!
    const bx = positions[i1 * 3]!
    const bz = positions[i1 * 3 + 2]!
    const by = positions[i1 * 3 + 1]!
    const cx = positions[i2 * 3]!
    const cz = positions[i2 * 3 + 2]!
    const cy = positions[i2 * 3 + 1]!

    // XZ bounding-box reject.
    if (x < Math.min(ax, bx, cx) || x > Math.max(ax, bx, cx) || z < Math.min(az, bz, cz) || z > Math.max(az, bz, cz)) continue

    const denom = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
    if (Math.abs(denom) < 1e-12) continue // degenerate triangle
    const w1 = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / denom
    const w2 = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / denom
    const w3 = 1 - w1 - w2
    if (w1 < -1e-9 || w2 < -1e-9 || w3 < -1e-9) continue // outside this triangle
    return w1 * ay + w2 * by + w3 * cy
  }
  return null
}
