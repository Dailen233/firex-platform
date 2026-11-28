import type { ActiveFirePatch } from './types'

// Pure backend-contract layer (types + runtime validation + binding + mapping).
// No fetch / import.meta / Vue / DOM, so it is shared between the app and
// scripts/check-data.ts and unit-testable in Node. The fetch layer lives in
// backend.ts and re-exports everything from here.

export type InputSource = 'simulation' | 'real'
export type TimeBasis = 'simulation_relative' | 'utc_anchored'
export type StateStatus = 'no_observation' | 'observation'

export interface BackendHealth {
  status: string
  algorithm_mode: string
  service: string
  processing_mode: string
}

export interface BackendRunRecord {
  run_id: string
  plant_id: string
  scene_id: string
  asset_version: string
  coordinate_frame_id: string | null
  input_source: InputSource
  schema_version: string
  created_at: string
  simulation_time_origin_s: number | null
  time_origin_utc: string | null
}

export interface BackendRunCreate {
  plant_id: string
  scene_id: string
  asset_version: string
  coordinate_frame_id: string | null
  input_source: InputSource
  simulation_time_origin_s?: number | null
  time_origin_utc?: string | null
}

export interface BackendFirePatch {
  patch_id: string
  /** Local XZ closed ring (X east, Z south, metres); Y is sampled by the viewer. */
  geometry: [number, number][]
}

export interface BackendDetection2D {
  class_id: number
  class_name: string
  confidence: number
  bbox: [number, number, number, number]
}

type XYZ = [number, number, number]
export interface BackendFlameEstimate {
  method: 'single_view_flame_silhouette'
  capture_id: string
  glb_sha256: string
  anchor_xyz_m: XYZ
  camera_xyz_m: XYZ
  vertices: XYZ[]
  triangles: [number, number, number][]
  uv: [number, number][]
  texture_png_base64: string
}

export interface BackendRunState {
  run_id: string
  plant_id: string
  scene_id: string
  asset_version: string
  coordinate_frame_id: string | null
  input_source: InputSource
  schema_version: string
  state_status: StateStatus
  revision: number
  observation_time_s: number | null
  result_origin: string | null
  provider_version: string | null
  evidence_capture_ids: string[]
  patches: BackendFirePatch[]
  detections?: BackendDetection2D[]
  fire_detected?: boolean | null
  flame?: BackendFlameEstimate | null
  observation_expires_at?: string | null
  produced_at: string | null
  time_basis: TimeBasis
  simulation_time_origin_s: number | null
  time_origin_utc: string | null
}

export type AlertStatus = 'no_observation' | 'no_detection' | 'fire' | 'stale'

export interface AtlasFireStatusItem {
  plant_id: string
  run_id: string
  scene_id: string
  asset_version: string
  coordinate_frame_id: string | null
  input_source: InputSource
  state_status: string
  alert_status: AlertStatus
  fire_detected: boolean
  is_fresh: boolean
  revision: number
  observation_time_s: number | null
  time_basis: TimeBasis
  result_origin: string | null
  provider_version: string | null
  produced_at: string | null
  evidence_capture_ids: string[]
  patch_count: number
  detection_count: number
  model_ref: string | null
  threshold: number | null
}

export interface AtlasFireStatus {
  generated_at: string
  fresh_after_s: number
  monitored_run_ids: string[]
  items: AtlasFireStatusItem[]
}

export interface BackendReconstructionSummary {
  run_id: string
  status: 'none' | 'available'
  revision: number | null
  group_id: string | null
  simulation_time_s: number | null
  source: string | null
  mask_source: string | null
  voxel_count: number | null
  voxel_size_m: number | null
  byte_size: number | null
  ply_sha256: string | null
  glb_sha256: string | null
  produced_at: string | null
}

export interface BackendReconstructionJob {
  job_id: string
  run_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed'
  source: string
  received_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  simulation_time_s: number | null
  group_id: string | null
  voxel_count: number | null
  mask_source: string | null
  revision: number | null
  zip_sha256: string
  zip_byte_size: number
}

