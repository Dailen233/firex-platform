<script setup lang="ts">
import { computed,onMounted } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { MapPin,Box,Layers,Info,Compass,ChevronRight } from 'lucide-vue-next'
import ProvinceMap from '../components/ProvinceMap.vue'
import PlantDetail from '../components/PlantDetail.vue'
import { plants,boundaries,boundaryLines,dataReady,dataError,boundaryError,loadCatalog,relatedPlants,sceneFor } from '../lib/data'
import { provinces,provinceName } from '../lib/provinces'
const route=useRoute();const router=useRouter()
const province=computed(()=>provinces.some(p=>p[0]===route.query.province)?String(route.query.province):'')
const currentPlants=computed(()=>province.value?relatedPlants(province.value):plants.value)
const selected=computed(()=>currentPlants.value.find(p=>p.properties.plant_id===route.query.plant))
function chooseProvince(code:string){router.push({path:'/atlas',query:code?{province:code}:{}})}
function choosePlant(id:string){router.push({path:'/atlas',query:{...(province.value?{province:province.value}:{}),plant:id}})}
function close(){router.push({path:'/atlas',query:province.value?{province:province.value}:{}})}
onMounted(loadCatalog)
</script>
<template>
 <main class="atlas-layout">
  <aside class="province-panel">
   <div class="panel-eyebrow">区域目录<Layers :size="16"/></div><h2>按省份浏览</h2><p class="small muted">跨省电站在关联省份重复展示</p>
   <button class="province-button national" :class="{selected:!province}" @click="chooseProvince('')"><span>全国样例</span><b>{{plants.length}}</b></button>
   <div class="province-scroll"><template v-for="(p,index) in provinces" :key="p[0]"><div v-if="index===3" class="divider-label">其他省级地区</div><button class="province-button" :class="{selected:province===p[0]}" @click="chooseProvince(p[0])" :aria-pressed="province===p[0]"><span>{{p[1]}}</span><b v-if="relatedPlants(p[0]).length">{{relatedPlants(p[0]).length}}</b><span v-else class="province-empty">—</span></button></template></div>
   <div class="province-footer"><Info :size="15"/><span>7 个样例，非全国电厂清单。<br/>无样例不代表当地没有电厂。</span></div>
  </aside>
  <section class="atlas-workspace">
   <div class="workspace-heading"><div><div class="eyebrow">电厂与山地场景 / ATLAS</div><h1>{{provinceName(province)}}<span>电厂总览</span></h1></div><div class="overview-stats"><div><strong>7</strong><span>唯一电厂样例</span></div><div><strong>1</strong><span>三维试建场景</span></div><div><strong>34</strong><span>省级地区</span></div></div></div>
   <div v-if="dataError" class="notice error" role="alert">{{dataError}}<button @click="loadCatalog">重新读取</button></div>
   <div class="map-section">
    <div class="map-topline"><span><Compass :size="16"/>中国省级地图</span><span class="small muted">点击省份或电厂点位 · 滚轮缩放</span></div>
    <ProvinceMap v-if="boundaries && dataReady" :boundaries="boundaries" :lines="boundaryLines" :plants="plants" :province="province" :selected-plant="selected?.properties.plant_id??''" @province="chooseProvince" @plant="choosePlant"/>
    <div v-else class="map-empty"><Layers :size="36"/><h3>{{boundaryError?'地图资源暂不可用':'正在读取省级地图'}}</h3><p>{{boundaryError?'可继续通过左侧省份列表浏览电厂与模型。':'加载本地边界文件与电厂样例。'}}</p><button v-if="boundaryError" @click="loadCatalog">重新读取地图</button></div>
    <div class="map-bottomline"><span><span class="sample-dot"></span>点位仅表示电厂样例，不表示火情</span><span>火情监测尚未接入</span></div>
   </div>
   <section class="plant-list"><div class="section-heading"><h2>{{province?`${provinceName(province)}关联电厂`:'全国电厂样例'}}<span class="count-pill">{{currentPlants.length}}</span></h2><span class="small muted">按项目 ID 关联 · 全国数量去重</span></div>
    <div v-if="!dataReady&&!dataError" class="empty-state">正在读取电厂目录…</div>
    <div v-else-if="!currentPlants.length" class="empty-state"><MapPin :size="24"/><div><strong>暂无样例数据</strong><p>{{provinceName(province)}}尚未收录电厂样例，可选择贵州、四川或云南继续浏览。</p></div></div>
    <div v-else class="plant-grid"><button v-for="p in currentPlants" :key="p.properties.plant_id" class="plant-item" :class="{chosen:selected?.properties.plant_id===p.properties.plant_id}" @click="choosePlant(p.properties.plant_id)"><span class="plant-type-icon"><Box v-if="sceneFor(p.properties.plant_id)" :size="19"/><MapPin v-else :size="19"/></span><span class="plant-item-text"><strong>{{p.properties.name}}</strong><span>{{p.properties.technology==='Coal'?'燃煤':'水电'}} · {{p.properties.capacity_mw?.toLocaleString()??'未知'}} MW</span></span><span v-if="sceneFor(p.properties.plant_id)" class="tag">三维试建</span><ChevronRight v-else :size="16" class="muted"/></button></div>
   </section>
   <footer class="atlas-footnote"><details><summary>地图来源与精度说明</summary><p>GeoJSON.CN 第三方分发与转换，来源页注明天地图；2026-10-09 取得 34 个省级面与 8 个境界线要素。底图 CGCS2000 / EPSG:4490，点位 WGS84 / EPSG:4326，未进行坐标基准转换。本轮为省级浏览，不代表米级地理配准验收。</p><a href="https://geojson.cn/data/atlas/tiandi" target="_blank" rel="noopener noreferrer">来源及版本说明</a></details></footer>
  </section>
  <PlantDetail v-if="selected" :plant="selected" :province="province" @close="close"/>
 </main>
</template>
