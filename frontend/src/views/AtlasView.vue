<script setup lang="ts">
import { computed,onMounted,onBeforeUnmount,ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { MapPin,Box,Layers,Info,Compass,ChevronRight,Flame,Mountain,FlaskConical,Search,X } from 'lucide-vue-next'
import ProvinceMap from '../components/ProvinceMap.vue'
import PlantDetail from '../components/PlantDetail.vue'
import RunConnectionPanel from '../components/RunConnectionPanel.vue'
import { plants,boundaries,boundaryLines,dataReady,dataError,boundaryError,loadCatalog,relatedPlants,sceneFor,referenceSceneFor,prototypeScenesFor,sceneLinks,sceneBySceneId } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import { useRunConnection } from '../lib/run-connection'
import { useAtlasFireStatus,observationTimeLabel,originLabel } from '../lib/fire-status'
import type { AtlasFireStatusItem } from '../lib/backend'
import { provinces,provinceName } from '../lib/provinces'
import { gridRegions,gridUnassigned,gridRegionSources,provinceCodesForGridRegion } from '../lib/grid-regions'
const route=useRoute();const router=useRouter()
const gridView=computed(()=>route.query.mode==='grid')
const gridArea=computed(()=>[...gridRegions,gridUnassigned].find(area=>area.id===route.query.area))
const province=computed(()=>!gridView.value&&provinces.some(p=>p[0]===route.query.province)?String(route.query.province):'')
const currentPlants=computed(()=>gridView.value?(gridArea.value?plants.value.filter(p=>provinceCodesForGridRegion(gridArea.value!.id).includes(p.properties.province_code)):plants.value):province.value?relatedPlants(province.value):plants.value)
const plantSearch=ref('')
const visiblePlants=computed(()=>{
 const query=plantSearch.value.trim().toLocaleLowerCase()
 if(!query)return currentPlants.value
 return currentPlants.value.filter(p=>`${p.properties.name} ${provinceName(p.properties.province_code)} ${p.properties.technology==='Coal'?'燃煤':'水电'}`.toLocaleLowerCase().includes(query))
})
const modeledProjectPlantIds=new Set(['GEM_HYDRO_SHUANGJIANGKOU','GEM_COAL_ZHIJIN'])
const plantGroups=computed(()=>[
 {key:'modeled',label:'可查看三维内容',note:'包含厂区预览或周边地形，具体内容和校核状态见场站详情。',plants:visiblePlants.value.filter(p=>modeledProjectPlantIds.has(p.properties.plant_id))},
 {key:'other',label:'其他场站信息',note:'',plants:visiblePlants.value.filter(p=>!modeledProjectPlantIds.has(p.properties.plant_id))},
].filter(group=>group.plants.length))
const selected=computed(()=>currentPlants.value.find(p=>p.properties.plant_id===route.query.plant))
const {isDemoOn,activeFirePatches}=useFireDemo()
const demoActive=computed(()=>isDemoOn.value&&activeFirePatches.value.length>0)
const conn=useRunConnection()
const boundPlantId=computed(()=>conn.isConnected.value?conn.run.value?.plant_id??'':'')
const {fireItems,staleItems,noDetectionItems,connected,everConnected,start:startFireStatus,stop:stopFireStatus}=useAtlasFireStatus()
const firePlants=computed(()=>fireItems.value.map(i=>({plantId:i.plant_id,label:originLabel(i),statusText:fireStatusText(i)})))
const fireAlertCount=computed(()=>fireItems.value.length)
const noDetectionCount=computed(()=>noDetectionItems.value.length)
const fireOverviewText=computed(()=>{
 if(!everConnected.value)return '火情数据尚未接通，当前状态未知。'
 if(!connected.value)return '火情信息连接中断，正在保留最近收到的信息。'
 if(fireAlertCount.value)return `收到 ${fireAlertCount.value} 条火情信息，请查看下方详情。`
 if(noDetectionCount.value)return '本次观测暂未发现火点；这不等于确认无火。'
 return '当前没有收到火情告警；未收到信息不代表现场没有火情。'
})
const sampleSceneCount=computed(()=>sceneLinks.value.filter(link=>currentPlants.value.some(p=>p.properties.plant_id===link.plant_id)).length)
const areaHeading=computed(()=>gridView.value?(gridArea.value?.name??'全国'):provinceName(province.value))
const browseQuery=computed<Record<string,string>>(()=>gridView.value?{mode:'grid',...(gridArea.value?{area:gridArea.value.id}:{})}:province.value?{province:province.value}:{})
function fireStatusText(item:AtlasFireStatusItem){return `观测 ${observationTimeLabel(item)} · ${originLabel(item)}`}
function plantName(id:string){return plants.value.find(p=>p.properties.plant_id===id)?.properties.name??id}
function sampleCountForArea(id:string){const codes=provinceCodesForGridRegion(id);return plants.value.filter(p=>codes.includes(p.properties.province_code)).length}
function chooseProvince(code:string){router.push({path:'/atlas',query:code?{province:code}:{}})}
function chooseGridArea(id:string){router.push({path:'/atlas',query:{mode:'grid',...(id?{area:id}:{})}})}
function chooseMode(mode:'province'|'grid'){router.push({path:'/atlas',query:mode==='grid'?{mode:'grid'}:{}})}
function choosePlant(id:string){router.push({path:'/atlas',query:{...(gridView.value?{mode:'grid',...(gridArea.value?{area:gridArea.value.id}:{})}:province.value?{province:province.value}:{}),plant:id}})}
function alertSceneRoute(item:AtlasFireStatusItem){
 const scene=sceneBySceneId(item.scene_id)
 if(!scene||scene.plant_id!==item.plant_id||scene.asset_version!==item.asset_version)return null
 return {name:'scene',params:{sceneId:scene.scene_id},query:{...browseQuery.value,run_id:item.run_id}}
}
function close(){router.push({path:'/atlas',query:{...(gridView.value?{mode:'grid',...(gridArea.value?{area:gridArea.value.id}:{})}:province.value?{province:province.value}:{})}})}
onMounted(()=>{loadCatalog();startFireStatus()})
onBeforeUnmount(()=>stopFireStatus())
</script>
<template>
 <main class="atlas-layout">
  <aside class="province-panel">
   <div class="panel-eyebrow">浏览范围<Layers :size="16"/></div>
   <div class="atlas-mode-switch" role="group" aria-label="地图划分方式"><button :class="{active:!gridView}" :aria-pressed="!gridView" @click="chooseMode('province')">按省份</button><button :class="{active:gridView}" :aria-pressed="gridView" @click="chooseMode('grid')">按电网区域</button></div>
   <template v-if="gridView">
    <h2>电网区域</h2><p class="small muted">按公开资料整理的区域参考图</p>
    <button class="province-button national" :class="{selected:!gridArea}" @click="chooseGridArea('')"><span>全部已录入场站</span><b>{{plants.length}}</b></button>
    <div class="province-scroll"><button v-for="area in gridRegions" :key="area.id" class="province-button area-button" :class="{selected:gridArea?.id===area.id}" @click="chooseGridArea(area.id)" :aria-pressed="gridArea?.id===area.id"><span><strong>{{area.shortName}}</strong><small>{{area.operator}}</small></span><b v-if="sampleCountForArea(area.id)">{{sampleCountForArea(area.id)}}</b><span v-else class="province-empty">—</span></button><div class="divider-label">其他地区</div><button class="province-button area-button" :class="{selected:gridArea?.id===gridUnassigned.id}" @click="chooseGridArea(gridUnassigned.id)" :aria-pressed="gridArea?.id===gridUnassigned.id"><span><strong>{{gridUnassigned.shortName}}</strong><small>内蒙古待拆分；台港澳未纳入</small></span><span class="province-empty">—</span></button></div>
    <div class="province-footer"><Info :size="15"/><span>分区用于地图浏览，不代表场站的调度归属。</span></div>
   </template>
   <template v-else>
    <h2>按省份浏览</h2><p class="small muted">跨省电站在关联省份重复展示</p>
    <button class="province-button national" :class="{selected:!province}" @click="chooseProvince('')"><span>全部已录入场站</span><b>{{plants.length}}</b></button>
    <div class="province-scroll"><template v-for="(p,index) in provinces" :key="p[0]"><div v-if="index===3" class="divider-label">其他省级地区</div><button class="province-button" :class="{selected:province===p[0]}" @click="chooseProvince(p[0])" :aria-pressed="province===p[0]"><span>{{p[1]}}</span><b v-if="relatedPlants(p[0]).length">{{relatedPlants(p[0]).length}}</b><span v-else class="province-empty">—</span></button></template></div>
    <div class="province-footer"><Info :size="15"/><span>当前已录入 {{plants.length}} 家场站，尚非全国完整名录。未显示不代表当地没有电厂。</span></div>
   </template>
  </aside>
  <section class="atlas-workspace">
   <div class="workspace-heading"><div><div class="eyebrow">Fire-X · 电厂与火情地图</div><h1>{{areaHeading}}<span>{{gridView?'电网区域':'场站总览'}}</span></h1></div><div class="overview-stats"><div><strong>{{currentPlants.length}}</strong><span>已录入场站</span></div><div><strong>{{sampleSceneCount}}</strong><span>可查看三维场景</span></div><div><strong>{{gridView?gridRegions.length:34}}</strong><span>{{gridView?'电网区域':'省级地区'}}</span></div></div></div>
   <div class="coverage-note" role="note"><Info :size="17"/><span><strong>当前覆盖范围有限</strong> · 已录入 {{plants.length}} 家场站，尚非全国完整名录。未显示不代表当地没有电厂。</span></div>
   <div class="fire-overview" :class="{alert:fireAlertCount>0}" role="status" aria-live="polite"><Flame :size="19"/><div><strong>火情动态</strong><span>{{fireOverviewText}}</span></div><b>{{fireAlertCount}}</b></div>
   <details class="advanced-connection"><summary>连接指定监测任务</summary><p class="small muted">用于查看某个已有任务的火情与三维重建结果。</p><RunConnectionPanel/></details>
   <div v-if="dataError" class="notice error" role="alert">{{dataError}}<button @click="loadCatalog">重新读取</button></div>
   <div class="map-section">
    <div class="map-topline"><span><Compass :size="16"/>{{gridView?'电网区域参考图':'已录入场站分布'}}</span><span class="small muted">选择{{gridView?'区域':'省份'}}或场站查看分布</span></div>
    <ProvinceMap v-if="boundaries && dataReady" :boundaries="boundaries" :lines="boundaryLines" :plants="plants" :province="province" :mode="gridView?'grid':'province'" :grid-region-id="gridArea?.id??''" :selected-plant="selected?.properties.plant_id??''" :demo-active="demoActive" :test-plant-id="boundPlantId" :fire-plants="firePlants" @province="chooseProvince" @grid-region="chooseGridArea" @plant="choosePlant"/>
    <div v-else class="map-empty"><Layers :size="36"/><h3>{{boundaryError?'地图暂时不可用':gridView?'正在加载区域地图':'正在加载省份地图'}}</h3><p>{{boundaryError?'你仍可通过左侧区域列表查看场站信息。':'正在准备地图和场站位置。'}}</p><button v-if="boundaryError" @click="loadCatalog">重新加载地图</button></div>
    <div v-if="gridView" class="grid-map-note"><strong>关于分区</strong><span>按公开资料将电网区域归并到省级范围，供浏览参考，并非调度系统的实际边界。场站按登记所在省份显示，不代表其调度归属。内蒙古东西部和河北省内分区尚未拆分；台港澳未纳入。</span><div class="grid-region-key"><span v-for="area in gridRegions" :key="area.id"><i :style="{backgroundColor:area.color}"></i>{{area.shortName}}</span><span><i :style="{backgroundColor:gridUnassigned.color}"></i>待补充 / 未纳入</span></div><div class="grid-source-links"><a v-for="source in gridRegionSources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{source.label}}</a></div></div>
    <div class="map-bottomline"><span><span class="sample-dot"></span>场站位置<span class="fire-dot"></span>收到火情观测</span><span v-if="!everConnected" class="tag neutral">暂无火情数据</span><span v-else-if="!connected" class="tag danger"><Flame :size="13"/>火情数据连接中断</span><span v-else-if="fireAlertCount" class="tag danger"><Flame :size="13"/>{{fireAlertCount}} 家场站有火情信息</span><span v-else-if="noDetectionCount" class="tag neutral">本次观测暂未发现火点</span><span v-else class="tag neutral">正在等待火情信息</span></div>
   </div>
   <section class="fire-feedback">
    <div class="section-heading"><h2>火情动态<span class="count-pill">{{fireAlertCount}}</span></h2><span class="small muted">收到火情信息后会在此显示，并标注信息来源和观测时间。</span></div>
    <div v-if="!everConnected" class="empty-state">尚未收到火情数据；当前状态未知。</div>
    <div v-else-if="!connected" class="notice amber" role="status">火情数据连接中断，暂时显示最近一次信息。</div>
    <div v-if="fireItems.length" class="fire-list">
     <div v-for="i in fireItems" :key="i.run_id" class="fire-card">
      <div class="fire-card-head"><strong>{{plantName(i.plant_id)}}</strong><span class="tag danger"><Flame :size="12"/>{{originLabel(i)}}</span></div>
      <dl class="fire-facts">
       <div><dt>观测时间</dt><dd>{{observationTimeLabel(i)}}</dd></div>
       <div v-if="i.detection_count"><dt>检测结果</dt><dd>{{i.detection_count}} 个火焰检测框</dd></div>
       <div v-else-if="i.patch_count"><dt>火区</dt><dd>{{i.patch_count}} 个</dd></div>
       <div v-if="i.model_ref"><dt>检测模型</dt><dd class="mono">{{i.model_ref}}</dd></div>
      </dl>
      <div class="fire-actions">
       <RouterLink v-if="alertSceneRoute(i)" class="primary-button" :to="alertSceneRoute(i)!"><Box :size="15"/>查看三维火情</RouterLink>
       <button class="secondary-button" @click="choosePlant(i.plant_id)">{{alertSceneRoute(i)?'电厂详情':'查看电厂'}}</button>
      </div>
     </div>
    </div>
    <div v-else-if="connected&&noDetectionCount" class="no-detect-list">
     <div v-for="i in noDetectionItems" :key="i.run_id" class="no-detect-card">
      <strong>{{plantName(i.plant_id)}}</strong><span class="tag neutral">本次观测暂未发现火点</span>
      <span class="small muted">观测 {{observationTimeLabel(i)}} · {{originLabel(i)}}</span>
     </div>
    </div>
    <div v-else-if="connected" class="empty-state">暂无火情告警{{staleItems.length?'（历史/过期记录不计入）':''}}。</div>
    <details v-if="staleItems.length" class="fire-history"><summary>较早的火情信息（{{staleItems.length}}）</summary><ul><li v-for="i in staleItems" :key="i.run_id">{{plantName(i.plant_id)}} · 观测 {{observationTimeLabel(i)}} · {{originLabel(i)}}（信息已过期）</li></ul></details>
   </section>
   <section class="plant-list"><div class="section-heading"><h2>{{gridView?`${gridArea?.shortName??'全国'}场站`:province?`${provinceName(province)}场站`:'全国场站信息'}}<span class="count-pill">{{visiblePlants.length}}</span></h2><span class="small muted">显示 {{visiblePlants.length}} / {{currentPlants.length}} 家 · {{gridView?'按登记位置展示；不代表场站调度归属':'按登记省份筛选 · 全国数量去重'}}</span></div>
    <label class="plant-search"><Search :size="16"/><input v-model="plantSearch" type="search" placeholder="搜索电厂名称、省份或类型" aria-label="搜索当前列表中的电厂"/><button v-if="plantSearch" type="button" aria-label="清空搜索" @click="plantSearch=''" @mousedown.prevent><X :size="15"/></button></label>
    <div v-if="!dataReady&&!dataError" class="empty-state">正在读取电厂目录…</div>
    <div v-else-if="!currentPlants.length" class="empty-state"><MapPin :size="24"/><div><strong>暂无场站信息</strong><p>{{gridView?(gridArea?.name??'本区域'):provinceName(province)}}目前没有已录入的场站信息，可选择其他区域查看。</p></div></div>
    <div v-else-if="!visiblePlants.length" class="empty-state"><Search :size="22"/><div><strong>没有找到匹配的电厂</strong><p>试试其他名称、省份或电厂类型。</p></div></div>
    <div v-else class="plant-groups">
     <section v-for="group in plantGroups" :key="group.key" class="plant-group">
      <div class="plant-group-heading"><h3>{{group.label}}<span class="count-pill">{{group.plants.length}}</span></h3><span v-if="group.note" class="small muted">{{group.note}}</span></div>
      <div class="plant-grid"><button v-for="p in group.plants" :key="p.properties.plant_id" class="plant-item" :class="{chosen:selected?.properties.plant_id===p.properties.plant_id}" @click="choosePlant(p.properties.plant_id)"><span class="plant-type-icon"><Box v-if="sceneFor(p.properties.plant_id)" :size="19"/><Mountain v-else-if="referenceSceneFor(p.properties.plant_id)" :size="19"/><FlaskConical v-else-if="prototypeScenesFor(p.properties.plant_id).length" :size="19"/><MapPin v-else :size="19"/></span><span class="plant-item-text"><strong>{{p.properties.name}}</strong><span>{{p.properties.technology==='Coal'?'燃煤':'水电'}} · {{p.properties.capacity_mw?.toLocaleString()??'未知'}} MW</span></span><span v-if="sceneFor(p.properties.plant_id)" class="tag">厂区三维预览</span><span v-else-if="referenceSceneFor(p.properties.plant_id)" class="tag">周边地形预览</span><span v-if="prototypeScenesFor(p.properties.plant_id).length" class="tag">概念预览</span><ChevronRight v-if="!sceneFor(p.properties.plant_id)&&!referenceSceneFor(p.properties.plant_id)&&!prototypeScenesFor(p.properties.plant_id).length" :size="16" class="muted"/></button></div>
     </section>
    </div>
   </section>
   <footer class="atlas-footnote"><details><summary>地图来源与定位精度</summary><p>地图边界来自 GeoJSON.CN 分发文件，底图与场站坐标使用不同坐标基准且未转换。本图用于省级和区域浏览，不适用于精确测绘或判断调度边界。</p><a href="https://geojson.cn/data/atlas/tiandi" target="_blank" rel="noopener noreferrer">查看地图来源及版本说明</a></details></footer>
  </section>
  <PlantDetail v-if="selected" :plant="selected" :browse-query="browseQuery" @close="close"/>
 </main>
</template>
<style scoped>
.atlas-mode-switch{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border:1px solid var(--border);border-radius:8px;background:#091723;margin:0 0 17px}
.atlas-mode-switch button{padding:7px 5px;border-color:transparent;background:transparent;color:#9bacbc;font-size:.75rem;white-space:nowrap}
.atlas-mode-switch button.active{background:#194436;border-color:#286958;color:#8ef8d4}
.area-button>span:first-child{display:flex;flex-direction:column;gap:1px;min-width:0}
.area-button strong{font-size:.85rem;font-weight:600}
.area-button small{font-size:.67rem;color:var(--muted);line-height:1.3}
.grid-map-note{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;padding:12px 16px;border-top:1px solid #4c422d;background:#201e18;color:#e2d1a8;font-size:.75rem;line-height:1.6}
.grid-map-note strong{white-space:nowrap;color:#f1d491}
.grid-region-key{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:3px 12px;margin-top:3px;color:#c2cfdb}
.grid-region-key span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.grid-region-key i{display:inline-block;width:9px;height:9px;border-radius:2px}
.grid-source-links{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:3px}
.grid-source-links a{font-size:.72rem;color:#9ec7dd;text-decoration:underline;text-underline-offset:2px}
.grid-source-links a:hover{color:#c5e8f6}
.map-bottomline .fire-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#ff6b6b;box-shadow:0 0 6px #ff6b6b}
.fire-feedback{margin:14px 0}
.coverage-note{display:flex;align-items:flex-start;gap:9px;margin:-8px 0 12px;padding:10px 13px;border:1px solid #4c422d;border-radius:7px;background:#201e18;color:#e2d1a8;font-size:.8rem;line-height:1.5}
.coverage-note svg{flex:none;margin-top:2px;color:#f1d491}
.coverage-note strong{color:#f1d491}
.fire-overview{display:flex;align-items:center;gap:10px;margin:0 0 14px;padding:12px 15px;border:1px solid var(--border);border-radius:8px;background:#101f2e;color:#c8d6e2}
.fire-overview>svg{flex:none;color:#9bacbc}
.fire-overview>div{display:flex;align-items:baseline;gap:10px;flex:1;min-width:0}
.fire-overview>div strong{color:#e4edf6}
.fire-overview>div span{font-size:.82rem;color:var(--muted)}
.fire-overview>b{font-size:1.25rem;font-variant-numeric:tabular-nums}
.fire-overview.alert{border-color:#6b3838;background:#1a1216}
.fire-overview.alert>svg,.fire-overview.alert>b{color:#ff8b86}
.advanced-connection{margin:0 0 14px;padding:10px 13px;border:1px solid var(--border);border-radius:8px;background:#0d1a26}
.advanced-connection summary{cursor:pointer;color:#a9c0cf;font-size:.8rem;font-weight:600}
.advanced-connection>p{margin:8px 0}
.advanced-connection .run-connection{margin-top:8px}
.fire-feedback .section-heading{margin-bottom:10px}
.fire-list{display:flex;flex-wrap:wrap;gap:10px}
.fire-actions{display:flex;gap:8px;flex-wrap:wrap}
.fire-actions .primary-button{width:auto}
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
.plant-search{display:flex;align-items:center;gap:9px;max-width:440px;margin:0 0 13px;padding:0 11px;border:1px solid var(--border);border-radius:8px;background:#0d1a26;color:var(--muted)}
.plant-search:focus-within{border-color:#4b9d89;box-shadow:0 0 0 2px rgba(76,184,153,.12)}
.plant-search input{width:100%;min-width:0;padding:10px 0;border:0;outline:0;background:transparent;color:#e7eff5;font:inherit;font-size:.82rem}
.plant-search input::placeholder{color:#8193a2}
.plant-search button{display:grid;place-items:center;padding:4px;border:0;background:transparent;color:#9bacbc;cursor:pointer}
.plant-search button:hover{color:#e7eff5}
@media(max-width:640px){.plant-group-heading{align-items:flex-start;flex-direction:column;gap:4px}.plant-group-heading>.small{text-align:left}}
@media(max-width:640px){.atlas-mode-switch{margin-bottom:10px;max-width:380px}.grid-map-note{grid-template-columns:1fr;gap:4px;padding:10px 12px}.grid-region-key,.grid-source-links{grid-column:1;gap:4px 10px}.coverage-note{margin-top:-4px}.fire-overview{align-items:flex-start}.fire-overview>div{display:flex;flex-direction:column;gap:2px}.fire-overview>b{font-size:1.05rem}}
</style>