export interface BackendReconstructionFrame {
  revision: number
  group_id: string
  simulation_time_s: number
  source: string
  mask_source: string | null
  voxel_count: number
  voxel_size_m: number
  byte_size: number
  ply_sha256: string
  glb_sha256: string | null
  produced_at: string
}

export type Validation<T> = { ok: true; value: T } | { ok: false; errors: string[] }

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.trim() !== ''
}
function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}
function isNonNegativeInteger(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0
}
const INPUT_SOURCES: InputSource[] = ['simulation', 'real']
const TIME_BASES: TimeBasis[] = ['simulation_relative', 'utc_anchored']
const STATE_STATUSES: StateStatus[] = ['no_observation', 'observation']

function readString(raw: Record<string, unknown>, key: string, errors: string[], where: string): string {
  const v = raw[key]
  if (!isNonEmptyString(v)) {
    errors.push(`${where}.${key} 必须为非空字符串`)
    return ''
  }
  return v
}

function readNullableString(raw: Record<string, unknown>, key: string, errors: string[], where: string): string | null {
  const v = raw[key]
  if (v !== null && !isNonEmptyString(v)) {
    errors.push(`${where}.${key} 必须为 null 或非空字符串`)
    return null
  }
  return v === null ? null : (v as string)
}

function readNullableNumber(raw: Record<string, unknown>, key: string, errors: string[], where: string): number | null {
  const v = raw[key]
  if (v !== null && !isFiniteNumber(v)) {
    errors.push(`${where}.${key} 必须为 null 或有限数值`)
    return null
  }
  return v === null ? null : (v as number)
}

function readInputSource(raw: Record<string, unknown>, errors: string[], where: string): InputSource {
  const v = raw.input_source
  if (!INPUT_SOURCES.includes(v as InputSource)) {
    errors.push(`${where}.input_source 必须为 ${INPUT_SOURCES.join('/')}`)
    return 'simulation'
  }
  return v as InputSource
}

/** Validate a closed local-XZ ring: finite [x,z] pairs, >=4 points, first==last. */
function validateGeometry(v: unknown, where: string, errors: string[]): [number, number][] | null {
  if (!Array.isArray(v)) {
    errors.push(`${where}.geometry 必须为数组`)
    return null
  }
  const pts: [number, number][] = []
  for (let i = 0; i < v.length; i++) {
    const p = v[i]
    if (!Array.isArray(p) || p.length !== 2 || !isFiniteNumber(p[0]) || !isFiniteNumber(p[1])) {
      errors.push(`${where}.geometry[${i}] 不是有限 [x,z] 数值对`)
      return null
    }
    pts.push([p[0] as number, p[1] as number])
  }
  if (pts.length < 4) {
    errors.push(`${where}.geometry 顶点不足（需首尾闭合的 >=3 顶点环）`)
    return null
  }
  const first = pts[0]!
  const last = pts[pts.length - 1]!
  if (first[0] !== last[0] || first[1] !== last[1]) {
    errors.push(`${where}.geometry 未闭合（首点 != 末点）`)
    return null
  }
  return pts
}

export function validateHealth(raw: unknown): Validation<BackendHealth> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['health 不是对象'] }
  const status = readString(raw, 'status', errors, 'health')
  const algorithm_mode = readString(raw, 'algorithm_mode', errors, 'health')
  const service = readString(raw, 'service', errors, 'health')
  const processing_mode = readString(raw, 'processing_mode', errors, 'health')
  if (errors.length) return { ok: false, errors }
  return { ok: true, value: { status, algorithm_mode, service, processing_mode } }
}

