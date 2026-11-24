// 跟随服务端重建结果 + 历史帧回看。
//
// 跟随模式（pinnedRevision === null）：轮询最新摘要，仅在新 revision 时下载 PLY，
// 通过绑定、SHA-256 与点数校验后才替换体素图层；失败保留最近有效帧。
// 固定模式（pinnedRevision !== null）：固定显示某一历史帧，服务端出新帧时只提示
// 「有新结果」，保持当前画面；「回到最新」才恢复跟随。
import { onBeforeUnmount, ref, shallowRef } from 'vue'
import {
  fetchReconstructionFrames,
  fetchReconstructionPly,
  fetchReconstructionSummary,
  type BackendReconstructionFrame,
  type BackendReconstructionSummary,
  type BackendRunRecord,
} from './backend'
import { parseVoxelPly } from './multiview-replay'
import type { SceneProfile } from './types'

const POLL_INTERVAL_MS = 2000

async function sha256hex(buf: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

export function useReconstructionFollow(opts: {
  runId: () => string | null
  run: () => BackendRunRecord | null
  profile: () => SceneProfile | null
  onVoxels: (points: Float32Array | null, voxelSizeM: number) => void
}) {
  const active = shallowRef(false)
  const summary = shallowRef<BackendReconstructionSummary | null>(null)
  const error = ref('')
  const loading = ref(false)
  const displayedRevision = shallowRef<number | null>(null)
  const frames = shallowRef<BackendReconstructionFrame[]>([])
  const pinnedRevision = shallowRef<number | null>(null)
  const hasNewer = ref(false)

  let session = 0
  let timer: number | null = null
  let inFlight: AbortController | null = null
  let pinInFlight: AbortController | null = null
  let lastRevision = -1

  // 上传前/显示前的绑定校验（不依赖摘要）。
  function bindingError(): string | null {
    const run = opts.run()
    const p = opts.profile()
    if (!run || !p) return '场景或监测任务尚未准备好，请稍后重试。'
    if (run.scene_id !== p.scene_id || run.asset_version !== p.asset_version) return '这份三维结果与当前场站不匹配，请选择对应场站的结果。'
    if (run.coordinate_frame_id !== p.coordinate_frame_id) return '结果的位置参考与当前场景不一致，暂时无法显示。'
    return null
  }

  function summaryBindingError(s: BackendReconstructionSummary): string | null {
    const base = bindingError()
    if (base) return base
    if (s.glb_sha256 && s.glb_sha256 !== opts.profile()!.asset.sha256) {
      return '这份三维结果与当前场站不匹配，已保留原画面。'
    }
    return null
  }

  function frameBindingError(f: BackendReconstructionFrame): string | null {
    const base = bindingError()
    if (base) return base
    if (f.glb_sha256 && f.glb_sha256 !== opts.profile()!.asset.sha256) {
      return '这条历史结果与当前场站不匹配，暂时无法显示。'
    }
    return null
  }

  async function refreshFrames(): Promise<void> {
    const id = opts.runId()
    const mySession = session
    if (!id) return
    try {
      const list = await fetchReconstructionFrames(id)
      if (mySession !== session) return
      frames.value = list
    } catch {
      // 历史列表加载失败不影响跟随
    }
  }

  async function poll(): Promise<void> {
    const id = opts.runId()
    const mySession = session
    if (!id) return
    const controller = new AbortController()
    inFlight = controller
    void refreshFrames()
    try {
      const s = await fetchReconstructionSummary(id, controller.signal)
      if (mySession !== session) return // 迟到响应丢弃
      summary.value = s
      if (s.status === 'none') {
        error.value = '暂无重建结果。'
        frames.value = []
        pinnedRevision.value = null
        hasNewer.value = false
        return
      }
      const bindErr = summaryBindingError(s)
      if (bindErr) {
        error.value = bindErr
        return // 保留最近有效帧
      }

      // 固定显示模式：只检测是否有新结果，保持当前画面。
      if (pinnedRevision.value !== null) {
        hasNewer.value = (s.revision ?? 0) > pinnedRevision.value
        error.value = ''
        return
      }

      // 跟随最新模式：仅新 revision 才下载 PLY。
      if (s.revision === lastRevision) {
        error.value = '' // 重复 revision：不重复下载 PLY
        return
      }
      if (s.revision! < lastRevision) {
        error.value = '收到较早的结果，已保留最近一次有效画面。'
        return
      }
      loading.value = true
      const buf = await fetchReconstructionPly(id, s.revision!, controller.signal)
      if (mySession !== session) return
      const sha = await sha256hex(buf)
      if (sha !== s.ply_sha256) {
        error.value = '三维结果文件校验未通过，已保留最近一次有效画面。'
        return
      }
      const ply = parseVoxelPly(buf)
      if (ply.vertex_count !== s.voxel_count) {
        error.value = '三维结果信息不一致，已保留最近一次有效画面。'
        return
      }
      lastRevision = s.revision!
      displayedRevision.value = s.revision!
      opts.onVoxels(ply.xyz, s.voxel_size_m ?? 4)
      error.value = ''
    } catch {
      if (mySession !== session) return
      error.value = '暂时无法读取最新三维结果，已保留最近一次有效画面。'
    } finally {
      if (inFlight === controller) {
        inFlight = null
        loading.value = false
      }
    }
  }

  // 固定显示某一历史帧（复用 PLY 校验与体素图层）。
  async function pinRevision(revision: number): Promise<void> {
    const id = opts.runId()
    if (!id) return
    const frame = frames.value.find((f) => f.revision === revision)
    if (!frame) {
      error.value = '这条历史结果暂时不可用。'
      return
    }
    const bindErr = frameBindingError(frame)
    if (bindErr) {
      error.value = bindErr
      return
    }
    pinnedRevision.value = revision
    hasNewer.value = false
    const mySession = session
    const controller = new AbortController()
    pinInFlight = controller
    loading.value = true
    try {
      const buf = await fetchReconstructionPly(id, revision, controller.signal)
      if (mySession !== session) return
      const sha = await sha256hex(buf)
      if (sha !== frame.ply_sha256) {
        error.value = '历史结果文件校验未通过，已保留当前画面。'
        return
      }
      const ply = parseVoxelPly(buf)
      if (ply.vertex_count !== frame.voxel_count) {
        error.value = '历史结果信息不一致，已保留当前画面。'
        return
      }
      displayedRevision.value = revision
      opts.onVoxels(ply.xyz, frame.voxel_size_m)
      error.value = ''
    } catch {
      if (mySession !== session) return
      error.value = '暂时无法加载这条历史结果，请稍后重试。'
    } finally {
      if (pinInFlight === controller) {
        pinInFlight = null
        loading.value = false
      }
    }
  }

  // 回到最新结果，恢复跟随。
  function backToLatest(): void {
    pinnedRevision.value = null
    hasNewer.value = false
    lastRevision = -1
    if (active.value) void poll()
  }

  function start(): void {
    session += 1
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    if (inFlight) {
      inFlight.abort()
      inFlight = null
    }
    if (pinInFlight) {
      pinInFlight.abort()
      pinInFlight = null
    }
    lastRevision = -1
    summary.value = null
    displayedRevision.value = null
    frames.value = []
    pinnedRevision.value = null
    hasNewer.value = false
    error.value = ''
    loading.value = false
    active.value = true
    void poll()
    timer = window.setInterval(() => {
      if (!inFlight) void poll()
    }, POLL_INTERVAL_MS)
  }

  function stop(): void {
    session += 1
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    if (inFlight) {
      inFlight.abort()
      inFlight = null
    }
    if (pinInFlight) {
      pinInFlight.abort()
      pinInFlight = null
    }
    loading.value = false
    active.value = false
    summary.value = null
    displayedRevision.value = null
    frames.value = []
    pinnedRevision.value = null
    hasNewer.value = false
    error.value = ''
    lastRevision = -1
    opts.onVoxels(null, 0)
  }

  // 立即触发一次轮询（上传任务完成时用，不等定时器）。
  function refresh(): void {
    if (active.value && !inFlight) void poll()
  }

  onBeforeUnmount(stop)

  return {
    active, summary, error, loading, displayedRevision, frames, pinnedRevision, hasNewer,
    bindingError, start, stop, refresh, pinRevision, backToLatest,
  }
}
