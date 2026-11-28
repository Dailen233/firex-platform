<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { History, RefreshCw, Upload, X } from 'lucide-vue-next'
import { fetchReconstructionJob, uploadReconstructionZip, type BackendRunRecord } from '../lib/backend'
import type { SceneProfile } from '../lib/types'
import { useReconstructionFollow } from '../lib/multiview-follow'

const props = defineProps<{
  profile: SceneProfile | null
  runId: string | null
  run: BackendRunRecord | null
  disabled?: boolean
}>()
const emit = defineEmits<{ voxels: [points: Float32Array | null, voxelSizeM: number]; active: [active: boolean] }>()

const {
  active, summary, error, loading, displayedRevision, frames, pinnedRevision, hasNewer,
  bindingError, start, stop, refresh, pinRevision, backToLatest,
} = useReconstructionFollow({
  runId: () => props.runId,
  run: () => props.run,
  profile: () => props.profile,
  onVoxels: (points, voxelSizeM) => emit('voxels', points, voxelSizeM),
})

// 切换 run 后清理上一 run 的跟随与历史选择（迟到请求由 session 丢弃）。
watch(
  () => props.runId,
  () => {
    if (active.value) {
      stop()
      emit('active', false)
    }
    clearUpload()
  },
)

// 与本地回放互斥：当本地回放激活时自动停止跟随。
watch(
  () => props.disabled,
  (d) => {
    if (d && active.value) {
      stop()
      emit('active', false)
    }
  },
)

function toggle() {
  if (active.value) {
    stop()
    emit('active', false)
  } else {
    start()
    emit('active', true)
  }
}

// ---- 上传多机位采集包 ----
type UploadPhase = 'idle' | 'uploading' | 'queued' | 'processing' | 'completed' | 'failed'
const uploadPhase = ref<UploadPhase>('idle')
const uploadError = ref('')
const uploadedRevision = ref<number | null>(null)
const fileName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
let uploadSession = 0

const submitting = computed(() => ['uploading', 'queued', 'processing'].includes(uploadPhase.value))
// 任务已完成 与 图层已显示 分开提示：图层已显示 = 跟随已把该 revision 渲染出来。
const layerShown = computed(
  () => uploadPhase.value === 'completed' && uploadedRevision.value !== null && displayedRevision.value === uploadedRevision.value,
)

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function onFileChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许再次选择同一文件
  if (!file) return
  await submit(file)
}

async function submit(file: File) {
  if (submitting.value || props.disabled) return
  const bindErr = bindingError()
  if (bindErr) {
    uploadError.value = bindErr
    uploadPhase.value = 'failed'
    return
  }
  uploadPhase.value = 'uploading'
  uploadError.value = ''
  fileName.value = file.name
  uploadedRevision.value = null
  // 确保跟随开启（未开启则自动开启），这样重建完成后自动加载并显示新体素。
  if (!active.value) {
    start()
    emit('active', true)
  }
  const mySession = ++uploadSession
  try {
    const job = await uploadReconstructionZip(props.runId!, file)
    if (mySession !== uploadSession) return
    if (job.status === 'completed') {
      uploadPhase.value = 'completed'
      uploadedRevision.value = job.revision
      refresh()
      return
    }
    if (job.status === 'failed') {
      uploadPhase.value = 'failed'
      uploadError.value = '三维结果生成失败，请检查拍摄文件包后重试。'
      return
    }
    uploadPhase.value = job.status
    await pollJob(job.job_id, mySession)
  } catch {
    if (mySession !== uploadSession) return
    uploadPhase.value = 'failed'
    uploadError.value = '文件上传失败，请确认网络正常且文件包完整后重试。'
  }
}

