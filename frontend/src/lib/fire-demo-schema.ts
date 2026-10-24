import type { FireKeyframe, FireLevel, FirePatch, FireRing, FireStateDemo, ResolvedPatchState, ActiveFirePatch } from './types'

// 纯校验与求值器：不依赖 Vue / DOM / 网络，浏览器与 scripts/check-data.ts 共用，
// 避免维护两套“等价”校验实现。

export const FIRE_DEMO_SCHEMA = 'Fire-X fire_state demo'
export const FIRE_DEMO_SCHEMA_VERSION = '1.0'
export const TERRAIN_EXTENT_M = 2000 // 地形为 [-2000,2000]²，环坐标必须在此范围内（不 clamp）
export const DEFAULT_INTENSITY = 0.6
export const DEFAULT_LEVEL: FireLevel = 'warning'
export const GROUND_OFFSET_MIN_M = 0
export const GROUND_OFFSET_MAX_M = 1 // 仅用于避免覆盖层与地形显示重叠，不代表火焰高度

export type ValidationResult = { ok: true; demo: FireStateDemo } | { ok: false; errors: string[] }

// ---- 纯几何助手 ----

export function ringSignedArea(pts: [number, number][]): number {
  let area = 0
  for (let i = 0; i < pts.length; i++) {
    const [x1, z1] = pts[i]
    const [x2, z2] = pts[(i + 1) % pts.length]
    area += x1 * z2 - x2 * z1
  }
  return area / 2
}

/** 偶奇规则（射线法）判断 (x,z) 是否在闭合环内。 */
export function pointInRingXZ(x: number, z: number, pts: [number, number][]): boolean {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, zi] = pts[i]
    const [xj, zj] = pts[j]
    const crosses = (zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi
    if (crosses) inside = !inside
  }
  return inside
}

function orientation(ax: number, az: number, bx: number, bz: number, cx: number, cz: number): number {
  const val = (bz - az) * (cx - bx) - (bx - ax) * (cz - bz)
  if (Math.abs(val) < 1e-12) return 0
  return val > 0 ? 1 : 2
}

function onSegment(ax: number, az: number, bx: number, bz: number, cx: number, cz: number): boolean {
  return Math.min(ax, bx) <= cx + 1e-9 && cx <= Math.max(ax, bx) + 1e-9 &&
    Math.min(az, bz) <= cz + 1e-9 && cz <= Math.max(az, bz) + 1e-9
}

function segmentsIntersect(p1: [number, number], p2: [number, number], q1: [number, number], q2: [number, number]): boolean {
  const o1 = orientation(p1[0], p1[1], p2[0], p2[1], q1[0], q1[1])
  const o2 = orientation(p1[0], p1[1], p2[0], p2[1], q2[0], q2[1])
  const o3 = orientation(q1[0], q1[1], q2[0], q2[1], p1[0], p1[1])
  const o4 = orientation(q1[0], q1[1], q2[0], q2[1], p2[0], p2[1])
  if (o1 !== o2 && o3 !== o4) return true
  if (o1 === 0 && onSegment(p1[0], p1[1], p2[0], p2[1], q1[0], q1[1])) return true
  if (o2 === 0 && onSegment(p1[0], p1[1], p2[0], p2[1], q2[0], q2[1])) return true
  if (o3 === 0 && onSegment(q1[0], q1[1], q2[0], q2[1], p1[0], p1[1])) return true
  if (o4 === 0 && onSegment(q1[0], q1[1], q2[0], q2[1], p2[0], p2[1])) return true
  return false
}

function ringSelfIntersects(pts: [number, number][]): boolean {
  const n = pts.length
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue // 相邻边共享端点，允许
      if (segmentsIntersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])) return true
    }
  }
  return false
}

// ---- 校验（整份文件严格校验：任一非法即拒绝整份） ----