export function validateRunRecord(raw: unknown): Validation<BackendRunRecord> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['run 不是对象'] }
  const run_id = readString(raw, 'run_id', errors, 'run')
  const plant_id = readString(raw, 'plant_id', errors, 'run')
  const scene_id = readString(raw, 'scene_id', errors, 'run')
  const asset_version = readString(raw, 'asset_version', errors, 'run')
  const schema_version = readString(raw, 'schema_version', errors, 'run')
  const created_at = readString(raw, 'created_at', errors, 'run')
  const coordinate_frame_id = readNullableString(raw, 'coordinate_frame_id', errors, 'run')
  const input_source = readInputSource(raw, errors, 'run')
  const simulation_time_origin_s = readNullableNumber(raw, 'simulation_time_origin_s', errors, 'run')
  const time_origin_utc = readNullableString(raw, 'time_origin_utc', errors, 'run')
  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      run_id, plant_id, scene_id, asset_version, coordinate_frame_id,
      input_source, schema_version, created_at, simulation_time_origin_s, time_origin_utc,
    },
  }
}

function isXYZ(v: unknown): v is XYZ {
  return Array.isArray(v) && v.length === 3 && v.every(isFiniteNumber)
}

function validateDetections(value: unknown, errors: string[]): BackendDetection2D[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || !value.every((d: unknown) =>
    isRecord(d) && isNonNegativeInteger(d.class_id) && isNonEmptyString(d.class_name)
    && isFiniteNumber(d.confidence) && d.confidence >= 0 && d.confidence <= 1
    && Array.isArray(d.bbox) && d.bbox.length === 4 && d.bbox.every(isFiniteNumber)
    && d.bbox[0] < d.bbox[2] && d.bbox[1] < d.bbox[3]
  )) {
    errors.push('run/state.detections 包含无效的检测框')
    return []
  }
  return value
}

function validateFlame(value: unknown): BackendFlameEstimate | null {
  if (!isRecord(value) || value.method !== 'single_view_flame_silhouette'
      || !isNonEmptyString(value.capture_id) || typeof value.glb_sha256 !== 'string'
      || !/^[a-f0-9]{64}$/.test(value.glb_sha256)
      || !isXYZ(value.anchor_xyz_m) || !isXYZ(value.camera_xyz_m)) return null
  const {vertices, triangles, uv, texture_png_base64} = value
  if (!Array.isArray(vertices) || vertices.length < 3 || vertices.length > 64 || !vertices.every(isXYZ)) return null
  if (!Array.isArray(triangles) || triangles.length < 1 || triangles.length > 62
      || !triangles.every((f: unknown) => Array.isArray(f) && f.length === 3 && new Set(f).size === 3
          && f.every(i => isNonNegativeInteger(i) && i < vertices.length))) return null
  if (!Array.isArray(uv) || uv.length !== vertices.length || !uv.every((p: unknown) =>
      Array.isArray(p) && p.length === 2 && p.every(v => isFiniteNumber(v) && v >= 0 && v <= 1))) return null
  if (typeof texture_png_base64 !== 'string' || texture_png_base64.length < 4 || texture_png_base64.length > 100000
      || texture_png_base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(texture_png_base64)) return null
  return {
    method: value.method, capture_id: value.capture_id, glb_sha256: value.glb_sha256,
    anchor_xyz_m: value.anchor_xyz_m, camera_xyz_m: value.camera_xyz_m, vertices, triangles, uv, texture_png_base64,
  }
}

