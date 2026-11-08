// E2.0 地形几何适配验证（CPU 三角网采样 + 射线求交）。
// 直接读取真实地形 GLB 的顶点与索引，核对 129×129、间距 78.125m、三角拓扑与
// 对角线方向，并对射线命中 / 边界 / 未命中 / 非共面四边形（区分两种对角线）做
// 几何验证。射线结果与现有 sampleHeightOnTerrain 交叉核对，记录实际数值与误差。
// 结果写入 evidence/sjk-terrain-geometry/result.json。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
import { raycastTerrain, TerrainMesh, type Vec3 } from '../src/lib/terrain-mesh.ts'
import { sampleHeightOnTerrain, validateTerrainMesh } from '../src/lib/terrain-sampling.ts'

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = join(frontendDir, '..')
const outDir = join(repoRoot, 'evidence', 'sjk-terrain-geometry')

// ---- minimal self-contained GLB reader (no three.js / DOM in Node) ----
interface GlbJson {
  buffers: { byteLength: number }[]
  bufferViews: { buffer: number; byteOffset?: number; byteLength: number; byteStride?: number }[]
  accessors: { bufferView?: number; byteOffset?: number; componentType: number; count: number; type: string }[]
  meshes: { primitives: { attributes: Record<string, number>; indices: number }[] }[]
}
function parseTerrainGlb(buf: Buffer): { positions: Float32Array; indices: Uint16Array | Uint32Array } {
  assert.equal(buf.readUInt32LE(0), 0x46546c67, '不是 GLB')
  assert.equal(buf.readUInt32LE(4), 2, 'GLB 版本 != 2')
  assert.equal(buf.readUInt32LE(8), buf.length, 'GLB 长度不匹配')
  let json: GlbJson | null = null
  let bin: Buffer | null = null
  let off = 12
  while (off < buf.length) {
    const len = buf.readUInt32LE(off)
    const type = buf.readUInt32LE(off + 4)
    const data = buf.subarray(off + 8, off + 8 + len)
    if (type === 0x4e4f534a) json = JSON.parse(data.toString('utf8'))
    else if (type === 0x004e4942) bin = data
    off += 8 + len
  }
  assert(json && bin, 'GLB 缺 JSON 或 BIN chunk')
  const prim = json.meshes[0]!.primitives[0]!
  const posAcc = json.accessors[prim.attributes.POSITION]!
  const idxAcc = json.accessors[prim.indices]!
  assert.equal(posAcc.componentType, 5126, 'POSITION 应为 Float32')
  assert.equal(posAcc.type, 'VEC3', 'POSITION 应为 VEC3')
  const posView = json.bufferViews[posAcc.bufferView!]!
  const posBase = (posView.byteOffset ?? 0) + (posAcc.byteOffset ?? 0)
  const posStride = posView.byteStride ?? 12
  const positions = new Float32Array(posAcc.count * 3)
  for (let i = 0; i < posAcc.count; i++) {
    positions[i * 3] = bin.readFloatLE(posBase + i * posStride)
    positions[i * 3 + 1] = bin.readFloatLE(posBase + i * posStride + 4)
    positions[i * 3 + 2] = bin.readFloatLE(posBase + i * posStride + 8)
  }
  const idxView = json.bufferViews[idxAcc.bufferView!]!
  const idxBase = (idxView.byteOffset ?? 0) + (idxAcc.byteOffset ?? 0)
  const idxStride = idxView.byteStride ?? (idxAcc.componentType === 5123 ? 2 : 4)
  let indices: Uint16Array | Uint32Array
  if (idxAcc.componentType === 5123) {
    indices = new Uint16Array(idxAcc.count)
    for (let i = 0; i < idxAcc.count; i++) indices[i] = bin.readUInt16LE(idxBase + i * idxStride)
  } else if (idxAcc.componentType === 5125) {
    indices = new Uint32Array(idxAcc.count)
    for (let i = 0; i < idxAcc.count; i++) indices[i] = bin.readUInt32LE(idxBase + i * idxStride)
  } else throw new Error(`不支持的索引 componentType ${idxAcc.componentType}`)
  return { positions, indices }
}

