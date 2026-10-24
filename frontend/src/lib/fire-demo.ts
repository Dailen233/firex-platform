import { computed, shallowRef, watchEffect } from 'vue'
import type { ActiveFirePatch, DemoStatus, FireStateDemo } from './types'
import { validateFireStateDemo, resolveActivePatches } from './fire-demo-schema'
import { assetUrl, readJson } from './data'

// 演示状态单例：唯一时钟（模块级，页面不得自行计时）、visibilitychange 冻结、
// activeFirePatches 仅在解析结果真正变化时替换（避免每帧重建覆盖层）。

export type DemoDataState = 'unloaded' | 'loading' | 'ready' | 'unavailable'

// R3 收尾：合成火情演示覆盖层回归未通过（用户实测播放超 50 秒仍未出现火区，原因未定位）。
// 本轮暂停演示入口（play 为 no-op，时钟不启动、覆盖层与派生演示告警保持清空），
// 不修复其渲染、不扩展火势算法；保留契约、校验与叠加能力供未来复用，不改写电厂真实监测字段。
export const FIRE_DEMO_DISABLED = true

function signatureOf(patches: ActiveFirePatch[]): string {
  return patches.map(p => `${p.patch_id}:${p.level}:${p.intensity.toFixed(3)}`).sort().join(';')
}

let store: ReturnType<typeof createStore> | null = null

function createStore() {
  const status = shallowRef<DemoStatus>('off')
  const t_s = shallowRef(0)
  const demo = shallowRef<FireStateDemo | null>(null)
  const dataState = shallowRef<DemoDataState>('unloaded')
  const loadError = shallowRef('')
  const activeFirePatches = shallowRef<ActiveFirePatch[]>([])

  // ---- 唯一时钟 ----
  let rafId = 0
  let lastNow = 0
  const tick = (now: number) => {
    if (status.value !== 'playing') { rafId = 0; return }
    const deltaS = Math.max(0, (now - lastNow) / 1000)
    lastNow = now
    const next = t_s.value + deltaS
    if (demo.value && next >= demo.value.duration_s) {
      t_s.value = demo.value.duration_s
      status.value = 'ended'
      rafId = 0
      return
    }
    t_s.value = next
    rafId = requestAnimationFrame(tick)
  }
  function startClock() {
    if (rafId) return
    lastNow = performance.now()
    rafId = requestAnimationFrame(tick)
  }
  function stopClock() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  }
  // 后台显式冻结时间；恢复时重置计时基准，前台按实际经过时间推进（限制到 duration_s）。
  const onVisibility = () => {
    if (document.visibilityState === 'hidden') {
      stopClock()
    } else if (status.value === 'playing') {
      lastNow = performance.now()
      startClock()
    }
  }
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)

  // ---- 派生：仅在 active 集合/等级/强度真正变化时替换 ----
  let lastSig = ''
  watchEffect(() => {
    if (status.value === 'off' || !demo.value) {
      if (lastSig !== '') { lastSig = ''; activeFirePatches.value = [] }
      return
    }
    const resolved = resolveActivePatches(demo.value, t_s.value)
    const sig = signatureOf(resolved)
    if (sig !== lastSig) { lastSig = sig; activeFirePatches.value = resolved }
  })

  // ---- 动作 ----
  function play() {
    if (FIRE_DEMO_DISABLED) return // 演示入口已暂停（见顶部注释）
    if (dataState.value !== 'ready' || !demo.value) return
    if (status.value === 'ended') return // ended 后播放无效，需先 reset
    if (status.value === 'off') t_s.value = 0
    status.value = 'playing'
    lastNow = performance.now()
    startClock()
  }
  function pause() {
    if (status.value !== 'playing') return
    status.value = 'paused'
    stopClock()
  }
  function reset() {
    stopClock()
    t_s.value = 0
    status.value = 'paused'
  }
  function close() {
    stopClock()
    t_s.value = 0
    status.value = 'off'
  }

  async function load() {
    if (dataState.value === 'ready' || dataState.value === 'loading') return
    dataState.value = 'loading'
    try {
      const raw = await readJson<unknown>(assetUrl('data/fire_state_demo.json'))
      const result = validateFireStateDemo(raw)
      if (!result.ok) {
        // 严格校验：任一非法即拒绝整份，停止播放并清空旧演示。
        close()
        demo.value = null
        loadError.value = result.errors.join('；')
        dataState.value = 'unavailable'
        return
      }
      demo.value = result.demo
      loadError.value = ''
      dataState.value = 'ready'
    } catch (e) {
      close()
      demo.value = null
      loadError.value = e instanceof Error ? e.message : '演示数据读取失败'
      dataState.value = 'unavailable'
    }
  }

  const activePatchIds = computed(() => activeFirePatches.value.map(p => p.patch_id))
  const isDemoOn = computed(() => status.value !== 'off')
  const playing = computed(() => status.value === 'playing')
  const demoOnNoFire = computed(() => isDemoOn.value && activeFirePatches.value.length === 0)

  return {
    status,
    t_s,
    dataState,
    loadError,
    demo,
    activeFirePatches,
    activePatchIds,
    isDemoOn,
    playing,
    demoOnNoFire,
    demoDisabled: FIRE_DEMO_DISABLED,
    play,
    pause,
    reset,
    close,
    load,
  }
}

export function useFireDemo() {
  if (!store) store = createStore()
  return store
}
