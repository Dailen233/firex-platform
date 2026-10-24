// Fetch layer over the backend contract. Re-exports every pure type/validator
// from backend-contract.ts and adds the HTTP calls + URL helpers.

export * from './backend-contract'
import {
  validateHealth,
  validateRunRecord,
  validateRunState,
  type BackendHealth,
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
export function runUrl(runId: string): string {
  return `${API_ORIGIN}/api/v1/runs/${encodeURIComponent(runId)}`
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