const glb = readFileSync(join(frontendDir, 'public/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb'))
const { positions, indices } = parseTerrainGlb(glb)
const mesh = new TerrainMesh(positions, indices)
const n = positions.length / 3
const DOWN: Vec3 = [0, -1, 0]

const results: { id: string; ok: boolean; detail: string }[] = []
function check(id: string, run: () => string): void {
  try {
    const detail = run()
    results.push({ id, ok: true, detail })
    console.log(`PASS  ${id} — ${detail}`)
  } catch (e) {
    results.push({ id, ok: false, detail: e instanceof Error ? e.message : String(e) })
    console.log(`FAIL  ${id} — ${e instanceof Error ? e.message : String(e)}`)
  }
}

// 1) 规模
check('GRID-01-vertex-triangle-count', () => {
  assert.equal(n, 16641)
  assert.equal(indices.length, 98304, '索引值数量应为 32768 三角形 × 3')
  assert.equal(mesh.triangleCount, 32768)
  return `顶点 ${n}，索引值 ${indices.length}（= ${mesh.triangleCount} 三角形 × 3）`
})

// 2) 规则网格：129×129、间距 78.125m、边长 10000m
const xSet = new Set<number>()
const zSet = new Set<number>()
for (let i = 0; i < n; i++) { xSet.add(positions[i * 3]!); zSet.add(positions[i * 3 + 2]!) }
const ux = Array.from(xSet).sort((a, b) => a - b)
const uz = Array.from(zSet).sort((a, b) => a - b)
check('GRID-02-grid-129x129', () => {
  assert.equal(ux.length, 129)
  assert.equal(uz.length, 129)
  return `X 列 ${ux.length}，Z 行 ${uz.length}`
})
check('GRID-03-spacing-78-125', () => {
  const sx = ux[1]! - ux[0]!
  const sz = uz[1]! - uz[0]!
  assert.ok(Math.abs(sx - 78.125) < 1e-6, `X 间距 ${sx}`)
  assert.ok(Math.abs(sz - 78.125) < 1e-6, `Z 间距 ${sz}`)
  for (let i = 1; i < 129; i++) {
    assert.ok(Math.abs((ux[i]! - ux[i - 1]!) - 78.125) < 1e-6, `X 列 ${i} 间距不均匀`)
    assert.ok(Math.abs((uz[i]! - uz[i - 1]!) - 78.125) < 1e-6, `Z 行 ${i} 间距不均匀`)
  }
  return `间距 X=${sx.toFixed(4)} Z=${sz.toFixed(4)} m（均匀）`
})
check('GRID-04-extent-10km-and-origin', () => {
  const ex = ux[128]! - ux[0]!
  const ez = uz[128]! - uz[0]!
  assert.ok(Math.abs(ex - 10000) < 1e-6, `X 边长 ${ex}`)
  assert.ok(Math.abs(ez - 10000) < 1e-6, `Z 边长 ${ez}`)
  return `边长 X=${ex.toFixed(2)} Z=${ez.toFixed(2)} m；范围 X[${ux[0]}, ${ux[128]}] Z[${uz[0]}, ${uz[128]}]`
})

// 3) 网格索引重建（按坐标，不依赖顶点存储顺序），并判定对角线方向
const xRank = new Map(ux.map((v, i) => [v, i] as const))
const zRank = new Map(uz.map((v, i) => [v, i] as const))
const grid: number[][] = Array.from({ length: 129 }, () => new Array(129).fill(-1))
for (let i = 0; i < n; i++) {
  const c = xRank.get(positions[i * 3]!)!
  const r = zRank.get(positions[i * 3 + 2]!)!
  grid[r]![c] = i
}
check('GRID-05-every-cell-has-a-vertex', () => {
  for (let r = 0; r < 129; r++) for (let c = 0; c < 129; c++) assert.notEqual(grid[r]![c], -1, `grid[${r}][${c}] 缺失`)
  return '129×129 顶点全部落位（按坐标重建网格一致）'
})

