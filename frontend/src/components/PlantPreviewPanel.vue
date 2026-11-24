<script setup lang="ts">
import { ref } from 'vue'
import { Building2, Eye, EyeOff, Layers } from 'lucide-vue-next'
import type { SceneProfile } from '../lib/types'

defineProps<{ profile: SceneProfile | null }>()
const emit = defineEmits<{ toggle: [visible: boolean]; focus: [view: 'oblique' | 'top'] }>()

const previewVisible = ref(false)
function toggle() {
  previewVisible.value = !previewVisible.value
  emit('toggle', previewVisible.value)
}
</script>

<template>
  <section class="plant-preview-panel" aria-label="厂区布局参考">
    <div class="panel-eyebrow">厂区布局参考<Building2 :size="16" /></div>
    <p class="small muted">包含开关楼、副厂房和辅助用房等场景建筑，供查看相对布局；新增建筑仅作场景示意，位置和尺寸尚未实地核实。</p>
    <div class="preview-controls">
      <button class="primary-button" :disabled="!profile" @click="toggle">
        <Eye v-if="!previewVisible" :size="14" /><EyeOff v-else :size="14" />
        {{ previewVisible ? '恢复原场景' : '查看布局参考' }}
      </button>
      <button class="secondary-button" :disabled="!profile" @click="emit('focus', 'oblique')">斜视</button>
      <button class="secondary-button" :disabled="!profile" @click="emit('focus', 'top')">俯视</button>
    </div>
    <p v-if="previewVisible" class="preview-tag"><Layers :size="13" />公开资料布局参考 · 位置尚未校准</p>
  </section>
</template>

<style scoped>
.plant-preview-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin:12px 0;background:#122436}
.plant-preview-panel .panel-eyebrow{margin-bottom:10px}
.preview-controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}
.preview-controls .primary-button,.preview-controls .secondary-button{display:inline-flex;align-items:center;gap:5px}
.preview-tag{display:inline-flex;align-items:center;gap:5px;margin:9px 0 0;font-size:.78rem;color:#ffd29b}
</style>
