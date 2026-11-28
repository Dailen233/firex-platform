// Fetch layer over the backend contract. Re-exports every pure type/validator
// from backend-contract.ts and adds the HTTP calls + URL helpers.

export * from './backend-contract'
import {
  validateAtlasFireStatus,
  validateHealth,
  validateReconstructionFrames,
  validateReconstructionJob,
  validateReconstructionSummary,
  validateRunRecord,
  validateRunState,
  type AtlasFireStatus,
  type BackendHealth,
  type BackendReconstructionFrame,
  type BackendReconstructionJob,
  type BackendReconstructionSummary,
  type BackendRunCreate,
  type BackendRunRecord,
  type BackendRunState,
  type Validation,
} from './backend-contract'

/**
 * Backend origin. Empty by default so the frontend uses Vite's dev proxy
 * (relative /health and /api/...). Set VITE_FIREX_API_ORIGIN (e.g.
 * http://127.0.0.1:8002) to talk to the backend directly (absolute URLs).
 */
export const API_ORIGIN: string = ((import.meta.env as { VITE_FIREX_API_ORIGIN?: string } | undefined)?.VITE_FIREX_API_ORIGIN ?? '').replace(/\/+$/, '')
export const REQUEST_TIMEOUT_MS = 5000

export function healthUrl(): string {
  return `${API_ORIGIN}/health`
}
export function runsUrl(): string {
  return `${API_ORIGIN}/api/v1/runs`
}

export function runUrl(runId: string): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}`
}

export async function createRun(payload: BackendRunCreate, signal?: AbortSignal): Promise<BackendRunRecord> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  const res = await fetch(runsUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
    signal: combined,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.error?.message) detail = body.error.message
    } catch {
      /* keep HTTP status */
    }
    throw new Error(detail)
  }
  const raw = await res.json()
  return unwrap(validateRunRecord(raw), 'create run')
}
export function runStateUrl(runId: string): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}/state`
}

async function getJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  const res = await fetch(url, { signal: combined, headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

const PLY_TIMEOUT_MS = 30000

async function getBinary(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const timeout = AbortSignal.timeout(PLY_TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  const res = await fetch(url, { signal: combined, headers: { Accept: 'application/octet-stream' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.arrayBuffer()
}

function unwrap<T>(result: Validation<T>, what: string): T {
  if (!result.ok) throw new Error(`${what} 响应校验失败：${result.errors.join('；')}`)
  return result.value
}

export async function fetchHealth(signal?: AbortSignal): Promise<BackendHealth> {
  const raw = await getJson(healthUrl(), signal)
  return unwrap(validateHealth(raw), '/health')
}

export async function fetchRun(runId: string, signal?: AbortSignal): Promise<BackendRunRecord> {
  const raw = await getJson(runUrl(runId), signal)
  const value = unwrap(validateRunRecord(raw), 'run')
  if (value.run_id !== runId) throw new Error(`运行身份不符：请求 ${runId}，返回 ${value.run_id}`)
  return value
}

export async function fetchRunState(runId: string, signal?: AbortSignal): Promise<BackendRunState> {
  const raw = await getJson(runStateUrl(runId), signal)
  const value = unwrap(validateRunState(raw), 'run/state')
  if (value.run_id !== runId) throw new Error(`快照身份不符：请求 ${runId}，返回 ${value.run_id}`)
  return value
}

export function atlasFireStatusUrl(): string {
  return `${API_ORIGIN}/api/v1/atlas/fire-status`
}

export async function fetchAtlasFireStatus(signal?: AbortSignal): Promise<AtlasFireStatus> {
  const raw = await getJson(atlasFireStatusUrl(), signal)
  return unwrap(validateAtlasFireStatus(raw), 'atlas/fire-status')
}

export function reconstructionUrl(runId: string): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}/reconstruction`
}

export function reconstructionPlyUrl(runId: string, revision: number): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}/reconstruction/${revision}/ply`
}

export async function fetchReconstructionSummary(
  runId: string,
  signal?: AbortSignal,
): Promise<BackendReconstructionSummary> {
  const raw = await getJson(reconstructionUrl(runId), signal)
  const value = unwrap(validateReconstructionSummary(raw), 'reconstruction')
  if (value.run_id !== runId) throw new Error(`重建摘要身份不符：请求 ${runId}，返回 ${value.run_id}`)
  return value
}

export async function fetchReconstructionPly(
  runId: string,
  revision: number,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  return getBinary(reconstructionPlyUrl(runId, revision), signal)
}

export function reconstructionFramesUrl(runId: string): string {
  return `${reconstructionUrl(runId)}/frames`
}

export async function fetchReconstructionFrames(
  runId: string,
  signal?: AbortSignal,
): Promise<BackendReconstructionFrame[]> {
  const raw = await getJson(reconstructionFramesUrl(runId), signal)
  return unwrap(validateReconstructionFrames(raw), 'reconstruction frames')
}

export function reconstructionJobsUrl(runId: string): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}/reconstruction-jobs`
}

export function reconstructionJobUrl(runId: string, jobId: string): string {
  return `${reconstructionJobsUrl(runId)}/${encodeURIComponent(jobId)}`
}

export async function fetchReconstructionJob(
  runId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<BackendReconstructionJob> {
  const raw = await getJson(reconstructionJobUrl(runId, jobId), signal)
  const value = unwrap(validateReconstructionJob(raw), 'reconstruction job')
  if (value.run_id !== runId) throw new Error(`重建任务身份不符：请求 ${runId}，返回 ${value.run_id}`)
  return value
}

const UPLOAD_TIMEOUT_MS = 120000

export async function uploadReconstructionZip(
  runId: string,
  zip: Blob,
  signal?: AbortSignal,
): Promise<BackendReconstructionJob> {
  const timeout = AbortSignal.timeout(UPLOAD_TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  const form = new FormData()
  form.append('file', zip, 'capture.zip')
  const res = await fetch(reconstructionJobsUrl(runId), { method: 'POST', body: form, signal: combined })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const raw = await res.json()
  return unwrap(validateReconstructionJob(raw), 'reconstruction job')
}
