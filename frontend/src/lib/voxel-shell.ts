export type VoxelLayerMode = 'points' | 'shell'

export type VoxelShell = {
  positions: Float32Array
  normals: Float32Array
  quadCount: number
}

// Bound temporary allocations and triangle buffers. Larger inputs can still
// use the existing point layer without any data loss.
const MAX_CELLS = 150_000
const MAX_QUADS = 160_000
const FACES = [[0, -1], [0, 1], [1, -1], [1, 1], [2, -1], [2, 1]] as const
const CORNERS = [[-1, -1], [1, -1], [1, 1], [-1, 1]] as const
const OUTWARD = [0, 1, 2, 0, 2, 3] as const
const REVERSED = [0, 2, 1, 0, 3, 2] as const
const cellKey = (x: number, y: number, z: number) => `${x},${y},${z}`

/**
 * Draw the union of the existing occupied cubes: omit shared faces, keep
 * holes and detached cells, and leave all input positions and counts intact.
 * Origin is relative to the first center; the lattice need not start at zero.
 */
export function buildVoxelShell(xyz: Float32Array, step: number): VoxelShell | null {
  if (!Number.isFinite(step) || step <= 0 ||
      !xyz.length || xyz.length % 3 || xyz.length / 3 > MAX_CELLS) return null

  const base = [xyz[0], xyz[1], xyz[2]]
  const lattice = new Int32Array(xyz.length)
  const filled = new Set<string>()
  const half = step / 2
  for (let i = 0; i < xyz.length; i += 3) {
    for (let axis = 0; axis < 3; axis++) {
      const value = xyz[i + axis]
      const delta = value - base[axis]
      const index = Math.round(delta / step)
      // Allow Float32 rounding while rejecting non-lattice points. Cap the
      // tolerance so a non-grid cloud never gets rounded into occupied cells.
      const tolerance = Math.min(step / 100, Math.max(step * 1e-5,
        Math.max(Math.abs(value), Math.abs(base[axis])) * 2 ** -22))
      if (!Number.isSafeInteger(index) || Math.abs(index) >= 2 ** 31 - 1 ||
          Math.abs(delta - index * step) > tolerance) return null
      const center = base[axis] + index * step
      const low = Math.fround(center - half), high = Math.fround(center + half)
      if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) return null
      lattice[i + axis] = index
    }
    const key = cellKey(lattice[i], lattice[i + 1], lattice[i + 2])
    if (filled.has(key)) return null
    filled.add(key)
  }

  const visible: number[] = []
  for (let i = 0; i < lattice.length; i += 3) {
    const x = lattice[i], y = lattice[i + 1], z = lattice[i + 2]
    FACES.forEach(([axis, side], face) => {
      const key = cellKey(x + (axis === 0 ? side : 0),
        y + (axis === 1 ? side : 0), z + (axis === 2 ? side : 0))
      if (!filled.has(key)) visible.push(i / 3 * FACES.length + face)
    })
    if (visible.length > MAX_QUADS) return null
  }

  const positions = new Float32Array(visible.length * 6 * 3)
  const normals = new Float32Array(positions.length)
  const center = [0, 0, 0]
  let write = 0
  for (const faceId of visible) {
    const i = Math.floor(faceId / FACES.length) * 3
    const [axis, side] = FACES[faceId % FACES.length]
    const u = (axis + 1) % 3, v = (axis + 2) % 3
    for (let k = 0; k < 3; k++) center[k] = base[k] + lattice[i + k] * step
    for (const corner of side > 0 ? OUTWARD : REVERSED) {
      const [du, dv] = CORNERS[corner]
      positions[write + axis] = center[axis] + side * half
      positions[write + u] = center[u] + du * half
      positions[write + v] = center[v] + dv * half
      normals[write + axis] = side
      write += 3
    }
  }
  return { positions, normals, quadCount: visible.length }
}