export function validateRunState(raw: unknown): Validation<BackendRunState> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['run/state 不是对象'] }
  const run_id = readString(raw, 'run_id', errors, 'run/state')
  const plant_id = readString(raw, 'plant_id', errors, 'run/state')
  const scene_id = readString(raw, 'scene_id', errors, 'run/state')
  const asset_version = readString(raw, 'asset_version', errors, 'run/state')
  const schema_version = readString(raw, 'schema_version', errors, 'run/state')
  const produced_at = readString(raw, 'produced_at', errors, 'run/state')
  const coordinate_frame_id = readNullableString(raw, 'coordinate_frame_id', errors, 'run/state')
  const input_source = readInputSource(raw, errors, 'run/state')

  let state_status: StateStatus = 'no_observation'
  if (!STATE_STATUSES.includes(raw.state_status as StateStatus)) {
    errors.push(`run/state.state_status 必须为 ${STATE_STATUSES.join('/')}`)
  } else {
    state_status = raw.state_status as StateStatus
  }

  let revision = -1
  if (!isNonNegativeInteger(raw.revision)) {
    errors.push('run/state.revision 必须为非负整数')
  } else {
    revision = raw.revision as number
  }

  let time_basis: TimeBasis = 'simulation_relative'
  if (!TIME_BASES.includes(raw.time_basis as TimeBasis)) {
    errors.push(`run/state.time_basis 必须为 ${TIME_BASES.join('/')}`)
  } else {
    time_basis = raw.time_basis as TimeBasis
  }
  if ((input_source === 'simulation' && time_basis !== 'simulation_relative') ||
      (input_source === 'real' && time_basis !== 'utc_anchored')) {
    errors.push(`run/state.time_basis 与 input_source 不一致（${input_source} -> ${time_basis}）`)
  }

  const simulation_time_origin_s = readNullableNumber(raw, 'simulation_time_origin_s', errors, 'run/state')
  const time_origin_utc = readNullableString(raw, 'time_origin_utc', errors, 'run/state')

  const evidence_capture_ids: string[] = []
  if (!Array.isArray(raw.evidence_capture_ids)) {
    errors.push('run/state.evidence_capture_ids 必须为数组')
  } else {
    for (let i = 0; i < raw.evidence_capture_ids.length; i++) {
      const e = raw.evidence_capture_ids[i]
      if (!isNonEmptyString(e)) {
        errors.push(`run/state.evidence_capture_ids[${i}] 必须为非空字符串`)
        break
      }
      evidence_capture_ids.push(e)
    }
  }

  const patches: BackendFirePatch[] = []
  if (!Array.isArray(raw.patches)) {
    errors.push('run/state.patches 必须为数组')
  } else {
    for (let i = 0; i < (raw.patches as unknown[]).length; i++) {
      const p = (raw.patches as unknown[])[i]
      if (!isRecord(p)) { errors.push(`run/state.patches[${i}] 不是对象`); continue }
      const patch_id = readString(p, 'patch_id', errors, `run/state.patches[${i}]`)
      const geometry = validateGeometry(p.geometry, `run/state.patches[${i}]`, errors)
      if (patch_id && geometry !== null) patches.push({ patch_id, geometry })
    }
  }

  const observation_time_s = readNullableNumber(raw, 'observation_time_s', errors, 'run/state')
  const result_origin = readNullableString(raw, 'result_origin', errors, 'run/state')
  const provider_version = readNullableString(raw, 'provider_version', errors, 'run/state')

  const detections = validateDetections(raw.detections, errors)
  const fire_detected = typeof raw.fire_detected === 'boolean' ? raw.fire_detected : null
  if (raw.fire_detected != null && fire_detected === null) errors.push('run/state.fire_detected 必须为布尔值或 null')
  const observation_expires_at = raw.observation_expires_at == null ? null
    : readString(raw, 'observation_expires_at', errors, 'run/state')
  if (observation_expires_at && !Number.isFinite(Date.parse(observation_expires_at))) {
    errors.push('run/state.observation_expires_at 不是有效时间')
  }
  const flame = raw.flame == null ? null : validateFlame(raw.flame)
  if (raw.flame != null && (!flame || input_source !== 'simulation' || result_origin !== 'yolo'
      || fire_detected !== true || !evidence_capture_ids.includes(flame.capture_id) || !observation_expires_at)) {
    errors.push('run/state.flame 无效或与本次仿真观测不匹配')
  }

  // Cross-field semantics for the two states.

  if (state_status === 'observation') {
    if (observation_time_s === null) errors.push('observation 状态必须提供 observation_time_s')
    if (result_origin === null) errors.push('observation 状态必须提供 result_origin')
    if (provider_version === null) errors.push('observation 状态必须提供 provider_version')
    if (result_origin === 'yolo') {
      if (fire_detected === null || !Array.isArray(raw.detections) || evidence_capture_ids.length === 0) {
        errors.push('YOLO 观测必须提供检测结果和证据帧')
      }
    } else if (patches.length === 0) {
      errors.push('轮廓观测必须提供非空 patches')
    }
  } else {
    if (revision !== 0) errors.push('no_observation 状态 revision 必须为 0')
    if (observation_time_s !== null) errors.push('no_observation 状态 observation_time_s 必须为 null')
    if (result_origin !== null) errors.push('no_observation 状态 result_origin 必须为 null')
    if (provider_version !== null) errors.push('no_observation 状态 provider_version 必须为 null')
    if (patches.length !== 0 || detections.length || flame || fire_detected !== null || observation_expires_at) errors.push('no_observation 状态不应携带火情观测')
  }

  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      run_id, plant_id, scene_id, asset_version, coordinate_frame_id,
      input_source, schema_version, state_status, revision, observation_time_s,
      result_origin, provider_version, evidence_capture_ids, patches, detections, fire_detected, flame, observation_expires_at, produced_at,
      time_basis, simulation_time_origin_s, time_origin_utc,
    },
  }
}

