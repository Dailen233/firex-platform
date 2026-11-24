<script setup lang="ts">
import { computed } from 'vue'
import { Box, ExternalLink, MapPin, X, ShieldQuestion, Zap, Flame, FlaskConical } from 'lucide-vue-next'
import type { Plant } from '../lib/types'
import { capacityScope,sceneFor,referenceSceneFor,prototypeScenesFor,assetUrl } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import { useRunConnection } from '../lib/run-connection'
const props=defineProps<{plant:Plant;browseQuery:Record<string,string>}>()
const emit=defineEmits<{close:[]}>()
const sceneQuery=computed(()=>({...props.browseQuery,plant:props.plant.properties.plant_id}))
const scene=computed(()=>sceneFor(props.plant.properties.plant_id))
const referenceScene=computed(()=>referenceSceneFor(props.plant.properties.plant_id))
const prototypeScenes=computed(()=>prototypeScenesFor(props.plant.properties.plant_id))
const {isDemoOn,activeFirePatches}=useFireDemo()
const demoActive=computed(()=>props.plant.properties.plant_id==='GEM_COAL_ZHIJIN'&&isDemoOn.value&&activeFirePatches.value.length>0)
const {isConnected,run,snapshot,observationTimeLabel}=useRunConnection()
const bound=computed(()=>isConnected.value&&run.value?.plant_id===props.plant.properties.plant_id)
</script>
<template>
 <aside class="plant-detail" aria-label="场站信息">
  <div class="panel-eyebrow">场站信息<button class="icon-button" @click="emit('close')" aria-label="关闭场站信息"><X :size="18"/></button></div>
  <div class="detail-title"><span class="type-label">{{plant.properties.technology==='Coal'?'燃煤电厂':'水电站'}}</span><h2>{{plant.properties.name}}</h2><p><MapPin :size="14"/>{{plant.properties.source_province}}{{scene?' · 织金县八步街道':''}}</p></div>
  <div class="capacity"><Zap :size="20"/><strong>{{plant.properties.capacity_mw?.toLocaleString()??'未知'}}</strong><span>MW</span></div>
  <p class="muted scope">{{capacityScope(plant)}}</p>
  <p v-if="plant.properties.commissioning_note" class="small muted scope">{{plant.properties.commissioning_note}}<template v-if="plant.properties.dam_design_height_m"> · 设计坝高 {{plant.properties.dam_design_height_m}} m</template></p>
  <div v-if="plant.properties.capacity_source_conflict" class="notice amber">公开资料中的装机容量不一致：一处记载 6,400 MW，另一处记载 7,750 MW，统计口径仍需核实。</div>
  <dl class="facts"><div><dt>公开资料状态</dt><dd>{{plant.properties.operating_status==='Operating'?'运行中':plant.properties.operating_status}}</dd></div><div><dt>火情信息</dt><dd class="unknown"><ShieldQuestion v-if="!demoActive" :size="14"/><Flame v-else :size="14"/>{{demoActive?'模拟数据':'暂无火情观测'}}</dd></div></dl>
  <details class="location-meta"><summary>位置与数据说明</summary><dl class="facts"><div><dt>地图参考坐标</dt><dd>{{plant.geometry.coordinates[0]}}, {{plant.geometry.coordinates[1]}}</dd></div><div><dt>坐标参考</dt><dd>WGS84 / EPSG:4326</dd></div></dl><p class="small muted">位置取自公开资料，仅用于地图定位，尚未达到测绘精度。</p></details>
  <section v-if="bound" class="run-bind-panel">
   <div class="panel-eyebrow">当前监测<FlaskConical :size="16"/></div>
   <template v-if="snapshot?.state_status==='observation'">
    <p class="small amber"><strong>{{snapshot.result_origin==='yolo'?'模拟观测数据':'平台测试数据'}}</strong>，不代表真实现场影像分析结果。</p>
    <dl class="facts"><div><dt>观测时间</dt><dd>{{observationTimeLabel}}</dd></div><div><dt>火区</dt><dd>{{snapshot.patches.length}} 个</dd></div></dl>
   </template>
   <p v-else class="small muted">尚未收到观测数据，当前情况未知，不能视为无火。</p>
  </section>
  <section class="scene-card" v-if="scene">
   <img :src="assetUrl('models/zhijin-v4/assets/scene_preview.png')" alt="织金 v4 模型预览"/>
   <div><span class="tag">三维预览版</span><h3>电厂与周边山地</h3><p>展示范围约 4 × 4 km</p><p class="small muted">厂区和地形用于场景预览，位置与细节尚未完成实地校核。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${scene.scene_id}`,query:sceneQuery}"><Box :size="17"/>查看三维预览</RouterLink></div>
  </section>
  <section v-if="referenceScene" class="scene-card reference">
   <img :src="assetUrl('models/shuangjiangkou-reference-v1/reference_preview.png')" alt="双江口参考底座预览"/>
   <div><span class="tag">周边地形预览</span><h3>双江口周边山地</h3><p>展示范围约 100 km²</p><p class="small muted">基于公开地形资料，不包含经核验的大坝和厂区精细模型。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${referenceScene.scene_id}`,query:sceneQuery}"><Box :size="17"/>查看地形预览</RouterLink></div>
  </section>
  <section v-for="ps in prototypeScenes" :key="ps.scene_id" class="scene-card prototype">
   <div><span class="tag amber">概念预览</span><h3>{{ps.display_name}}</h3><p class="small muted">{{ps.notice ?? '用于展示场景构想'}}</p><p class="small muted">模型位置尚未与真实地理位置校准。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${ps.scene_id}`,query:sceneQuery}"><Box :size="17"/>查看概念预览</RouterLink></div>
  </section>
  <div v-if="!scene && !referenceScene && !prototypeScenes.length" class="empty-model"><Box :size="25"/><strong>三维场景暂未开放</strong><p>你仍可查看该场站的基本信息。</p></div>
  <section v-if="plant.properties.research_area_markers?.length" class="research-area">
   <div class="panel-eyebrow">周边位置参考</div>
   <p class="small muted">{{plant.properties.research_area_scope_note??'以下位置来自公开地图资料，仅用于场景参考。'}}</p>
   <ul class="marker-list">
    <li v-for="m in plant.properties.research_area_markers" :key="m.id">
     <div class="marker-line"><span class="tag amber">地图参考位置</span><strong>{{m.label}}</strong></div>
    <details class="marker-coordinate"><summary>查看地图坐标</summary><p class="small muted coord">{{m.lon}}, {{m.lat}}（WGS84）</p></details>
     <p class="small muted">{{m.note}}<template v-if="m.source_url"> · <a :href="m.source_url" target="_blank" rel="noopener noreferrer">{{m.source}}<ExternalLink :size="11"/></a></template></p>
    </li>
   </ul>
  </section>
  <section class="source-section"><h3>资料来源</h3><p class="small">{{plant.properties.source_version}}</p><a :href="plant.properties.source_url" target="_blank" rel="noopener noreferrer">查看场站资料<ExternalLink :size="13"/></a><a v-if="plant.properties.capacity_source_url" :href="plant.properties.capacity_source_url" target="_blank" rel="noopener noreferrer">查看装机容量来源<ExternalLink :size="13"/></a><a v-if="plant.properties.official_case_source" :href="plant.properties.official_case_source" target="_blank" rel="noopener noreferrer">{{scene?'查看公开项目图片':'查看补充资料'}}<ExternalLink :size="13"/></a><details><summary>装机容量统计口径</summary><p class="small">{{plant.properties.capacity_scope}}</p></details></section>
 </aside>
</template>
<style scoped>
.research-area{border:1px solid var(--border);border-radius:8px;padding:13px;margin-top:14px;background:#0d1a26}
.marker-list{list-style:none;margin:10px 0 0;padding:0}
.marker-list li{border-top:1px solid var(--border);padding:9px 0}
.marker-list li:first-child{border-top:0;padding-top:2px}
.marker-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.marker-list .coord{font-variant-numeric:tabular-nums}
</style>
