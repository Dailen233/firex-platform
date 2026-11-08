import { computed, shallowRef } from 'vue'
import {
  fetchAtlasFireStatus,
  type AtlasFireStatus,
  type AtlasFireStatusItem,
} from './backend'

// A1 全国地图火情反馈：唯一轮询器（页面不得自行计时）。进入首页开始、离开释放。
// 串行轮询（在途则跳过本 tick），超时由 backend.getJson 提供；后端断开时保留
// 最近有效结果并明确标出断开，不把旧结果当成新告警，也不刷新观测时间。

export const FIRE_STATUS_POLL_INTERVAL_MS = 4000

function errorText(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

function createStore() {
  const snapshot = shallowRef<AtlasFireStatus | null>(null)
  const connected = shallowRef(false) // 最近一次轮询是否成功
  const everConnected = shallowRef(false) // 是否曾成功（区分“未连接”与“断开后恢复”）
  const error = shallowRef('')
  const lastSuccessfulQueryAt = shallowRef<number | null>(null)

  let timer: number | null = null
  let inFlight: AbortController | null = null
  let started = false

  async function poll(): Promise<void> {
    const controller = new AbortController()
    inFlight = controller
    try {
      const result = await fetchAtlasFireStatus(controller.signal)
      snapshot.value = result
      error.value = ''
      connected.value = true
      everConnected.value = true
      lastSuccessfulQueryAt.value = Date.now()
    } catch (e) {
      // 网络/校验失败：保留最近有效结果，但明确标为断开。
      connected.value = false
      error.value = errorText(e)
    } finally {
      if (inFlight === controller) inFlight = null
    }
  }

  function tick(): void {
    if (inFlight) return // 串行：绝不让在途请求与下一个重叠
    void poll()
  }

  function start(): void {
    if (started) return
    started = true
    void poll()
    timer = window.setInterval(tick, FIRE_STATUS_POLL_INTERVAL_MS)
  }

  function stop(): void {
    started = false
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    if (inFlight) {
      inFlight.abort()
      inFlight = null
    }
  }

  const items = computed(() => snapshot.value?.items ?? [])
  const fireItems = computed(() => items.value.filter((i) => i.alert_status === 'fire'))
  const staleItems = computed(() => items.value.filter((i) => i.alert_status === 'stale'))
  const noDetectionItems = computed(() => items.value.filter((i) => i.alert_status === 'no_detection'))
  const itemsByPlantId = computed(() => new Map(items.value.map((i) => [i.plant_id, i])))

  return {
    snapshot,
    connected,
    everConnected,
    error,
    lastSuccessfulQueryAt,
    items,
    fireItems,
    staleItems,
    noDetectionItems,
    itemsByPlantId,
    start,
    stop,
  }
}

let store: ReturnType<typeof createStore> | null = null

export function useAtlasFireStatus() {
  if (!store) store = createStore()
  return store
}

export function observationTimeLabel(item: AtlasFireStatusItem): string {
  if (item.observation_time_s === null) return '—'
  const base = `${item.observation_time_s.toFixed(1)} s`
  return item.time_basis === 'utc_anchored' ? `${base}（相对 UTC 锚点）` : `${base}（相对仿真原点）`
}

// A2：来源标签。合成火情（YOLO 检测的仿真影像）标「数据来源：仿真」；fixture 标「数据来源：接口测试」。
export function originLabel(item: AtlasFireStatusItem): string {
  if (item.result_origin === 'yolo') return '数据来源：仿真'
  return '数据来源：接口测试'
}
