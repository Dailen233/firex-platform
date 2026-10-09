<script setup lang="ts">
import { computed } from 'vue'
import { Box, ExternalLink, MapPin, X, ShieldQuestion, Zap } from 'lucide-vue-next'
import type { Plant } from '../lib/types'
import { capacityScope,sceneFor,assetUrl } from '../lib/data'
const props=defineProps<{plant:Plant;province:string}>()
const emit=defineEmits<{close:[]}>()
const scene=computed(()=>sceneFor(props.plant.properties.plant_id))
</script>
<template>
 <aside class="plant-detail" aria-label="电厂详情">
  <div class="panel-eyebrow">电厂详情<button class="icon-button" @click="emit('close')" aria-label="关闭电厂详情"><X :size="18"/></button></div>
  <div class="detail-title"><span class="type-label">{{plant.properties.technology==='Coal'?'燃煤电厂':'水电站'}}</span><h2>{{plant.properties.name}}</h2><p><MapPin :size="14"/>{{plant.properties.source_province}}{{scene?' · 织金县八步街道':''}}</p></div>
  <div class="capacity"><Zap :size="20"/><strong>{{plant.properties.capacity_mw?.toLocaleString()??'未知'}}</strong><span>MW</span></div>
  <p class="muted scope">{{capacityScope(plant)}}</p>
  <div v-if="plant.properties.capacity_source_conflict" class="notice amber">来源差异待核查：官方报道 6,400 MW，GEM 7,750 MW。两者的统计口径尚未确认。</div>
  <dl class="facts"><div><dt>运行状态（来源记录）</dt><dd>{{plant.properties.operating_status==='Operating'?'运行中':plant.properties.operating_status}}</dd></div><div><dt>火情状态</dt><dd class="unknown"><ShieldQuestion :size="14"/>尚未接入</dd></div><div><dt>代表点坐标</dt><dd>{{plant.geometry.coordinates[0]}}, {{plant.geometry.coordinates[1]}}</dd></div><div><dt>坐标基准</dt><dd>WGS84 / EPSG:4326</dd></div></dl>
  <p class="small muted">点位来自资料页面，独立影像核验待完成；非测绘级坐标。</p>
  <section class="scene-card" v-if="scene">
   <img :src="assetUrl('models/zhijin-v4/assets/scene_preview.png')" alt="织金 v4 模型预览"/>
   <div><span class="tag">试建场景 · v4</span><h3>电厂与周边山地</h3><p>4 × 4 km · 16 km² 研究区</p><p class="small muted">无卫星纹理，几何与地理精度待验证。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${scene.scene_id}`,query:{province,plant:plant.properties.plant_id}}"><Box :size="17"/>进入三维场景</RouterLink></div>
  </section>
  <div v-else class="empty-model"><Box :size="25"/><strong>尚无三维模型</strong><p>当前仅提供电厂样例详情。</p></div>
  <section class="source-section"><h3>数据依据</h3><p class="small">{{plant.properties.source_version}}</p><a :href="plant.properties.source_url" target="_blank" rel="noopener noreferrer">GEM 项目页面<ExternalLink :size="13"/></a><a v-if="plant.properties.capacity_source_url" :href="plant.properties.capacity_source_url" target="_blank" rel="noopener noreferrer">装机容量官方来源<ExternalLink :size="13"/></a><a v-if="plant.properties.official_case_source" :href="plant.properties.official_case_source" target="_blank" rel="noopener noreferrer">{{scene?'国家能源集团照片参考':'补充资料来源'}}<ExternalLink :size="13"/></a><p class="small muted">项目编号：{{plant.properties.plant_id}}<br/>自定义样例 ID，非 GEM 原生编号。</p><details><summary>原始容量口径</summary><p class="small">{{plant.properties.capacity_scope}}</p></details></section>
 </aside>
</template>