async function pollJob(id: string, mySession: number) {
  while (mySession === uploadSession) {
    await sleep(1000)
    let job
    try {
      job = await fetchReconstructionJob(props.runId!, id)
    } catch {
      continue // 网络抖动，重试，保留上一帧
    }
    if (mySession !== uploadSession) return
    if (job.status === 'completed') {
      uploadPhase.value = 'completed'
      uploadedRevision.value = job.revision
      refresh() // 立即让跟随拉取新 revision，不等定时器
      return
    }
    if (job.status === 'failed') {
      uploadPhase.value = 'failed'
      uploadError.value = '三维结果生成失败，请稍后重试。'
      return
    }
    uploadPhase.value = job.status
  }
}

function clearUpload() {
  uploadSession += 1
  uploadPhase.value = 'idle'
  uploadError.value = ''
  uploadedRevision.value = null
  fileName.value = ''
}

onBeforeUnmount(() => {
  uploadSession += 1
})

// 当前实际显示的画面：固定历史帧时用该帧，否则用最新摘要。
const frame = computed(() => {
  if (pinnedRevision.value !== null) {
    const f = frames.value.find((x) => x.revision === pinnedRevision.value)
    if (f) {
      return {
        simulation_time_s: f.simulation_time_s,
        voxel_count: f.voxel_count,
        revision: f.revision,
        mask_source: f.mask_source,
      }
    }
  }
  const s = summary.value
  if (!s || s.status !== 'available') return null
  return {
    simulation_time_s: s.simulation_time_s,
    voxel_count: s.voxel_count ?? 0,
    revision: s.revision,
    mask_source: s.mask_source,
  }
})

// 掩膜来源按实际字段显示：独立掩膜（binary_png）不默认标「历史采集」。
const badge = computed(() =>
  frame.value?.mask_source === 'binary_png' ? '使用标注图' : '依据影像估算范围',
)

function onPin(revision: number) {
  void pinRevision(revision)
}
</script>

<template>
  <section class="follow-panel" aria-label="三维重建结果">
    <h3><RefreshCw :size="17" />实时重建结果</h3>
    <p class="small muted">连接监测任务后，页面会自动显示最新的三维重建结果。</p>
    <p v-if="!runId" class="small muted">请先连接监测任务，再查看重建结果。</p>
    <button v-else type="button" class="follow-toggle" :disabled="disabled" @click="toggle">
      {{ active ? '暂停更新' : '接收最新结果' }}
    </button>
    <p v-if="error" class="small follow-error" role="alert">{{ error }}</p>

    <div class="upload-block">
      <h4><Upload :size="15" />上传多角度拍摄文件</h4>
      <p class="small muted">每个压缩包对应一次拍摄，需包含原始图片、拍摄参数和对应的掩膜文件。</p>
      <p v-if="!runId" class="small muted">请先连接监测任务，再上传文件。</p>
      <template v-else>
        <label class="upload-file" :class="{ busy: submitting }">
          <input ref="fileInput" type="file" accept=".zip" :disabled="submitting || disabled" @change="onFileChosen" />
          <span class="upload-file-label">{{ fileName || '选择拍摄文件包' }}</span>
          <button v-if="fileName && !submitting" type="button" class="upload-clear" aria-label="清除" @click="clearUpload">
            <X :size="13" />
          </button>
        </label>
        <div class="upload-status" role="status">
          <span v-if="uploadPhase === 'uploading'" class="muted">上传中…</span>
          <span v-else-if="uploadPhase === 'queued'" class="muted">文件已收到，准备处理…</span>
          <span v-else-if="uploadPhase === 'processing'" class="muted">正在生成三维结果…</span>
          <span v-else-if="uploadPhase === 'completed' && !layerShown" class="muted">结果已生成，正在加载…</span>
          <span v-else-if="uploadPhase === 'completed' && layerShown" class="done">三维重建结果已显示。</span>
          <span v-else-if="uploadPhase === 'failed'" class="upload-error" role="alert">{{ uploadError }}</span>
        </div>
      </template>
    </div>

    <div v-if="runId && frames.length" class="history-block">
      <h4><History :size="15" />历史结果</h4>
      <div class="history-list">
        <button
          v-for="f in frames"
          :key="f.revision"
          type="button"
          class="history-item"
          :class="{ selected: pinnedRevision === f.revision }"
          @click="onPin(f.revision)"
        >
          {{ f.simulation_time_s }} 秒 · {{ f.voxel_count.toLocaleString() }} 个点
        </button>
      </div>
      <div v-if="pinnedRevision !== null" class="history-pinned">
        <span class="muted">正在查看第 {{ pinnedRevision }} 批结果</span>
        <button type="button" class="history-back" @click="backToLatest">查看最新结果</button>
      </div>
      <div v-if="hasNewer" class="history-newer" role="status">已收到更新结果，点击「查看最新结果」切换。</div>
    </div>

    <template v-if="active && frame">
      <div class="follow-badge"><span class="tag amber">{{ badge }}</span></div>
      <div class="follow-info">
        影像时间 <strong>{{ frame.simulation_time_s }} 秒</strong> ·
        三维点数 <strong>{{ frame.voxel_count.toLocaleString() }}</strong> ·
        结果批次 <strong>{{ frame.revision }}</strong>
      </div>
      <p class="small muted">此结果为三维预览，尚未完成精度核验。</p>
    </template>
    <p v-if="active && !frame && loading" class="small muted">正在读取最新重建帧…</p>
  </section>