function validateRing(ring: unknown, where: string, errors: string[]): FireRing | null {
  if (typeof ring !== 'object' || ring === null) { errors.push(`${where} 不是对象`); return null }
  const o = ring as Record<string, unknown>
  if (!Array.isArray(o.ring_xz)) { errors.push(`${where}.ring_xz 必须为数组`); return null }
  const raw = o.ring_xz as unknown[]
  const cleaned: [number, number][] = []
  for (let i = 0; i < raw.length; i++) {
    const v = raw[i]
    if (!Array.isArray(v) || v.length !== 2 || typeof v[0] !== 'number' || typeof v[1] !== 'number' || !Number.isFinite(v[0]) || !Number.isFinite(v[1])) {
      errors.push(`${where}.ring_xz[${i}] 不是有限 [x,z] 数值对`); return null
    }
    const p: [number, number] = [v[0], v[1]]
    const last = cleaned[cleaned.length - 1]
    if (last && last[0] === p[0] && last[1] === p[1]) continue
    cleaned.push(p)
  }
  // 允许显式闭合（首尾重复），去除后判断顶点数
  if (cleaned.length > 1 && cleaned[0][0] === cleaned[cleaned.length - 1][0] && cleaned[0][1] === cleaned[cleaned.length - 1][1]) cleaned.pop()
  if (cleaned.length < 3) { errors.push(`${where}.ring_xz 去重后顶点不足 3`); return null }
  if (cleaned.length > 64) { errors.push(`${where}.ring_xz 顶点过多（>64）`); return null }
  for (const [x, z] of cleaned) {
    if (Math.abs(x) > TERRAIN_EXTENT_M || Math.abs(z) > TERRAIN_EXTENT_M) { errors.push(`${where}.ring_xz 越出地形 [-${TERRAIN_EXTENT_M},${TERRAIN_EXTENT_M}]²`); return null }
  }
  if (Math.abs(ringSignedArea(cleaned)) < 1e-6) { errors.push(`${where}.ring_xz 面积接近 0`); return null }
  if (ringSelfIntersects(cleaned)) { errors.push(`${where}.ring_xz 存在自交`); return null }

  let offset = 0.5
  if (o.ground_offset_m !== undefined) {
    if (typeof o.ground_offset_m !== 'number' || !Number.isFinite(o.ground_offset_m) || o.ground_offset_m < GROUND_OFFSET_MIN_M || o.ground_offset_m > GROUND_OFFSET_MAX_M) {
      errors.push(`${where}.ground_offset_m 必须在 [${GROUND_OFFSET_MIN_M},${GROUND_OFFSET_MAX_M}]`); return null
    }
    offset = o.ground_offset_m
  }
  return { ring_xz: cleaned, ground_offset_m: offset }
}

function validateKeyframes(arr: unknown[], where: string, duration_s: number, errors: string[]): FireKeyframe[] | null {
  const out: FireKeyframe[] = []
  let prevT = -Infinity
  for (let i = 0; i < arr.length; i++) {
    const kf = arr[i]
    if (typeof kf !== 'object' || kf === null) { errors.push(`${where}[${i}] 不是对象`); return null }
    const o = kf as Record<string, unknown>
    if (typeof o.t_s !== 'number' || !Number.isFinite(o.t_s) || o.t_s < 0 || o.t_s > duration_s) { errors.push(`${where}[${i}].t_s 必须在 [0, ${duration_s}]`); return null }
    if (o.t_s <= prevT) { errors.push(`${where}[${i}].t_s 必须严格升序`); return null }
    prevT = o.t_s
    if (typeof o.active !== 'boolean') { errors.push(`${where}[${i}].active 必须为 boolean`); return null }
    let intensity: number | undefined
    if (o.intensity !== undefined) {
      if (typeof o.intensity !== 'number' || !Number.isFinite(o.intensity) || o.intensity < 0 || o.intensity > 1) { errors.push(`${where}[${i}].intensity 必须在 [0,1]`); return null }
      intensity = o.intensity
    }
    let level: FireLevel | undefined
    if (o.level !== undefined) {
      if (o.level !== 'watch' && o.level !== 'warning' && o.level !== 'critical') { errors.push(`${where}[${i}].level 非法`); return null }
      level = o.level
    }
    out.push({ t_s: o.t_s, active: o.active, intensity, level })
  }
  return out
}

