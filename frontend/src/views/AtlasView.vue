<script setup lang="ts">
import { computed,onMounted,onBeforeUnmount } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { MapPin,Box,Layers,Info,Compass,ChevronRight,Flame,Mountain,FlaskConical } from 'lucide-vue-next'
import ProvinceMap from '../components/ProvinceMap.vue'
import PlantDetail from '../components/PlantDetail.vue'
import RunConnectionPanel from '../components/RunConnectionPanel.vue'
import { plants,boundaries,boundaryLines,dataReady,dataError,boundaryError,loadCatalog,relatedPlants,sceneFor,referenceSceneFor,prototypeScenesFor,sceneLinks } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import { useRunConnection } from '../lib/run-connection'
import { useAtlasFireStatus,observationTimeLabel,originLabel } from '../lib/fire-status'
import type { AtlasFireStatusItem } from '../lib/backend'
import { provinces,provinceName } from '../lib/provinces'
const route=useRoute();const router=useRouter()
const province=computed(()=>provinces.some(p=>p[0]===route.query.province)?String(route.query.province):'')
const currentPlants=computed(()=>province.value?relatedPlants(province.value):plants.value)
const modeledProjectPlantIds=new Set(['GEM_HYDRO_SHUANGJIANGKOU','GEM_COAL_ZHIJIN'])
const plantGroups=computed(()=>[
 {key:'modeled',label:'双江口与织金建模项目',note:'双江口正式模型仍待接入；具体场景资源类型见标签。',plants:currentPlants.value.filter(p=>modeledProjectPlantIds.has(p.properties.plant_id))},
 {key:'other',label:'其他电厂样例',note:'',plants:currentPlants.value.filter(p=>!modeledProjectPlantIds.has(p.properties.plant_id))},
].filter(group=>group.plants.length))
const selected=computed(()=>currentPlants.value.find(p=>p.properties.plant_id===route.query.plant))
const browsableSceneCount=computed(()=>sceneLinks.value.length)
const {isDemoOn,activeFirePatches}=useFireDemo()
const demoActive=computed(()=>isDemoOn.value&&activeFirePatches.value.length>0)
const conn=useRunConnection()
const boundPlantId=computed(()=>conn.isConnected.value?conn.run.value?.plant_id??'':'')
const {fireItems,staleItems,noDetectionItems,connected,everConnected,start:startFireStatus,stop:stopFireStatus}=useAtlasFireStatus()
const firePlants=computed(()=>fireItems.value.map(i=>({plantId:i.plant_id,label:originLabel(i),statusText:fireStatusText(i)})))
const fireAlertCount=computed(()=>fireItems.value.length)
const noDetectionCount=computed(()=>noDetectionItems.value.length)
function fireStatusText(item:AtlasFireStatusItem){return `观测 ${observationTimeLabel(item)} · ${item.result_origin??'来源未知'}`}
function plantName(id:string){return plants.value.find(p=>p.properties.plant_id===id)?.properties.name??id}
function chooseProvince(code:string){router.push({path:'/atlas',query:code?{province:code}:{}})}
function choosePlant(id:string){router.push({path:'/atlas',query:{...(province.value?{province:province.value}:{}),plant:id}})}
function close(){router.push({path:'/atlas',query:province.value?{province:province.value}:{}})}
onMounted(()=>{loadCatalog();startFireStatus()})
onBeforeUnmount(()=>stopFireStatus())
</script>
<template>
 <main class="atlas-layout">
  <aside class="province-panel">
   <div class="panel-eyebrow">区域目录<Layers :size="16"/></div><h2>按省份浏览</h2><p class="small muted">跨省电站在关联省份重复展示</p>
   <button class="province-button national" :class="{selected:!province}" @click="chooseProvince('')"><span>全国样例</span><b>{{plants.length}}</b></button>
   <div class="province-scroll"><template v-for="(p,index) in provinces" :key="p[0]"><div v-if="index===3" class="divider-label">其他省级地区</div><button class="province-button" :class="{selected:province===p[0]}" @click="chooseProvince(p[0])" :aria-pressed="province===p[0]"><span>{{p[1]}}</span><b v-if="relatedPlants(p[0]).length">{{relatedPlants(p[0]).length}}</b><span v-else class="province-empty">—</span></button></template></div>
   <div class="province-footer"><Info :size="15"/><span>{{plants.length}} 个样例，非全国电厂清单。<br/>无样例不代表当地没有电厂。</span></div>
  </aside>
  <section class="atlas-workspace">
   <div class="workspace-heading"><div><div class="eyebrow">电厂与山地场景 / ATLAS</div><h1>{{provinceName(province)}}<span>电厂总览</span></h1></div><div class="overview-stats"><div><strong>{{plants.length}}</strong><span>唯一电厂样例</span></div><div><strong>{{browsableSceneCount}}</strong><span>可浏览三维场景</span></div><div><strong>34</strong><span>省级地区</span></div></div></div>
   <RunConnectionPanel class="atlas-connection"/>
   <div v-if="dataError" class="notice error" role="alert">{{dataError}}<button @click="loadCatalog">重新读取</button></div>
   <div class="map-section">
    <div class="map-topline"><span><Compass :size="16"/>中国省级地图</span><span class="small muted">选择省份或电厂自动定位放大 · 滚轮缩放</span></div>
    <ProvinceMap v-if="boundaries && dataReady" :boundaries="boundaries" :lines="boundaryLines" :plants="plants" :province="province" :selected-plant="selected?.properties.plant_id??''" :demo-active="demoActive" :test-plant-id="boundPlantId" :fire-plants="firePlants" @province="chooseProvince" @plant="choosePlant"/>
    <div v-else class="map-empty"><Layers :size="36"/><h3>{{boundaryError?'地图资源暂不可用':'正在读取省级地图'}}</h3><p>{{boundaryError?'可继续通过左侧省份列表浏览电厂与模型。':'加载本地边界文件与电厂样例。'}}</p><button v-if="boundaryError" @click="loadCatalog">重新读取地图</button></div>
    <div class="map-bottomline"><span><span class="sample-dot"></span>点位表示电厂样例，不表示火情</span><span v-if="!everConnected" class="tag neutral">火情监测数据未接入</span><span v-else-if="!connected" class="tag danger"><Flame :size="13"/>火情监测连接断开</span><span v-else-if="fireAlertCount" class="tag danger"><Flame :size="13"/>火情监测：{{fireAlertCount}} 厂站检出火点</span><span v-else-if="noDetectionCount" class="tag neutral">火情监测已接入 · 本帧未检出火点</span><span v-else class="tag neutral">火情监测已接入 · 等待数据</span></div>
   </div>
   <section class="fire-feedback">
    <div class="section-heading"><h2>火情反馈<span class="count-pill">{{fireAlertCount}}</span></h2><span class="small muted">有效检测结果自动标出；合成火情标「数据来源：仿真」，接口测试标「数据来源：接口测试」</span></div>
    <div v-if="!everConnected" class="empty-state">等待火情监测数据…</div>
    <div v-else-if="!connected" class="notice amber" role="status">火情监测连接断开，显示最近一次结果（可能已过期）。</div>
    <div v-if="fireItems.length" class="fire-list">
     <div v-for="i in fireItems" :key="i.run_id" class="fire-card">
      <div class="fire-card-head"><strong>{{plantName(i.plant_id)}}</strong><span class="tag danger"><Flame :size="12"/>{{originLabel(i)}}</span></div>
      <dl class="fire-facts">
       <div><dt>观测时间</dt><dd>{{observationTimeLabel(i)}}</dd></div>
       <div v-if="i.detection_count"><dt>检测结果</dt><dd>{{i.detection_count}} 个火点</dd></div>
       <div v-else-if="i.patch_count"><dt>火区</dt><dd>{{i.patch_count}} 个</dd></div>
       <div v-if="i.model_ref"><dt>检测模型</dt><dd class="mono">{{i.model_ref}}</dd></div>
      </dl>
      <button class="secondary-button" @click="choosePlant(i.plant_id)">查看电厂</button>
     </div>
    </div>
    <div v-else-if="connected&&noDetectionCount" class="no-detect-list">
     <div v-for="i in noDetectionItems" :key="i.run_id" class="no-detect-card">
      <strong>{{plantName(i.plant_id)}}</strong><span class="tag neutral">本帧未检出火点</span>
      <span class="small muted">观测 {{observationTimeLabel(i)}} · {{originLabel(i)}}</span>
     </div>
    </div>
    <div v-else-if="connected" class="empty-state">暂无火情告警{{staleItems.length?'（历史/过期记录不计入）':''}}。</div>
    <details v-if="staleItems.length" class="fire-history"><summary>历史 / 过期记录（{{staleItems.length}}）</summary><ul><li v-for="i in staleItems" :key="i.run_id">{{plantName(i.plant_id)}} · 观测 {{observationTimeLabel(i)}} · {{i.result_origin??'—'}}（已过期）</li></ul></details>
   </section>
   <section class="plant-list"><div class="section-heading"><h2>{{province?`${provinceName(province)}关联电厂`:'全国电厂样例'}}<span class="count-pill">{{currentPlants.length}}</span></h2><span class="small muted">按项目 ID 关联 · 全国数量去重</span></div>
    <div v-if="!dataReady&&!dataError" class="empty-state">正在读取电厂目录…</div>
    <div v-else-if="!currentPlants.length" class="empty-state"><MapPin :size="24"/><div><strong>暂无样例数据</strong><p>{{provinceName(province)}}尚未收录电厂样例，可选择贵州、四川或云南继续浏览。</p></div></div>
    <div v-else class="plant-groups">
     <section v-for="group in plantGroups" :key="group.key" class="plant-group">
      <div class="plant-group-heading"><h3>{{group.label}}<span class="count-pill">{{group.plants.length}}</span></h3><span v-if="group.note" class="small muted">{{group.note}}</span></div>
      <div class="plant-grid"><button v-for="p in group.plants" :key="p.properties.plant_id" class="plant-item" :class="{chosen:selected?.properties.plant_id===p.properties.plant_id}" @click="choosePlant(p.properties.plant_id)"><span class="plant-type-icon"><Box v-if="sceneFor(p.properties.plant_id)" :size="19"/><Mountain v-else-if="referenceSceneFor(p.properties.plant_id)" :size="19"/><FlaskConical v-else-if="prototypeScenesFor(p.properties.plant_id).length" :size="19"/><MapPin v-else :size="19"/></span><span class="plant-item-text"><strong>{{p.properties.name}}</strong><span>{{p.properties.technology==='Coal'?'燃煤':'水电'}} · {{p.properties.capacity_mw?.toLocaleString()??'未知'}} MW</span></span><span v-if="sceneFor(p.properties.plant_id)" class="tag">三维试建</span><span v-else-if="referenceSceneFor(p.properties.plant_id)" class="tag">参考预览</span><span v-if="prototypeScenesFor(p.properties.plant_id).length" class="tag">模型草案</span><ChevronRight v-if="!sceneFor(p.properties.plant_id)&&!referenceSceneFor(p.properties.plant_id)&&!prototypeScenesFor(p.properties.plant_id).length" :size="16" class="muted"/></button></div>
     </section>
    </div>
   </section>
   <footer class="atlas-footnote"><details><summary>地图来源与精度说明</summary><p>GeoJSON.CN 第三方分发与转换，来源页注明天地图；2026-10-09 取得 34 个省级面与 8 个境界线要素。底图 CGCS2000 / EPSG:4490，点位 WGS84 / EPSG:4326，未进行坐标基准转换。本轮为省级浏览，不代表米级地理配准验收。</p><a href="https://geojson.cn/data/atlas/tiandi" target="_blank" rel="noopener noreferrer">来源及版本说明</a></details></footer>
  </section>
  <PlantDetail v-if="selected" :plant="selected" :province="province" @close="close"/>
 </main>