function cellDiagonal(r: number, c: number): 'backslash' | 'slash' {
  const v00 = grid[r]![c]!, v10 = grid[r]![c + 1]!, v01 = grid[r + 1]![c]!, v11 = grid[r + 1]![c + 1]!
  const corners = new Set([v00, v10, v01, v11])
  const cnt = new Map<number, number>([[v00, 0], [v10, 0], [v01, 0], [v11, 0]])
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t]!, b = indices[t + 1]!, c2 = indices[t + 2]!
    if (corners.has(a) && corners.has(b) && corners.has(c2)) {
      for (const v of [a, b, c2]) cnt.set(v, (cnt.get(v) ?? 0) + 1)
    }
  }
  // 两个三角形共享的对角线端点各出现 2 次，其余角点各 1 次。
  const diag = [v00, v10, v01, v11].filter((v) => cnt.get(v) === 2)
  assert.equal(diag.length, 2, `cell(${r},${c}) 对角端点数量异常`)
  return (diag.includes(v00) && diag.includes(v11)) ? 'backslash' : 'slash'
}
let diagonalOfCell00 = 'unknown'
check('GRID-06-triangulation-diagonal-consistent', () => {
  diagonalOfCell00 = cellDiagonal(0, 0)
  for (let r = 0; r < 128; r++) {
    for (let c = 0; c < 128; c++) {
      assert.equal(cellDiagonal(r, c), diagonalOfCell00, `cell(${r},${c}) 对角线方向不一致`)
    }
  }
  return `全部 128×128 格统一采用 ${diagonalOfCell00 === 'backslash' ? '反斜线 \\（v00↔v11）' : '斜线 /（v10↔v01）'} 对角线`
})

// 4) 射线：命中（三角形内部）——与 sampleHeightOnTerrain 交叉核对
const c0 = 64, r0 = 64
const x0 = ux[c0]!, z0 = uz[r0]!
const px = x0 + 0.3 * 78.125
const pz = z0 + 0.2 * 78.125
let interiorErr = NaN
check('RAY-01-interior-hit-matches-height', () => {
  const expected = sampleHeightOnTerrain(px, pz, positions, indices)
  if (expected === null) throw new Error('采样点应在网格内')
  const hit = raycastTerrain([px, 10000, pz], DOWN, positions, indices)
  assert.ok(hit, '应命中')
  assert.ok(Math.abs(hit.point[0] - px) < 1e-6, `X 偏差 ${Math.abs(hit.point[0] - px)}`)
  assert.ok(Math.abs(hit.point[2] - pz) < 1e-6, `Z 偏差 ${Math.abs(hit.point[2] - pz)}`)
  interiorErr = Math.abs(hit.point[1] - expected)
  assert.ok(interiorErr < 1e-3, `Y 误差 ${interiorErr}`)
  const b = hit.barycentric
  assert.ok(Math.abs(b[0] + b[1] + b[2] - 1) < 1e-9, '重心坐标和 != 1')
  return `命中 y=${hit.point[1].toFixed(3)}，期望 ${expected.toFixed(3)}，误差 ${interiorErr.toExponential(2)} m`
})