export function validateFireStateDemo(input: unknown): ValidationResult {
  const errors: string[] = []
  if (typeof input !== 'object' || input === null) return { ok: false, errors: ['演示数据不是对象'] }
  const d = input as Record<string, unknown>

  if (d.schema !== FIRE_DEMO_SCHEMA) errors.push(`schema 必须为 ${FIRE_DEMO_SCHEMA}`)
  if (d.schema_version !== FIRE_DEMO_SCHEMA_VERSION) errors.push(`schema_version 必须为 ${FIRE_DEMO_SCHEMA_VERSION}`)
  if (d.is_mock !== true) errors.push('is_mock 必须为 true')
  if (d.demo_origin !== 'synthetic_demo_rule') errors.push('demo_origin 必须为 synthetic_demo_rule')
  if (d.plant_id !== 'GEM_COAL_ZHIJIN') errors.push('plant_id 必须为 GEM_COAL_ZHIJIN')
  if (d.scene_id !== 'zhijin_pilot') errors.push('scene_id 必须为 zhijin_pilot')
  if (typeof d.duration_s !== 'number' || !Number.isFinite(d.duration_s) || d.duration_s <= 0) errors.push('duration_s 必须为有限正数')
  if (!Array.isArray(d.patches) || d.patches.length === 0) errors.push('patches 必须为非空数组')
  const rules = d.rules as Record<string, unknown> | undefined
  let spreadNote = ''
  let disclaimer = ''
  if (!rules || typeof rules.disclaimer !== 'string' || rules.disclaimer.trim() === '') errors.push('rules.disclaimer 缺失')
  else { disclaimer = rules.disclaimer; spreadNote = typeof rules.spread_note === 'string' ? rules.spread_note : '' }

  if (errors.length > 0) return { ok: false, errors }

  const duration_s = d.duration_s as number
  const seenIds = new Set<string>()
  const patches: FirePatch[] = []
  const rawPatches = d.patches as unknown[]
  for (let i = 0; i < rawPatches.length; i++) {
    const where = `patches[${i}]`
    const p = rawPatches[i]
    if (typeof p !== 'object' || p === null) { errors.push(`${where} 不是对象`); continue }
    const o = p as Record<string, unknown>
    const id = o.patch_id
    if (typeof id !== 'string' || id.trim() === '') { errors.push(`${where}.patch_id 非法`); continue }
    if (seenIds.has(id)) { errors.push(`${where}.patch_id 重复：${id}`); continue }
    seenIds.add(id)
    if (o.plant_id !== 'GEM_COAL_ZHIJIN') errors.push(`${where}.plant_id 不匹配`)
    if (o.scene_id !== 'zhijin_pilot') errors.push(`${where}.scene_id 不匹配`)
    if (o.is_mock !== true) errors.push(`${where}.is_mock 必须为 true`)

    let rings: FireRing[] = []
    if (!Array.isArray(o.rings) || o.rings.length === 0) { errors.push(`${where}.rings 必须为非空数组`) }
    else {
      const rawRings = o.rings as unknown[]
      for (let ri = 0; ri < rawRings.length; ri++) {
        const r = validateRing(rawRings[ri], `${where}.rings[${ri}]`, errors)
        if (r) rings.push(r)
      }
    }
    let keyframes: FireKeyframe[] = []
    if (!Array.isArray(o.keyframes)) { errors.push(`${where}.keyframes 必须为数组`) }
    else {
      const kf = validateKeyframes(o.keyframes as unknown[], `${where}.keyframes`, duration_s, errors)
      if (kf) keyframes = kf
    }
    patches.push({ patch_id: id as string, plant_id: o.plant_id as string, scene_id: o.scene_id as string, is_mock: true, rings, keyframes })
  }

  if (errors.length > 0) return { ok: false, errors }

  const demo: FireStateDemo = {
    schema: FIRE_DEMO_SCHEMA,
    schema_version: FIRE_DEMO_SCHEMA_VERSION,
    is_mock: true,
    demo_origin: 'synthetic_demo_rule',
    plant_id: 'GEM_COAL_ZHIJIN',
    scene_id: 'zhijin_pilot',
    duration_s,
    patches,
    rules: { spread_note: spreadNote, disclaimer },
  }
  return { ok: true, demo }
}

// ---- 求值（纯函数，关键帧间保持上一关键帧取值，无插值） ----

export function resolvePatch(patch: FirePatch, t_s: number): ResolvedPatchState {
  let active = false
  let intensity = DEFAULT_INTENSITY
  let level = DEFAULT_LEVEL
  for (const kf of patch.keyframes) {
    if (kf.t_s > t_s) break
    active = kf.active
    if (kf.intensity !== undefined) intensity = kf.intensity
    if (kf.level !== undefined) level = kf.level
  }
  return { patch_id: patch.patch_id, active, intensity, level }
}

export function resolveActivePatches(demo: FireStateDemo, t_s: number): ActiveFirePatch[] {
  const out: ActiveFirePatch[] = []
  for (const p of demo.patches) {
    const r = resolvePatch(p, t_s)
    if (r.active) out.push({ patch_id: p.patch_id, level: r.level, intensity: r.intensity, rings: p.rings })
  }
  return out
}