const ALERT_STATUSES: AlertStatus[] = ['no_observation', 'no_detection', 'fire', 'stale']

export function validateAtlasFireStatus(raw: unknown): Validation<AtlasFireStatus> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['atlas/fire-status 不是对象'] }
  const generated_at = readString(raw, 'generated_at', errors, 'atlas')
  const fresh_after_s = raw.fresh_after_s
  if (typeof fresh_after_s !== 'number' || !Number.isInteger(fresh_after_s) || fresh_after_s <= 0) {
    errors.push('atlas.fresh_after_s 必须为正整数')
  }
  const monitored_run_ids: string[] = []
  if (!Array.isArray(raw.monitored_run_ids)) {
    errors.push('atlas.monitored_run_ids 必须为数组')
  } else {
    for (let i = 0; i < raw.monitored_run_ids.length; i++) {
      const e = raw.monitored_run_ids[i]
      if (!isNonEmptyString(e)) { errors.push(`atlas.monitored_run_ids[${i}] 必须为非空字符串`); break }
      monitored_run_ids.push(e)
    }
  }
  const items: AtlasFireStatusItem[] = []
  if (!Array.isArray(raw.items)) {
    errors.push('atlas.items 必须为数组')
  } else {
    for (let i = 0; i < (raw.items as unknown[]).length; i++) {
      const it = (raw.items as unknown[])[i]
      if (!isRecord(it)) { errors.push(`atlas.items[${i}] 不是对象`); continue }
      const where = `atlas.items[${i}]`
      const plant_id = readString(it, 'plant_id', errors, where)
      const run_id = readString(it, 'run_id', errors, where)
      const scene_id = readString(it, 'scene_id', errors, where)
      const asset_version = readString(it, 'asset_version', errors, where)
      const coordinate_frame_id = readNullableString(it, 'coordinate_frame_id', errors, where)
      const input_source = readInputSource(it, errors, where)
      const state_status = readString(it, 'state_status', errors, where)
      if (!ALERT_STATUSES.includes(it.alert_status as AlertStatus)) {
        errors.push(`${where}.alert_status 必须为 ${ALERT_STATUSES.join('/')}`)
      }
      if (typeof it.fire_detected !== 'boolean') errors.push(`${where}.fire_detected 必须为布尔`)
      if (typeof it.is_fresh !== 'boolean') errors.push(`${where}.is_fresh 必须为布尔`)
      if (!isNonNegativeInteger(it.revision)) errors.push(`${where}.revision 必须为非负整数`)
      const observation_time_s = readNullableNumber(it, 'observation_time_s', errors, where)
      if (!TIME_BASES.includes(it.time_basis as TimeBasis)) errors.push(`${where}.time_basis 必须为 ${TIME_BASES.join('/')}`)
      const result_origin = readNullableString(it, 'result_origin', errors, where)
      const provider_version = readNullableString(it, 'provider_version', errors, where)
      const produced_at = readNullableString(it, 'produced_at', errors, where)
      if (!isNonNegativeInteger(it.patch_count)) errors.push(`${where}.patch_count 必须为非负整数`)
      if (!isNonNegativeInteger(it.detection_count)) errors.push(`${where}.detection_count 必须为非负整数`)
      const model_ref = readNullableString(it, 'model_ref', errors, where)
      const threshold = readNullableNumber(it, 'threshold', errors, where)
      const evidence_capture_ids: string[] = []
      if (!Array.isArray(it.evidence_capture_ids)) {
        errors.push(`${where}.evidence_capture_ids 必须为数组`)
      } else {
        for (let k = 0; k < (it.evidence_capture_ids as unknown[]).length; k++) {
          const e = (it.evidence_capture_ids as unknown[])[k]
          if (!isNonEmptyString(e)) { errors.push(`${where}.evidence_capture_ids[${k}] 必须为非空字符串`); break }
          evidence_capture_ids.push(e)
        }
      }
      items.push({
        plant_id, run_id, scene_id, asset_version, coordinate_frame_id, input_source, state_status,
        alert_status: it.alert_status as AlertStatus,
        fire_detected: it.fire_detected as boolean,
        is_fresh: it.is_fresh as boolean,
        revision: it.revision as number,
        observation_time_s,
        time_basis: it.time_basis as TimeBasis,
        result_origin, provider_version, produced_at,
        evidence_capture_ids,
        patch_count: it.patch_count as number,
        detection_count: it.detection_count as number,
        model_ref,
        threshold,
      })
    }
  }
  if (errors.length) return { ok: false, errors }
  return { ok: true, value: { generated_at, fresh_after_s: fresh_after_s as number, monitored_run_ids, items } }
}

