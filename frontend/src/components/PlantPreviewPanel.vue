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
  <section class="plant-preview-panel" aria-label="厂区近景预览">
    <div class="panel-eyebrow">厂区近景预览<Building2 :size="16" /></div>
    <p class="small muted">参考公开资料的仿真布局：GIS 开关楼、地面副厂房、辅助用房和多栋候选厂房，以及场坪、挡墙与道路。开启时隐藏会误读的地面主厂房与露天主变，关闭后恢复原场景；新增厂房仅作建模效果，不代表真实设施。</p>
    <div class="preview-controls">
      <button class="primary-button" :disabled="!profile" @click="toggle">
        <Eye v-if="!previewVisible" :size="14" /><EyeOff v-else :size="14" />
        {{ previewVisible ? '关闭预览层' : '开启预览层' }}
      </button>
      <button class="secondary-button" :disabled="!profile" @click="emit('focus', 'oblique')">斜视</button>
      <button class="secondary-button" :disabled="!profile" @click="emit('focus', 'top')">俯视</button>
    </div>
    <p v-if="previewVisible" class="preview-tag"><Layers :size="13" />参考公开资料的仿真布局 · 坝区与卫星底图待位置核准</p>
  </section>
</template>

<style scoped>
.plant-preview-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin:12px 0;background:#122436}
.plant-preview-panel .panel-eyebrow{margin-bottom:10px}
.preview-controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}
.preview-controls .primary-button,.preview-controls .secondary-button{display:inline-flex;align-items:center;gap:5px}
.preview-tag{display:inline-flex;align-items:center;gap:5px;margin:9px 0 0;font-size:.78rem;color:#ffd29b}
</style>