// 5) 射线：边界（格边中点，共享边两侧高度一致）
const ex = x0 + 0.5 * 78.125
const ez = z0
let boundaryErr = NaN
check('RAY-02-boundary-edge-hit', () => {
  const vL = grid[r0]![c0]!, vR = grid[r0]![c0 + 1]!
  const exp = (positions[vL * 3 + 1]! + positions[vR * 3 + 1]!) / 2
  const hit = raycastTerrain([ex, 10000, ez], DOWN, positions, indices)
  assert.ok(hit, '边界应命中')
  boundaryErr = Math.abs(hit.point[1] - exp)
  assert.ok(boundaryErr < 1e-3, `边界 Y 误差 ${boundaryErr}`)
  const sampled = sampleHeightOnTerrain(ex, ez, positions, indices)
  assert.ok(sampled !== null && Math.abs(sampled - exp) < 1e-3, '边界采样与两端均值不符')
  return `边界命中 y=${hit.point[1].toFixed(3)}，两端均值 ${exp.toFixed(3)}，误差 ${boundaryErr.toExponential(2)} m`
})

// 6) 射线：未命中（超出范围 / 反向）
check('RAY-03-miss-outside-and-away', () => {
  const miss = raycastTerrain([ux[128]! + 1000, 10000, uz[128]! + 1000], DOWN, positions, indices)
  assert.equal(miss, null, '超出范围不应命中')
  const away = raycastTerrain([px, 10000, pz], [0, 1, 0], positions, indices)
  assert.equal(away, null, '反向射线不应命中')
  return '超出范围与反向射线均返回 null'
})

// 7) 非共面四边形：区分两种对角线
check('RAY-04-noncoplanar-quad-diagonal', () => {
  // A(0,0,0) B(1,0,0) C(1,1,1) D(0,0,1)：A/B/D 共面(y=0)，C 抬高 → 非共面四边形。
  const qPos = [0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1]
  const diagAC = [0, 1, 2, 0, 2, 3] // 对角线 A↔C
  const diagBD = [0, 1, 3, 1, 2, 3] // 对角线 B↔D
  const origin: Vec3 = [0.5, 5, 0.5]
  const hAC = raycastTerrain(origin, DOWN, qPos, diagAC)
  const hBD = raycastTerrain(origin, DOWN, qPos, diagBD)
  assert.ok(hAC, '对角线 AC 应命中')
  assert.ok(hBD, '对角线 BD 应命中')
  assert.ok(Math.abs(hAC.point[1] - 0.5) < 1e-9, `AC 对角线中心高 ${hAC.point[1]} 应为 0.5`)
  assert.ok(Math.abs(hBD.point[1] - 0.0) < 1e-9, `BD 对角线中心高 ${hBD.point[1]} 应为 0.0`)
  return `非共面四边形中心：AC 对角线 y=${hAC.point[1]}，BD 对角线 y=${hBD.point[1]}（正确区分）`
})

// 8) 重心重建一致性（真实三角形内部，读取实际 hit.triangle）
check('RAY-05-barycentric-reconstruction-interior', () => {
  const hit = raycastTerrain([px, 10000, pz], DOWN, positions, indices)
  assert.ok(hit, '应命中')
  const ti = hit.triangle
  const i0 = indices[ti * 3]!, i1 = indices[ti * 3 + 1]!, i2 = indices[ti * 3 + 2]!
  const a: Vec3 = [positions[i0 * 3]!, positions[i0 * 3 + 1]!, positions[i0 * 3 + 2]!]
  const b: Vec3 = [positions[i1 * 3]!, positions[i1 * 3 + 1]!, positions[i1 * 3 + 2]!]
  const c: Vec3 = [positions[i2 * 3]!, positions[i2 * 3 + 1]!, positions[i2 * 3 + 2]!]
  const [w0, w1, w2] = hit.barycentric
  const rx = w0 * a[0] + w1 * b[0] + w2 * c[0]
  const ry = w0 * a[1] + w1 * b[1] + w2 * c[1]
  const rz = w0 * a[2] + w1 * b[2] + w2 * c[2]
  const err = Math.hypot(rx - hit.point[0], ry - hit.point[1], rz - hit.point[2])
  assert.ok(err < 1e-6, `重建误差 ${err}`)
  return `命中三角形 ${ti}，重心重建误差 ${err.toExponential(2)} m`
})

