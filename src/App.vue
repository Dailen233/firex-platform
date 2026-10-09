<script setup lang="ts">
import { Flame, Map, Box } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
const route=useRoute()
</script>
<template>
  <div class="app-shell">
    <header class="app-header">
      <RouterLink to="/atlas" class="brand" aria-label="Fire-X 电厂总览"><span class="brand-icon"><Flame :size="25"/></span><span>Fire<span class="brand-x">-X</span></span><small>火灾数字孪生</small></RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/atlas" :class="{active:route.path==='/atlas'}"><Map :size="17"/>电厂总览</RouterLink>
        <span v-if="route.path.startsWith('/scene')" class="active"><Box :size="17"/>织金三维场景</span>
      </nav>
      <div class="header-note"><span class="round-label">首轮原型</span><span class="muted">数据截至 2026.10.09</span></div>
    </header>
    <RouterView/>
  </div>
</template>
