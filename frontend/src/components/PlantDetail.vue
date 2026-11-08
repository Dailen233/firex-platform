<script setup lang="ts">
import { computed } from 'vue'
import { Box, ExternalLink, MapPin, X, ShieldQuestion, Zap, Flame, FlaskConical } from 'lucide-vue-next'
import type { Plant } from '../lib/types'
import { capacityScope,sceneFor,referenceSceneFor,prototypeScenesFor,assetUrl } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import { useRunConnection } from '../lib/run-connection'
const props=defineProps<{plant:Plant;province:string}>()
const emit=defineEmits<{close:[]}>()
const scene=computed(()=>sceneFor(props.plant.properties.plant_id))
const referenceScene=computed(()=>referenceSceneFor(props.plant.properties.plant_id))
const prototypeScenes=computed(()=>prototypeScenesFor(props.plant.properties.plant_id))
const {isDemoOn,activeFirePatches}=useFireDemo()
const demoActive=computed(()=>props.plant.properties.plant_id==='GEM_COAL_ZHIJIN'&&isDemoOn.value&&activeFirePatches.value.length>0)
const {isConnected,run,snapshot,observationTimeLabel}=useRunConnection()
const bound=computed(()=>isConnected.value&&run.value?.plant_id===props.plant.properties.plant_id)
</script>
<template>
 <aside class="plant-detail" aria-label="电厂详情">
  <div class="panel-eyebrow">电厂详情<button class="icon-button" @click="emit('close')" aria-label="关闭电厂详情"><X :size="18"/></button></div>
  <div class="detail-title"><span class="type-label">{{plant.properties.technology==='Coal'?'燃煤电厂':'水电站'}}</span><h2>{{plant.properties.name}}</h2><p><MapPin :size="14"/>{{plant.properties.source_province}}{{scene?' · 织金县八步街道':''}}</p></div>
  <div class="capacity"><Zap :size="20"/><strong>{{plant.properties.capacity_mw?.toLocaleString()??'未知'}}</strong><span>MW</span></div>
  <p class="muted scope">{{capacityScope(plant)}}</p>
  <p v-if="plant.properties.commissioning_note" class="small muted scope">{{plant.properties.commissioning_note}}<template v-if="plant.properties.dam_design_height_m"> · 设计坝高 {{plant.properties.dam_design_height_m}} m</template></p>
  <div v-if="plant.properties.capacity_source_conflict" class="notice amber">来源差异待核查：官方报道 6,400 MW，GEM 7,750 MW。两者的统计口径尚未确认。</div>
  <dl class="facts"><div><dt>运行状态（来源记录）</dt><dd>{{plant.properties.operating_status==='Operating'?'运行中':plant.properties.operating_status}}</dd></div><div><dt>火情状态</dt><dd class="unknown"><ShieldQuestion v-if="!demoActive" :size="14"/><Flame v-else :size="14"/>{{demoActive?'数据来源：仿真':'火情数据未接入'}}</dd></div><div><dt>代表点坐标</dt><dd>{{plant.geometry.coordinates[0]}}, {{plant.geometry.coordinates[1]}}</dd></div><div><dt>坐标基准</dt><dd>WGS84 / EPSG:4326</dd></div></dl>
  <p class="small muted">点位来自资料页面，独立影像核验待完成；非测绘级坐标。</p>
  <section v-if="bound" class="run-bind-panel">
   <div class="panel-eyebrow">监测运行<FlaskConical :size="16"/></div>
   <template v-if="snapshot?.state_status==='observation'">
    <p class="small amber"><strong>{{snapshot.result_origin==='yolo'?'数据来源：仿真':'数据来源：接口测试'}}，不代表图像重建</strong>（提供者 {{snapshot.provider_version}}）</p>
    <dl class="facts"><div><dt>观测时间</dt><dd>{{observationTimeLabel}}</dd></div><div><dt>火区</dt><dd>{{snapshot.patches.length}} 个</dd></div></dl>
   </template>
   <p v-else class="small muted">等待观测数据，不能解释为确认无火。</p>
  </section>
  <section class="scene-card" v-if="scene">
   <img :src="assetUrl('models/zhijin-v4/assets/scene_preview.png')" alt="织金 v4 模型预览"/>
   <div><span class="tag">试建场景 · v4</span><h3>电厂与周边山地</h3><p>4 × 4 km · 16 km² 研究区</p><p class="small muted">无卫星纹理，几何与地理精度待验证。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${scene.scene_id}`,query:{province,plant:plant.properties.plant_id}}"><Box :size="17"/>进入三维场景</RouterLink></div>
  </section>
  <section v-if="referenceScene" class="scene-card reference">
   <img :src="assetUrl('models/shuangjiangkou-reference-v1/reference_preview.png')" alt="双江口参考底座预览"/>
   <div><span class="tag">参考底座 · reference-v1</span><h3>公开 DSM 山地参考底座</h3><p>约 100 km² · 建议研究区</p><p class="small muted">非当前大坝/厂区精细模型；主要数据采集于 2011–2015 年。正式模型待接入。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${referenceScene.scene_id}`,query:{province,plant:plant.properties.plant_id}}"><Box :size="17"/>浏览山地参考底座</RouterLink></div>
  </section>
  <section v-for="ps in prototypeScenes" :key="ps.scene_id" class="scene-card prototype">
   <div><span class="tag amber">模型草案 · 未配准</span><h3>{{ps.display_name}}</h3><p class="small muted">{{ps.notice ?? '概念模型 · 尚未配准'}}</p><p class="small muted">仅模型预览；不能把本地几何范围当作已完成地理配准。</p>
   <RouterLink class="primary-button" :to="{path:`/scene/${ps.scene_id}`,query:{province,plant:plant.properties.plant_id}}"><Box :size="17"/>查看草案</RouterLink></div>
  </section>
  <div v-if="!scene && !referenceScene && !prototypeScenes.length" class="empty-model"><Box :size="25"/><strong>尚无三维模型</strong><p>当前仅提供电厂样例详情，三维场景待接入。</p></div>
  <section v-if="plant.properties.research_area_markers?.length" class="research-area">
   <div class="panel-eyebrow">研究区参考标记</div>
   <p class="small muted">{{plant.properties.research_area_scope_note??'研究区边界与范围待核。'}}</p>
   <ul class="marker-list">
    <li v-for="m in plant.properties.research_area_markers" :key="m.id">
     <div class="marker-line"><span class="tag amber">公开地图参考 · 非测量</span><strong>{{m.label}}</strong></div>
     <p class="small muted coord">{{m.lon}}, {{m.lat}}（WGS84）</p>
     <p class="small muted">{{m.note}}<template v-if="m.source_url"> · <a :href="m.source_url" target="_blank" rel="noopener noreferrer">{{m.source}}<ExternalLink :size="11"/></a></template></p>
    </li>
   </ul>
  </section>
  <section class="source-section"><h3>数据依据</h3><p class="small">{{plant.properties.source_version}}</p><a :href="plant.properties.source_url" target="_blank" rel="noopener noreferrer">项目来源页面<ExternalLink :size="13"/></a><a v-if="plant.properties.capacity_source_url" :href="plant.properties.capacity_source_url" target="_blank" rel="noopener noreferrer">装机容量官方来源<ExternalLink :size="13"/></a><a v-if="plant.properties.official_case_source" :href="plant.properties.official_case_source" target="_blank" rel="noopener noreferrer">{{scene?'国家能源集团照片参考':'补充资料来源'}}<ExternalLink :size="13"/></a><p class="small muted">项目编号：{{plant.properties.plant_id}}<br/>自定义样例 ID，非 GEM 原生编号。</p><details><summary>原始容量口径</summary><p class="small">{{plant.properties.capacity_scope}}</p></details></section>
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