</template>
<style scoped>
.fire-feedback{margin:14px 0}
.fire-feedback .section-heading{margin-bottom:10px}
.fire-list{display:flex;flex-wrap:wrap;gap:10px}
.fire-card{border:1px solid #5a2f2f;border-radius:8px;padding:12px;background:#1a1216;min-width:240px}
.fire-card-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.fire-facts{margin:0 0 10px}
.fire-facts>div{display:flex;justify-content:space-between;gap:8px;border-top:1px solid #3a2430;padding:4px 0;font-size:.8125rem}
.fire-facts>div:first-child{border-top:0}
.fire-facts dt{color:#c9a8b4}
.fire-facts dd{font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,monospace;font-size:.72rem;word-break:break-all}
.fire-history{margin-top:8px;font-size:.8125rem;color:var(--muted)}
.fire-history ul{margin:6px 0 0;padding-left:18px}
.no-detect-list{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}
.no-detect-card{display:flex;align-items:center;gap:10px;flex-wrap:wrap;border:1px solid #33414d;border-radius:8px;padding:10px 12px;background:#121a22;font-size:.875rem}
.plant-group+.plant-group{margin-top:17px}
.plant-group-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:9px}
.plant-group-heading h3{display:flex;align-items:center;gap:8px;font-size:.9rem;font-weight:600}
.plant-group-heading>.small{font-size:.75rem;text-align:right}
@media(max-width:640px){.plant-group-heading{align-items:flex-start;flex-direction:column;gap:4px}.plant-group-heading>.small{text-align:left}}
</style>