function readNullableNonNegativeInt(raw: Record<string, unknown>, key: string, errors: string[], where: string): number | null {
  const v = raw[key]
  if (v === null || v === undefined) return null
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 0) {
    errors.push(`${where}.${key} 必须为 null 或非负整数`)
    return null
  }
  return v
}

export function validateReconstructionSummary(raw: unknown): Validation<BackendReconstructionSummary> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['reconstruction 不是对象'] }
  const run_id = readString(raw, 'run_id', errors, 'reconstruction')
  let status: BackendReconstructionSummary['status'] = 'none'
  if (raw.status !== 'none' && raw.status !== 'available') {
    errors.push('reconstruction.status 必须为 none/available')
  } else {
    status = raw.status
  }
  const revision = readNullableNonNegativeInt(raw, 'revision', errors, 'reconstruction')
  const group_id = readNullableString(raw, 'group_id', errors, 'reconstruction')
  const simulation_time_s = readNullableNumber(raw, 'simulation_time_s', errors, 'reconstruction')
  const source = readNullableString(raw, 'source', errors, 'reconstruction')
  const mask_source = readNullableString(raw, 'mask_source', errors, 'reconstruction')
  const voxel_count = readNullableNonNegativeInt(raw, 'voxel_count', errors, 'reconstruction')
  const voxel_size_m = readNullableNumber(raw, 'voxel_size_m', errors, 'reconstruction')
  const byte_size = readNullableNonNegativeInt(raw, 'byte_size', errors, 'reconstruction')
  const ply_sha256 = readNullableString(raw, 'ply_sha256', errors, 'reconstruction')
  const glb_sha256 = readNullableString(raw, 'glb_sha256', errors, 'reconstruction')
  const produced_at = readNullableString(raw, 'produced_at', errors, 'reconstruction')

  if (status === 'available') {
    if (revision === null) errors.push('reconstruction 有结果时必须提供 revision')
    if (simulation_time_s === null) errors.push('reconstruction 有结果时必须提供 simulation_time_s')
    if (voxel_count === null) errors.push('reconstruction 有结果时必须提供 voxel_count')
    if (byte_size === null) errors.push('reconstruction 有结果时必须提供 byte_size')
    if (group_id === null) errors.push('reconstruction 有结果时必须提供 group_id')
    if (ply_sha256 === null || !/^[a-f0-9]{64}$/.test(ply_sha256)) errors.push('reconstruction 有结果时必须提供有效的 ply_sha256')
  }
  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      run_id, status, revision, group_id, simulation_time_s, source, mask_source,
      voxel_count, voxel_size_m, byte_size, ply_sha256, glb_sha256, produced_at,
    },
  }
}

