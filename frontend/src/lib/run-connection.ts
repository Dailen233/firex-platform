import { computed, shallowRef } from 'vue'
import {
  fetchHealth,
  fetchRun,
  fetchRunState,
  validateSnapshotAgainstRun,
  revisionDecision,
  type BackendHealth,
  type BackendRunRecord,
  type BackendRunState,
} from './backend'

// Shared connection state + a single poller. Components must not create their
// own pollers; the connection survives page navigation (map -> detail -> scene).
// The poller is serial (skips a tick while a request is in flight), has a
// timeout, and every response is checked against the current session/run id and
// the run's immutable binding so a stale or mismatched response can never
// pollute a new connection.

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export const POLL_INTERVAL_MS = 1000

function errorText(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

function createStore() {
  const status = shallowRef<ConnectionStatus>('disconnected')
  const runId = shallowRef('')
  const health = shallowRef<BackendHealth | null>(null)
  const run = shallowRef<BackendRunRecord | null>(null)
  const snapshot = shallowRef<BackendRunState | null>(null)
  const error = shallowRef('')
  const lastSuccessfulQueryAt = shallowRef<number | null>(null)
  const lastNewRevisionAt = shallowRef<number | null>(null)

  let session = 0
  let timer: number | null = null
  let inFlight: AbortController | null = null
  let connectAbort: AbortController | null = null
  let lastRevision = -1

  async function poll(): Promise<void> {
    const id = runId.value
    if (!id) return
    const mySession = session
    const controller = new AbortController()
    inFlight = controller
    try {
      const state = await fetchRunState(id, controller.signal)
      if (mySession !== session) return // stale response for a previous connection
      // The snapshot must belong to the connected run and share its immutable binding.
      const bindErr = run.value ? validateSnapshotAgainstRun(run.value, state) : null
      if (bindErr) throw new Error(bindErr)
      const decision = revisionDecision(lastRevision, state.revision)
      if (decision === 'regression') {
        // A backward revision must never overwrite the newer valid result.
        error.value = `收到旧 revision ${state.revision}（当前 ${lastRevision}），已忽略并保留最近有效结果`
        return // do not refresh lastSuccessfulQueryAt / snapshot / new-revision time
      }
      error.value = ''
      if (status.value !== 'connected') status.value = 'connected'
      lastSuccessfulQueryAt.value = Date.now()
      if (decision === 'accept') {
        lastRevision = state.revision
        lastNewRevisionAt.value = Date.now()
        snapshot.value = state
      }
      // decision === 'duplicate': no-op (no geometry rebuild, no new-observation time)
    } catch (e) {
      if (mySession !== session) return
      // Network/invalid response: keep the last valid snapshot of the same run.
      const keep = snapshot.value !== null ? '连接异常（沿用最近有效结果）' : '连接异常，尚未取得有效结果'
      error.value = `${keep}：${errorText(e)}`
      if (snapshot.value === null) status.value = 'error'
      // lastSuccessfulQueryAt is intentionally not refreshed on failure.
    } finally {
      if (inFlight === controller) inFlight = null
    }
  }

  function tick(): void {
    if (inFlight) return // serial: never overlap a request still in flight
    void poll()
  }

  function startPoller(): void {
    if (timer !== null) return
    void poll() // immediate first poll
    timer = window.setInterval(tick, POLL_INTERVAL_MS)
  }

  function stopPoller(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    if (inFlight) {
      inFlight.abort()
      inFlight = null
    }
  }

  async function connect(id: string): Promise<void> {
    const trimmed = id.trim()
    if (!trimmed) {
      status.value = 'error'
      error.value = '请输入 run_id'
      return
    }
    stopPoller() // cancel any in-flight poll
    session += 1
    const mySession = session
    connectAbort?.abort() // cancel any connect-phase request still in flight
    const controller = new AbortController()
    connectAbort = controller
    runId.value = trimmed
    status.value = 'connecting'
    error.value = ''
    health.value = null
    run.value = null
    snapshot.value = null
    lastSuccessfulQueryAt.value = null
    lastNewRevisionAt.value = null
    lastRevision = -1
    try {
      const h = await fetchHealth(controller.signal)
      if (h.service !== 'firex-backend') throw new Error(`目标服务不是 firex-backend（service=${h.service}）`)
      const r = await fetchRun(trimmed, controller.signal)
      if (mySession !== session) return // disconnected / reconnected during connect
      health.value = h
      run.value = r
      startPoller()
    } catch (e) {
      if (mySession !== session) return
      status.value = 'error'
      error.value = errorText(e)
    } finally {
      if (connectAbort === controller) connectAbort = null
    }
  }

  function disconnect(): void {
    session += 1
    connectAbort?.abort()
    connectAbort = null
    stopPoller()
    runId.value = ''
    status.value = 'disconnected'
    health.value = null
    run.value = null
    snapshot.value = null
    error.value = ''
    lastSuccessfulQueryAt.value = null
    lastNewRevisionAt.value = null
    lastRevision = -1
  }

  const isConnected = computed(() => status.value === 'connected')
  const observationTimeLabel = computed(() => {
    const s = snapshot.value
    if (!s || s.observation_time_s === null) return null
    const base = `${s.observation_time_s.toFixed(1)} s`
    return s.time_basis === 'utc_anchored' ? `${base}（相对 UTC 锚点）` : `${base}（相对仿真原点）`
  })

  return {
    status,
    runId,
    health,
    run,
    snapshot,
    error,
    lastSuccessfulQueryAt,
    lastNewRevisionAt,
    isConnected,
    observationTimeLabel,
    connect,
    disconnect,
  }
}

let store: ReturnType<typeof createStore> | null = null

export function useRunConnection() {
  if (!store) store = createStore()
  return store
}
