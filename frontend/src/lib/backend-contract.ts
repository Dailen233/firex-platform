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

export interface BackendFirePatch {
  patch_id: string
  /** Local XZ closed ring (X east, Z south, metres); Y is sampled by the viewer. */
  geometry: [number, number][]
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

  // Cross-field semantics for the two states (B3).
  if (state_status === 'observation') {
    if (observation_time_s === null) errors.push('observation 状态必须提供 observation_time_s')
    if (result_origin === null) errors.push('observation 状态必须提供 result_origin')
    if (provider_version === null) errors.push('observation 状态必须提供 provider_version')
    if (patches.length === 0) errors.push('observation 状态必须提供非空 patches')
  } else {
    if (revision !== 0) errors.push('no_observation 状态 revision 必须为 0')
    if (observation_time_s !== null) errors.push('no_observation 状态 observation_time_s 必须为 null')
    if (result_origin !== null) errors.push('no_observation 状态 result_origin 必须为 null')
    if (provider_version !== null) errors.push('no_observation 状态 provider_version 必须为 null')
    if (patches.length !== 0) errors.push('no_observation 状态 patches 必须为空')
  }

  if (errors.length) return { ok: false, errors }
  return {
    ok: true,
    value: {
      run_id, plant_id, scene_id, asset_version, coordinate_frame_id,
      input_source, schema_version, state_status, revision, observation_time_s,
      result_origin, provider_version, evidence_capture_ids, patches, produced_at,
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
