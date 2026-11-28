// Node 22+: node frontend/scripts/verify-voxel-shell.mjs [terrain-clip-dir]
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { buildVoxelShell } from '../src/lib/voxel-shell.ts'
import { parseMultiviewSummary, parseVoxelPly } from '../src/lib/multiview-replay.ts'

function bounds(xyz) {
  const min = [Infinity, Infinity, Infinity]
  const max = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < xyz.length; i++) {
    const axis = i % 3
    min[axis] = Math.min(min[axis], xyz[i])
    max[axis] = Math.max(max[axis], xyz[i])
  }
  return [min, max]
}

const centers = new Float32Array([2, -2, 10, 6, -2, 10])
const joined = buildVoxelShell(centers, 4)
assert.equal(joined.quadCount, 10)
assert.equal(buildVoxelShell(centers.subarray(0, 3), 4).quadCount, 6)
assert.equal(buildVoxelShell(new Float32Array([2, -2, 10, 10, -2, 10]), 4).quadCount, 12)
assert.deepEqual(bounds(joined.positions), [[0, -4, 8], [8, 0, 12]])
assert.deepEqual(Array.from(centers), [2, -2, 10, 6, -2, 10])
// Two adjacent cubes meet at x=4; no entire face should lie on that plane.
for (let i = 0; i < joined.positions.length; i += 18) {
  assert.ok([0, 3, 6, 9, 12, 15].some((dx) => joined.positions[i + dx] !== 4))
}
for (let i = 0; i < joined.positions.length; i += 9) {
  const a = [0, 1, 2].map((k) => joined.positions[i + 3 + k] - joined.positions[i + k])
  const b = [0, 1, 2].map((k) => joined.positions[i + 6 + k] - joined.positions[i + k])
  const cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
  assert.ok(cross.reduce((sum, value, axis) => sum + value * joined.normals[i + axis], 0) > 0)
}
for (const [points, size] of [
  [[], 4], [[0, 0, 0], 0], [[0, 0, 0, 1, 0, 0], 4],
  [[0, 0, 0, 0, 0, 0], 4], [[NaN, 0, 0], 4], [[1e30, 0, 0], 4],
]) {
  assert.equal(buildVoxelShell(new Float32Array(points), size), null)
}
console.log('Geometry, winding, immutable inputs and fallback: PASS')

const fixture = process.argv[2]
if (fixture) {
  const summary = parseMultiviewSummary(readFileSync(join(fixture, 'summary.json'), 'utf8'))
  // Expected exposed-face counts were independently measured on the original
  // 4 m terrain-clipped pair; check the same fixture beyond the toy cases.
  const expected = new Map([[1800, [33599, 18640]], [3600, [43005, 29668]]])
  assert.equal(summary.voxel_size_m, 4)
  assert.deepEqual(summary.groups.map((g) => g.simulation_time_s), [...expected.keys()])
  for (const group of summary.groups) {
    const [points, faces] = expected.get(group.simulation_time_s)
    const ply = readFileSync(join(fixture, `${group.group_id}-voxels.ply`))
    const frame = parseVoxelPly(ply.buffer.slice(ply.byteOffset, ply.byteOffset + ply.byteLength))
    assert.equal(frame.vertex_count, group.candidate_voxel_count)
    assert.equal(frame.vertex_count, points)
    const start = performance.now()
    const shell = buildVoxelShell(frame.xyz, summary.voxel_size_m)
    const elapsed = performance.now() - start
    assert.equal(shell.quadCount, faces)
    assert.equal(shell.positions.length / 9, faces * 2)
    const expectedBounds = bounds(frame.xyz).map((v, j) => v.map((x) => x + (j === 0 ? -2 : 2)))
    assert.deepEqual(bounds(shell.positions), expectedBounds)
    console.log(`${group.simulation_time_s} s: ${points} centers, ${faces * 2} triangles, ${elapsed.toFixed(1)} ms CPU`)
  }
}