export function validateReconstructionJob(raw: unknown): Validation<BackendReconstructionJob> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['reconstruction job 不是对象'] }
  const job_id = readString(raw, 'job_id', errors, 'job')
  const run_id = readString(raw, 'run_id', errors, 'job')
  let status: BackendReconstructionJob['status'] = 'queued'
  if (!['queued', 'processing', 'completed', 'failed'].includes(raw.status as string)) {
    errors.push('job.status 必须为 queued/processing/completed/failed')
  } else {
    status = raw.status as BackendReconstructionJob['status']
  }
  const source = readString(raw, 'source', errors, 'job')
  const received_at = readString(raw, 'received_at', errors, 'job')
  const started_at = readNullableString(raw, 'started_at', errors, 'job')
  const finished_at = readNullableString(raw, 'finished_at', errors, 'job')
  const error = readNullableString(raw, 'error', errors, 'job')
  const simulation_time_s = readNullableNumber(raw, 'simulation_time_s', errors, 'job')
  const group_id = readNullableString(raw, 'group_id', errors, 'job')
  const voxel_count = readNullableNonNegativeInt(raw, 'voxel_count', errors, 'job')
  const mask_source = readNullableString(raw, 'mask_source', errors, 'job')
  const revision = readNullableNonNegativeInt(raw, 'revision', errors, 'job')
  const zip_sha256 = readString(raw, 'zip_sha256', errors, 'job')
  const zip_byte_size = readNullableNonNegativeInt(raw, 'zip_byte_size', errors, 'job')
  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      job_id, run_id, status, source, received_at, started_at, finished_at, error,
      simulation_time_s, group_id, voxel_count, mask_source, revision, zip_sha256, zip_byte_size: zip_byte_size ?? 0,
    },
  }
}

export function validateReconstructionFrame(raw: unknown): Validation<BackendReconstructionFrame> {
  const errors: string[] = []
  if (!isRecord(raw)) return { ok: false, errors: ['reconstruction frame 不是对象'] }
  const revision = readNullableNonNegativeInt(raw, 'revision', errors, 'frame')
  const group_id = readString(raw, 'group_id', errors, 'frame')
  const simulation_time_s = readNullableNumber(raw, 'simulation_time_s', errors, 'frame')
  const source = readString(raw, 'source', errors, 'frame')
  const mask_source = readNullableString(raw, 'mask_source', errors, 'frame')
  const voxel_count = readNullableNonNegativeInt(raw, 'voxel_count', errors, 'frame')
  const voxel_size_m = readNullableNumber(raw, 'voxel_size_m', errors, 'frame')
  const byte_size = readNullableNonNegativeInt(raw, 'byte_size', errors, 'frame')
  const ply_sha256 = readString(raw, 'ply_sha256', errors, 'frame')
  const glb_sha256 = readNullableString(raw, 'glb_sha256', errors, 'frame')
  const produced_at = readString(raw, 'produced_at', errors, 'frame')
  if (revision === null || simulation_time_s === null || voxel_count === null || voxel_size_m === null || byte_size === null) {
    errors.push('reconstruction frame 缺少必填字段')
  }
  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      revision: revision!, group_id, simulation_time_s: simulation_time_s!, source, mask_source,
      voxel_count: voxel_count!, voxel_size_m: voxel_size_m!, byte_size: byte_size!,
      ply_sha256, glb_sha256, produced_at,
    },
  }
}

export function validateReconstructionFrames(raw: unknown): Validation<BackendReconstructionFrame[]> {
  if (!Array.isArray(raw)) return { ok: false, errors: ['reconstruction frames 必须为数组'] }
  const errors: string[] = []
  const frames: BackendReconstructionFrame[] = []
  for (let i = 0; i < raw.length; i++) {
    const r = validateReconstructionFrame(raw[i])
    if (!r.ok) { errors.push(`frames[${i}]：${r.errors.join('；')}`); continue }
    frames.push(r.value)
  }
  if (errors.length) return { ok: false, errors }
  return { ok: true, value: frames }
}