</template>

<style scoped>
.follow-panel{background:#112233;border:1px solid #2a4959;border-radius:8px;padding:14px;margin:12px 0}
.follow-panel h3{display:flex;align-items:center;gap:8px;margin-bottom:11px;color:#edf7fd}
.follow-panel h3 svg{color:#7fd7c4}
.follow-toggle{font-size:.78rem;padding:6px 10px;color:#cfe3ee;background:#17303c;border:1px solid #3a5a6b;border-radius:5px;cursor:pointer}
.follow-toggle:disabled{opacity:.5;cursor:not-allowed}
.follow-error{color:#ffd29b;margin:7px 0}
.follow-badge{margin:9px 0 6px}
.follow-info{font-size:.78rem;color:#cfe3ee;font-variant-numeric:tabular-nums;margin-bottom:8px}
.follow-info strong{color:#ffcf9e}
.upload-block{margin-top:12px;padding-top:11px;border-top:1px dashed #2a4959}
.upload-block h4{display:flex;align-items:center;gap:7px;margin:0 0 6px;color:#cfe3ee;font-size:.85rem}
.upload-block h4 svg{color:#7fd7c4}
.upload-file{display:flex;align-items:center;gap:8px;margin:8px 0 6px}
.upload-file input[type="file"]{color:#cfe3ee;font-size:.75rem;max-width:100%}
.upload-file input[type="file"]:disabled{opacity:.5}
.upload-file.busy{opacity:.6}
.upload-file-label{font-size:.75rem;color:#cfe3ee}
.upload-clear{background:none;border:none;color:#ffd29b;cursor:pointer;padding:0;display:inline-flex}
.upload-status{font-size:.78rem;min-height:1.1em}
.upload-status .muted{color:#8fb0c2}
.upload-status .done{color:#8fe3c0}
.upload-error{color:#ffb1a3}
.history-block{margin-top:12px;padding-top:11px;border-top:1px dashed #2a4959}
.history-block h4{display:flex;align-items:center;gap:7px;margin:0 0 6px;color:#cfe3ee;font-size:.85rem}
.history-block h4 svg{color:#7fd7c4}
.history-list{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.history-item{font-size:.74rem;padding:4px 8px;color:#cfe3ee;background:#17303c;border:1px solid #3a5a6b;border-radius:4px;cursor:pointer;font-variant-numeric:tabular-nums}
.history-item:hover{border-color:#5a8aa0}
.history-item.selected{border-color:#7fd7c4;color:#bff0e3;background:#143a40}
.history-pinned{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:6px 0}
.history-back{font-size:.74rem;padding:4px 10px;color:#0e1a20;background:#7fd7c4;border:none;border-radius:4px;cursor:pointer}
.history-back:hover{background:#9ce5d4}
.history-newer{font-size:.76rem;color:#ffd29b;margin:6px 0}
</style>
