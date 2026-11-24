<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { Box, X } from 'lucide-vue-next'
import type { SceneProfile } from '../lib/types'
import {
  parseMultiviewSummary, parseVoxelPly, plyGroupId,
  type MultiviewReplayGroup, type MultiviewReplaySummary,
} from '../lib/multiview-replay'

const props = defineProps<{ profile: SceneProfile | null; disabled?: boolean }>()
const emit = defineEmits<{ voxels: [points: Float32Array | null, voxelSizeM: number]; active: [active: boolean] }>()

type LoadedGroup = MultiviewReplayGroup & { xyz: Float32Array }

const summary = shallowRef<MultiviewReplaySummary | null>(null)
const groups = shallowRef<LoadedGroup[]>([])
const currentIndex = ref(0)
const active = ref(false)
const error = ref('')

const currentGroup = computed(() => groups.value[currentIndex.value] ?? null)

function bindingError(s: MultiviewReplaySummary): string | null {
  const p = props.profile
  if (!p) return '场景尚未准备好，请稍后重试。'
  if (s.scene_id !== p.scene_id || s.asset_version !== p.asset_version) return '所选三维结果与当前场站不匹配，请选择对应场站的文件。'
  if (s.coordinate_frame_id !== p.coordinate_frame_id) return '所选三维结果的位置参考与当前场景不一致。'
  for (const g of s.groups) {
    if (g.glb_sha256 && g.glb_sha256 !== p.asset.sha256) return '所选三维结果与当前场站不匹配，请选择对应场站的文件。'
  }
  return null
}

async function onImport(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  error.value = ''
  try {
    const jsonFile = files.find((f) => f.name.toLowerCase().endsWith('.json'))
    const plyFiles = files.filter((f) => f.name.toLowerCase().endsWith('.ply'))
    if (!jsonFile) throw new Error('请同时选择重建说明文件和对应的点云文件。')
    const s = parseMultiviewSummary(await jsonFile.text())
    const bindIssue = bindingError(s)
    if (bindIssue) throw new Error(bindIssue)
    const plyByName = new Map<string, Float32Array>()
    for (const f of plyFiles) {
      const gid = plyGroupId(f.name)
      if (!gid) throw new Error('点云文件名称无法识别，请选择原始导出文件。')
      const ply = parseVoxelPly(await f.arrayBuffer())
      for (let i = 0; i < ply.xyz.length; i++) {
        if (!Number.isFinite(ply.xyz[i]!)) throw new Error('点云文件包含无效数据，请重新导出三维结果。')
      }
      plyByName.set(gid, ply.xyz)
    }
    const merged: LoadedGroup[] = s.groups.map((g) => {
      const xyz = plyByName.get(g.group_id)
      if (!xyz) throw new Error('缺少部分点云文件，请同时选择全部重建文件。')
      if (xyz.length / 3 !== g.candidate_voxel_count) {
        throw new Error('重建说明与点云内容不一致，请重新导出完整结果。')
      }
      return { ...g, xyz }
    })
    // 全部通过后再替换，导入失败时保留上次成功结果。
    summary.value = s
    groups.value = merged
    currentIndex.value = 0
    active.value = true
    emit('active', true)
    emit('voxels', merged[0]!.xyz, s.voxel_size_m)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导入失败。'
  }
}

function select(index: number) {
  currentIndex.value = index
  const g = groups.value[index]
  if (g) emit('voxels', g.xyz, summary.value?.voxel_size_m ?? 4)
}

function exit() {
  active.value = false
  emit('voxels', null, 0)
  emit('active', false)
  summary.value = null
  groups.value = []
  currentIndex.value = 0
}

// 与跟随服务端互斥：当跟随激活时自动退出本地回放。
watch(
  () => props.disabled,
  (d) => {
    if (d && active.value) exit()
  },
)
</script>

<template>
  <section class="replay-panel" aria-label="多角度三维重建预览">
    <h3><Box :size="17" />多角度重建预览</h3>
    <p class="small muted">加载多角度影像生成的三维结果，在场景中查看重建范围。当前结果仅供预览，精度尚未核验。</p>
    <label class="replay-import">
      <input type="file" multiple accept=".json,.ply" :disabled="!profile || disabled" @change="onImport" />
      <span>{{ disabled ? '正在显示最新结果，暂不能切换文件' : profile ? '选择重建说明文件和点云文件' : '场景准备好后可选择文件' }}</span>
    </label>
    <p v-if="error" class="small replay-error" role="alert">{{ error }}</p>
    <template v-if="active && currentGroup">
      <div class="replay-badge"><span class="tag amber">离线结果预览 · 精度待核验</span></div>
      <div class="replay-info">
        影像时间 <strong>{{ currentGroup.simulation_time_s }} 秒</strong> ·
        拍摄角度 <strong>{{ currentGroup.source_camera_count }}</strong> ·
        三维点数 <strong>{{ currentGroup.candidate_voxel_count.toLocaleString() }}</strong>
      </div>
      <div class="replay-controls">
        <button
          v-for="(g, i) in groups"
          :key="g.group_id"
          type="button"
          :class="{ active: i === currentIndex }"
          @click="select(i)"
        >{{ g.simulation_time_s }} s</button>
        <button type="button" class="exit" @click="exit"><X :size="13" />关闭预览</button>
      </div>
      <p class="small muted">预览期间暂不显示实时火情图层；关闭预览后恢复。三维结果还未完成精度核验。</p>
    </template>
  </section>
</template>

<style scoped>
.replay-panel{background:#112233;border:1px solid #2a4959;border-radius:8px;padding:14px;margin:12px 0}
.replay-panel h3{display:flex;align-items:center;gap:8px;margin-bottom:11px;color:#edf7fd}
.replay-panel h3 svg{color:#ffb86b}
.replay-import{display:block;margin:8px 0}
.replay-import input{position:absolute;width:1px;height:1px;opacity:0;overflow:hidden}
.replay-import span{display:inline-block;font-size:.75rem;color:#a2e5dc;border:1px solid #3f827a;background:#173b3e;padding:6px 9px;border-radius:5px;cursor:pointer}
.replay-import input:disabled + span{opacity:.5;cursor:not-allowed;color:#7f98a6;border-color:#35515d;background:#17262f}
.replay-error{color:#ffd29b;margin:7px 0}
.replay-badge{margin:9px 0 6px}
.replay-info{font-size:.78rem;color:#cfe3ee;font-variant-numeric:tabular-nums;margin-bottom:9px}
.replay-info strong{color:#ffcf9e}
.replay-controls{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.replay-controls button{font-size:.73rem;padding:5px 9px;color:#cfe3ee;background:#17303c;border:1px solid #3a5a6b;border-radius:5px;cursor:pointer}
.replay-controls button.active{color:#182027;background:#ffb86b;border-color:#ffb86b;font-weight:600}
.replay-controls button.exit{color:#ffd29b;border-color:#7a4b3a;background:#2d1d16}
</style>