// 9) 输入守卫反例（F-01）：NaN/Infinity 查询返回 null，非法网格显式抛错
function expectThrow(fn: () => unknown, msg: string): string {
  let threw = false
  try { fn() } catch { threw = true }
  assert.ok(threw, msg)
  return msg
}
check('GUARD-01-nan-inf-origin-null', () => {
  assert.equal(raycastTerrain([NaN, 10000, pz], DOWN, positions, indices), null)
  assert.equal(raycastTerrain([px, Infinity, pz], DOWN, positions, indices), null)
  return 'NaN/Infinity 原点返回 null'
})
check('GUARD-02-nan-inf-direction-null', () => {
  assert.equal(raycastTerrain([px, 10000, pz], [NaN, 0, 0], positions, indices), null)
  assert.equal(raycastTerrain([px, 10000, pz], [0, -Infinity, 0], positions, indices), null)
  return 'NaN/Infinity 方向返回 null'
})
check('GUARD-03-zero-direction-null', () => {
  assert.equal(raycastTerrain([px, 10000, pz], [0, 0, 0], positions, indices), null)
  return '零方向返回 null'
})
check('GUARD-04-nan-xz-sample-null', () => {
  assert.equal(sampleHeightOnTerrain(NaN, pz, positions, indices), null)
  assert.equal(sampleHeightOnTerrain(px, Infinity, positions, indices), null)
  return 'NaN/Infinity x/z 采样返回 null'
})
check('GUARD-05-illegal-indices-length-throws', () => {
  return expectThrow(() => raycastTerrain([px, 10000, pz], DOWN, positions, [0, 1, 2, 3]), 'indices 长度非 3 的倍数应报错')
})
check('GUARD-06-illegal-index-range-throws', () => {
  return expectThrow(() => raycastTerrain([px, 10000, pz], DOWN, positions, [0, 1, 999999]), '索引越界应报错')
})
check('GUARD-07-nan-position-throws', () => {
  return expectThrow(() => validateTerrainMesh([0, NaN, 0, 1, 0, 0, 0, 0, 1], null), 'NaN 顶点应报错')
})
check('GUARD-08-hit-result-finite', () => {
  const hit = raycastTerrain([px, 10000, pz], DOWN, positions, indices)
  assert.ok(hit, '应命中')
  assert.ok(hit.point.every(Number.isFinite), '命中点须有限')
  assert.ok(Number.isFinite(hit.distance), '距离须有限')
  assert.ok(hit.barycentric.every(Number.isFinite), '重心坐标须有限')
  return `命中点/距离/重心均有限（distance=${hit.distance.toFixed(3)}）`
})

const summary = {
  date: '2026-11-02',
  asset: 'frontend/public/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb',
  vertex_count: n,
  index_count: indices.length,
  triangle_count: mesh.triangleCount,
  grid: { nx: ux.length, nz: uz.length, spacing_x: ux[1]! - ux[0]!, spacing_z: uz[1]! - uz[0]!, extent_x: ux[128]! - ux[0]!, extent_z: uz[128]! - uz[0]!, min_x: ux[0], max_x: ux[128]!, min_z: uz[0], max_z: uz[128]! },
  diagonal: diagonalOfCell00,
  ray_checks: { interior_error_m: interiorErr, boundary_error_m: boundaryErr },
  unity_transform: '待实测（缺失，不默认单位矩阵；两份草案保持 unregistered / fire_patch_overlay=false）',
  checks: results,
}
mkdirSync(outDir, { recursive: true })
writeFileSync(join(outDir, 'result.json'), JSON.stringify(summary, null, 2) + '\n')
const passed = results.filter((r) => r.ok).length
console.log(`\nRESULT: ${passed}/${results.length} checks passed`)
process.exit(passed === results.length ? 0 : 1)