/** Immutable binding fields that a snapshot must share with its run record. */
export function validateSnapshotAgainstRun(run: BackendRunRecord, snapshot: BackendRunState): string | null {
  if (snapshot.run_id !== run.run_id) return `快照 run_id ${snapshot.run_id} 与运行 ${run.run_id} 不符`
  if (snapshot.plant_id !== run.plant_id) return `快照 plant_id ${snapshot.plant_id} 与运行 ${run.plant_id} 不符`
  if (snapshot.scene_id !== run.scene_id) return `快照 scene_id ${snapshot.scene_id} 与运行 ${run.scene_id} 不符`
  if (snapshot.asset_version !== run.asset_version) return `快照 asset_version ${snapshot.asset_version} 与运行 ${run.asset_version} 不符`
  if (snapshot.coordinate_frame_id !== run.coordinate_frame_id) return `快照坐标参考系 ${snapshot.coordinate_frame_id ?? '缺失'} 与运行 ${run.coordinate_frame_id ?? '缺失'} 不符`
  if (snapshot.input_source !== run.input_source) return `快照 input_source ${snapshot.input_source} 与运行 ${run.input_source} 不符`
  if (snapshot.simulation_time_origin_s !== run.simulation_time_origin_s) return '快照仿真时间原点与运行不符'
  if (snapshot.time_origin_utc !== run.time_origin_utc) return '快照 UTC 时间原点与运行不符'
  return null
}

export type RevisionDecision = 'accept' | 'duplicate' | 'regression'

/** Only a strictly newer revision is accepted; duplicate/regression never overwrite. */
export function revisionDecision(current: number, next: number): RevisionDecision {
  if (next > current) return 'accept'
  if (next === current) return 'duplicate'
  return 'regression'
}

// ---- Snapshot -> active fire patches (with scene-binding validation) ----

export interface SceneBinding {
  plant_id: string
  scene_id: string
  asset_version: string
  coordinate_frame_id: string | null
}

export interface PatchMapping {
  patches: ActiveFirePatch[]
  bindingError: string | null
}

const FIXTURE_LEVEL = 'warning' as const
const FIXTURE_INTENSITY = 0.6

/**
 * Map a backend snapshot to viewer fire patches, but only when the run binds to
 * the current scene. A binding mismatch is reported (never drawn on the wrong
 * scene). An observation also requires an explicit, matching coordinate frame;
 * a missing frame is NOT treated as a match. No fire severity is invented:
 * fixture patches use a fixed display level/intensity.
 */
export function snapshotToActiveFirePatches(snapshot: BackendRunState, binding: SceneBinding): PatchMapping {
  if (snapshot.plant_id !== binding.plant_id || snapshot.scene_id !== binding.scene_id || snapshot.asset_version !== binding.asset_version) {
    return {
      patches: [],
      bindingError: `运行绑定 ${snapshot.plant_id}/${snapshot.scene_id}/${snapshot.asset_version} 与当前场景 ${binding.plant_id}/${binding.scene_id}/${binding.asset_version} 不符，拒绝绘制轮廓`,
    }
  }
  if (snapshot.state_status !== 'observation') {
    return { patches: [], bindingError: null }
  }
  if (!binding.coordinate_frame_id || !snapshot.coordinate_frame_id || binding.coordinate_frame_id !== snapshot.coordinate_frame_id) {
    return {
      patches: [],
      bindingError: `观测火区需明确且匹配的坐标系：运行 ${snapshot.coordinate_frame_id ?? '缺失'} vs 场景 ${binding.coordinate_frame_id ?? '缺失'}`,
    }
  }
  if (snapshot.patches.length === 0) {
    return { patches: [], bindingError: null }
  }
  const patches: ActiveFirePatch[] = snapshot.patches.map((p) => ({
    patch_id: p.patch_id,
    level: FIXTURE_LEVEL,
    intensity: FIXTURE_INTENSITY,
    rings: [{ ring_xz: p.geometry.map(([x, z]) => [x, z] as [number, number]), ground_offset_m: 0.5 }],
  }))
  return { patches, bindingError: null }
}
