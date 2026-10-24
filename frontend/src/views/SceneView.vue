<script setup lang="ts">
import { computed,onMounted,ref,shallowRef } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft,Mountain,Focus,RotateCcw,MousePointer2,Info,ExternalLink,Box,ShieldQuestion,Play,Pause,X,Flame } from 'lucide-vue-next'
import SceneCanvas from '../components/SceneCanvas.vue'
import { loadCatalog,dataReady,dataError,sceneBySceneId,assetUrl,plants,heightLabel,identityLabel } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import type { ReferenceMarker,SceneProfile,SceneObject } from '../lib/types'
const route=useRoute();const sceneCanvas=ref<InstanceType<typeof SceneCanvas>>();const profile=shallowRef<SceneProfile|null>(null)
const objects=shallowRef<SceneObject[]>([]),markers=shallowRef<ReferenceMarker[]>([]),selected=shallowRef<SceneObject|null>(null),error=ref(''),attempt=ref(0)
const renderMode=ref<'webgl'|'software'>('webgl')
const {status,t_s,dataState,loadError,demo,activeFirePatches,isDemoOn,playing,demoDisabled,play,pause,reset,close,load}=useFireDemo()
const sceneLink=computed(()=>sceneBySceneId(String(route.params.sceneId)))
const plant=computed(()=>sceneLink.value?plants.value.find(p=>p.properties.plant_id===sceneLink.value!.plant_id):undefined)
const valid=computed(()=>!!sceneLink.value)
const isZhijinDemo=computed(()=>sceneLink.value?.scene_id==='zhijin_pilot')
const firePatches=computed(()=>isZhijinDemo.value?activeFirePatches.value:[])
const backQuery=computed(()=>({...(plant.value?{province:plant.value.properties.province_code}:{}),plant:sceneLink.value?.plant_id??''}))
const statsText=computed(()=>{
 const a=profile.value?.asset;if(!a)return ''
 const parts:string[]=[]
 if(a.object_meshes!=null)parts.push(`${a.object_meshes} 个对象`)
 if(a.triangles!=null)parts.push(`${a.triangles.toLocaleString()} 个三角形`)
 else if(a.vertex_count!=null)parts.push(`${a.vertex_count.toLocaleString()} 个顶点`)
 return parts.join(' · ')
})
function loaded(p:SceneProfile,o:SceneObject[],m:ReferenceMarker[]){profile.value=p;objects.value=o;markers.value=m;error.value=''}
function retry(){profile.value=null;objects.value=[];markers.value=[];selected.value=null;error.value='';attempt.value++}
function choose(event:Event){sceneCanvas.value?.select((event.target as HTMLSelectElement).value||null,true)}
onMounted(()=>{loadCatalog();load()})
</script>
<template>
 <main class="scene-layout">
  <header class="scene-heading"><div><RouterLink class="back-link" :to="{path:'/atlas',query:backQuery}"><ArrowLeft :size="16"/>返回电厂详情</RouterLink><h1>{{profile?.display_name??'正在读取场景'}}<span v-if="profile" class="tag">{{profile.scene_badge}}</span></h1><p v-if="plant">{{plant.properties.name}} · {{plant.properties.source_province}}</p></div><div v-if="profile?.study_area_stat" class="scene-size"><strong>{{profile.study_area_stat}}</strong></div></header>
  <div class="scene-workspace">
   <section class="viewer-frame">
    <SceneCanvas v-if="dataReady&&valid&&sceneLink" :key="attempt" ref="sceneCanvas" :profile-url="assetUrl(sceneLink.profile_uri)" :fire-patches="firePatches" @loaded="loaded" @selected="selected=$event" @error="error=$event" @mode="renderMode=$event"/>
    <div v-else class="loader-overlay" role="status"><h3>{{dataError||(dataReady?'场景不存在':'正在读取场景索引')}}</h3><button v-if="dataError" @click="loadCatalog">重试目录</button></div>
    <div v-if="profile" class="viewer-toolbar"><button v-if="profile.cameras.plant" @click="sceneCanvas?.frame('plant')"><Focus :size="17"/>厂区取景</button><button v-if="profile.cameras.whole_terrain" @click="sceneCanvas?.frame('whole_terrain')"><Mountain :size="17"/>全域地形</button><button v-if="!profile.cameras.whole_terrain" @click="sceneCanvas?.frame('panorama')"><Mountain :size="17"/>全景</button><button @click="sceneCanvas?.frame('default')" title="恢复初始取景"><RotateCcw :size="17"/>恢复默认视角</button></div>
    <div class="viewer-badges"><template v-if="isZhijinDemo"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>尚未接入火情</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>演示告警 · 合成</span><span v-else class="tag amber">演示中 · 当前无演示火区</span></template><span v-else class="tag amber">正式模型待接入</span><span class="tag neutral">高程示意色 · 非植被或火险</span></div>
    <div class="viewer-bottom"><span><MousePointer2 :size="14"/>拖动旋转 · 滚轮缩放 · 右键平移</span><span class="axis-label">X 东 · Y 上 · Z 南 / 米</span></div>
   </section>
   <aside class="scene-inspector">
    <div class="panel-eyebrow">场景检查<Box :size="16"/></div>
    <div v-if="profile" class="loaded-status">{{profile.display_name}}已加载<span>{{statsText}}</span></div>
    <p v-if="profile?.ui_notice" class="notice amber">{{profile.ui_notice}}</p>
    <p v-if="renderMode==='software'" class="notice amber">当前浏览器不支持 WebGL，已使用兼容显示。地形为原始顶点粗采样，光照为近似效果；GPU 渲染与性能尚待验证。<template v-if="isZhijinDemo&&activeFirePatches.length">兼容模式不支持火区覆盖层显示，演示告警仅同步至地图与详情。</template><template v-if="profile?.capabilities.reference_markers">兼容模式不渲染参考标记。</template></p>
    <div v-if="!profile" class="notice" :class="{error:!!error}">{{error?'模型暂不可用':'正在加载场景资源'}}<button v-if="error" class="secondary-button" @click="retry">重新加载</button></div>
    <section v-if="isZhijinDemo" class="demo-panel">
     <div class="panel-eyebrow">演示火情<Flame :size="16"/></div>
     <div v-if="demoDisabled" class="notice amber"><ShieldQuestion :size="14"/>合成火情演示暂不可用：覆盖层回归未通过（播放超 50 秒未见火区，原因未定位）。本轮已暂停演示入口，叠加能力保留供未来复用。</div>
     <p v-else-if="dataState==='loading'" class="small muted">正在读取演示数据…</p>
     <div v-else-if="dataState==='unavailable'" class="notice error">演示数据不可用<template v-if="loadError">：{{loadError}}</template></div>
     <template v-else-if="dataState==='ready'">
      <div class="demo-status"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>尚未接入火情</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>演示告警 · 合成</span><span v-else class="tag amber">演示中 · 当前无演示火区</span><span class="demo-time">{{t_s.toFixed(1)}} / {{demo?.duration_s??0}} s</span></div>
      <div class="demo-controls"><button v-if="!isDemoOn" @click="play"><Flame :size="14"/>开启演示</button><template v-else><button @click="play" :disabled="status==='ended'"><Play :size="14"/>播放</button><button @click="pause" :disabled="!playing"><Pause :size="14"/>暂停</button><button @click="reset"><RotateCcw :size="14"/>重置</button><button @click="close"><X :size="14"/>关闭</button></template></div>
      <p class="small muted">合成示例，非真实火情、非算法识别、非经验证风险评估。</p>
     </template>
    </section>
    <section v-if="profile?.capabilities.reference_markers&&markers.length" class="markers-panel">
     <div class="panel-eyebrow">参考标记</div>
     <p class="small muted">三个公开地图参考点；高度为参考表面 +1m 显示偏移，非设施实测高度。</p>
     <ul class="marker-list">
      <li v-for="m in markers" :key="m.marker_id"><div class="marker-line"><strong>{{m.label}}</strong></div><p class="small muted coord">{{m.lon_lat_wgs84[0]}}, {{m.lon_lat_wgs84[1]}}（WGS84）</p><p class="small muted">局部 {{m.local_xyz_m.map(v=>v.toFixed(1)).join(', ')}} m</p></li>
     </ul>
    </section>
    <template v-if="profile?.capabilities.object_selection">
     <label class="object-label" for="object-select">定位对象</label><select id="object-select" :value="selected?.object_id??''" :disabled="!profile" @change="choose"><option value="">选择对象，或在模型上单击</option><option v-for="o in objects" :key="o.object_id" :value="o.object_id">{{o.object_id}} · {{o.display_name}}</option></select>
     <section v-if="selected" class="object-detail"><div class="object-code">{{selected.object_id}}</div><h2>{{selected.display_name}}</h2><div class="tags"><span class="tag amber">{{selected.object_id==='terrain'?'估计地形层':identityLabel(selected.identity_status)}}</span><span class="tag neutral">{{heightLabel(selected)}}</span></div>
      <dl class="facts"><div v-if="selected.display_height_m!==undefined"><dt>模型显示高度</dt><dd>{{selected.display_height_m.toFixed(2)}} m</dd></div><div v-if="selected.original_GBA_height_prediction_m!==undefined"><dt>原始 GBA 高度预测</dt><dd>{{selected.original_GBA_height_prediction_m.toFixed(2)}} m</dd></div><div><dt>火险评估</dt><dd>尚未接入</dd></div></dl>
      <p v-if="selected.object_id==='B01'" class="notice amber">30 m 拱顶为展示假设；原始约 7.30 m 预测独立保留。设施身份尚未确认。</p>
      <p v-else-if="selected.object_id==='CH01'" class="notice">240 m 为报告记载；外径与收分仍为展示假设，非本次实测。</p>
      <p v-else-if="selected.object_id.startsWith('CT-')" class="notice amber">150 m 为展示假设；塔壳、支撑与平台均未完成实地核验。</p>
      <p v-else-if="selected.object_id==='terrain'" class="notice">混合来源高程与人工估计平台，无卫星贴图。颜色不代表真实地表类型或风险。</p>
      <p v-else class="small muted">建筑轮廓与高度来自候选资料；设施功能、位置与地面高程均待独立核验。</p>
      <details><summary>原始证据字段</summary><p class="small">身份：{{selected.identity_status}}</p><p class="small">高度：{{selected.height_status}}</p><p class="small">位置：{{selected.position_status}}</p><p v-if="selected.shape_status" class="small">外形：{{selected.shape_status}}</p></details>
     </section>
     <div v-else class="object-placeholder"><MousePointer2 :size="27"/><h3>查看设施证据</h3><p>选择厂区设施，查看对象身份、显示高度与资料依据。</p></div>
    </template>
    <section class="scene-notes"><h3><Info :size="15"/>使用范围</h3><p v-if="profile?.study_area_note">{{profile.study_area_note}}</p><p v-if="profile?.coordinate_note">{{profile.coordinate_note}}</p><details><summary>数据来源与署名</summary><div v-for="s in profile?.sources_and_attribution" :key="s.name" class="attribution"><a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{s.name}}<ExternalLink :size="12"/></a><span v-else>{{s.name}}</span><p class="small muted">{{s.licence??s.attribution??s.notice??'原交接资料参考'}}</p></div></details><details v-if="profile?.limitations?.length"><summary>限制说明</summary><ul class="limits"><li v-for="(l,i) in profile.limitations" :key="i" class="small muted">{{l}}</li></ul></details></section>
   </aside>
  </div>
 </main>
</template>
<style scoped>
.demo-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin-top:16px;background:#122436}
.demo-panel .panel-eyebrow{margin-bottom:10px}
.demo-status{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.demo-time{font-variant-numeric:tabular-nums;font-size:.8125rem;color:#a9c0cf}
.demo-controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}
.demo-controls button{display:inline-flex;align-items:center;gap:5px;font-size:.8125rem;padding:7px 10px}
.markers-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin-top:16px;background:#0d1a26}
.markers-panel .panel-eyebrow{margin-bottom:10px}
.marker-list{list-style:none;margin:10px 0 0;padding:0}
.marker-list li{border-top:1px solid var(--border);padding:8px 0}
.marker-list li:first-child{border-top:0;padding-top:2px}
.marker-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.marker-list .coord{font-variant-numeric:tabular-nums}
.limits{list-style:disc;margin:8px 0 0 18px;padding:0}
</style>
