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
  if (!p) return '场景尚未加载，无法核对绑定。'
  if (s.scene_id !== p.scene_id) return `场景 ID 不匹配：结果「${s.scene_id}」≠ 当前「${p.scene_id}」。`
  if (s.asset_version !== p.asset_version) return `资产版本不匹配：结果「${s.asset_version}」≠ 当前「${p.asset_version}」。`
  if (s.coordinate_frame_id !== p.coordinate_frame_id) return `坐标系 ID 不匹配：结果「${s.coordinate_frame_id}」≠ 当前「${p.coordinate_frame_id}」。`
  for (const g of s.groups) {
    if (g.glb_sha256 && g.glb_sha256 !== p.asset.sha256) return `分组 ${g.group_id} 的 GLB SHA 与当前模型不一致。`
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
    if (!jsonFile) throw new Error('未选择 summary.json。')
    const s = parseMultiviewSummary(await jsonFile.text())
    const bindIssue = bindingError(s)
    if (bindIssue) throw new Error(bindIssue)
    const plyByName = new Map<string, Float32Array>()
    for (const f of plyFiles) {
      const gid = plyGroupId(f.name)
      if (!gid) throw new Error(`无法识别 PLY 对应的分组：${f.name}。`)
      const ply = parseVoxelPly(await f.arrayBuffer())
      for (let i = 0; i < ply.xyz.length; i++) {
        if (!Number.isFinite(ply.xyz[i]!)) throw new Error(`PLY ${f.name} 含无效坐标。`)
      }
      plyByName.set(gid, ply.xyz)
    }
    const merged: LoadedGroup[] = s.groups.map((g) => {
      const xyz = plyByName.get(g.group_id)
      if (!xyz) throw new Error(`分组 ${g.group_id} 缺少对应的 *-voxels.ply。`)
      if (xyz.length / 3 !== g.candidate_voxel_count) {
        throw new Error(`分组 ${g.group_id} 的 PLY 点数 ${xyz.length / 3} 与摘要 ${g.candidate_voxel_count} 不一致。`)
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
  <section class="replay-panel" aria-label="多视角重建回放">
    <h3><Box :size="17" />多视角重建回放</h3>
    <p class="small muted">导入离线重建的 summary.json 与对应 *-voxels.ply，在原模型上叠加候选体素。</p>
    <label class="replay-import">
      <input type="file" multiple accept=".json,.ply" :disabled="!profile || disabled" @change="onImport" />
      <span>{{ disabled ? '跟随服务端期间不可导入' : profile ? '选择 summary.json 与 *-voxels.ply' : '场景加载后可选文件' }}</span>
    </label>
    <p v-if="error" class="small replay-error" role="alert">{{ error }}</p>
    <template v-if="active && currentGroup">
      <div class="replay-badge"><span class="tag amber">离线重建回放 · 候选体素</span></div>
      <div class="replay-info">
        仿真时间 <strong>{{ currentGroup.simulation_time_s }} s</strong> ·
        重建机位 <strong>{{ currentGroup.source_camera_count }}</strong> ·
        候选体素 <strong>{{ currentGroup.candidate_voxel_count.toLocaleString() }}</strong>
      </div>
      <div class="replay-controls">
        <button
          v-for="(g, i) in groups"
          :key="g.group_id"
          type="button"
          :class="{ active: i === currentIndex }"
          @click="select(i)"
        >{{ g.simulation_time_s }} s</button>
        <button type="button" class="exit" @click="exit"><X :size="13" />退出回放</button>
      </div>
      <p class="small muted">回放期间隐藏实时单帧火焰图层；退出后恢复实时显示。体素为候选重建，精度未验收。</p>
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
