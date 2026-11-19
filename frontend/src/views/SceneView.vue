<script setup lang="ts">
import { computed,nextTick,onBeforeUnmount,onMounted,ref,shallowRef,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { ArrowLeft,Mountain,Focus,RotateCcw,MousePointer2,Info,ExternalLink,Box,ShieldQuestion,Play,Pause,X,Flame,Plus } from 'lucide-vue-next'
import SceneCanvas from '../components/SceneCanvas.vue'
import SjkGridPanel from '../components/SjkGridPanel.vue'
import MultiviewReplayPanel from '../components/MultiviewReplayPanel.vue'
import ReconstructionFollowPanel from '../components/ReconstructionFollowPanel.vue'
import PlantPreviewPanel from '../components/PlantPreviewPanel.vue'
import { supportsSjkCorridor,type GridSummary } from '../lib/sjk-grid'
import RunConnectionPanel from '../components/RunConnectionPanel.vue'
import { loadCatalog,dataReady,dataError,sceneBySceneId,assetUrl,plants,heightLabel,identityLabel } from '../lib/data'
import { useFireDemo } from '../lib/fire-demo'
import { useRunConnection } from '../lib/run-connection'
import { createRun, snapshotToActiveFirePatches } from '../lib/backend'
import type { ActiveFirePatch,ReferenceMarker,SceneProfile,SceneObject } from '../lib/types'
import type { LocalRegistrationPointResult } from '../lib/dev/sjk-local-registration'
const route=useRoute();const router=useRouter();const sceneCanvas=ref<InstanceType<typeof SceneCanvas>>();const profile=shallowRef<SceneProfile|null>(null)
const objects=shallowRef<SceneObject[]>([]),markers=shallowRef<ReferenceMarker[]>([]),selected=shallowRef<SceneObject|null>(null),error=ref(''),attempt=ref(0)
const renderMode=ref<'webgl'|'software'>('webgl'),overlayIssue=ref<string|null>('')
const {status,t_s,dataState,loadError,demo,activeFirePatches,isDemoOn,playing,demoDisabled,play,pause,reset,close,load}=useFireDemo()
const conn=useRunConnection()
const sceneLink=computed(()=>sceneBySceneId(String(route.params.sceneId)))
const alertRunId=computed(()=>typeof route.query.run_id==='string'?route.query.run_id.trim():'')
let ownedRunId=''
function releaseAlertConnection(){
 if(ownedRunId&&conn.runId.value===ownedRunId)conn.disconnect()
 ownedRunId=''
}
function connectAlert(){
 const id=alertRunId.value
 if(!sceneLink.value||!id)return
 if(conn.runId.value===id&&(conn.status.value==='connecting'||conn.status.value==='connected'))return
 ownedRunId=id
 void conn.connect(id)
}
// 新建重建运行：从当前已加载的双江口场景配置创建 run，成功后写入链接并自动连接。
const creatingRun=ref(false)
const createRunError=ref('')
async function createReconstructionRun(){
 if(creatingRun.value||!profile.value)return
 const p=profile.value
 if(!p.coordinate_frame_id){createRunError.value='当前场景缺少坐标参考系，无法创建运行。';return}
 creatingRun.value=true
 createRunError.value=''
 try{
  const rec=await createRun({
   plant_id:p.plant_id,
   scene_id:p.scene_id,
   asset_version:p.asset_version,
   coordinate_frame_id:p.coordinate_frame_id,
   input_source:'simulation',
   simulation_time_origin_s:0.0,
  })
  // 写入链接 run_id，触发 connectAlert 自动连接；此后刷新/重开都能回到同一次运行。
  await router.replace({query:{...route.query,run_id:rec.run_id}})
 }catch(e){
  createRunError.value=`创建运行失败：${e instanceof Error?e.message:String(e)}`
 }finally{
  creatingRun.value=false
 }
}
watch([alertRunId,sceneLink],([id,link])=>{
 if(ownedRunId&&(id!==ownedRunId||!link))releaseAlertConnection()
 if(link&&id)connectAlert()
},{immediate:true})
onBeforeUnmount(releaseAlertConnection)
// 场景切换时强制重挂载画布：释放旧几何/材质/贴图/事件并取消旧请求，避免旧加载覆盖新选择。
const canvasKey=computed(()=>`${sceneLink.value?.scene_id ?? ''}:${attempt.value}`)
const plant=computed(()=>sceneLink.value?plants.value.find(p=>p.properties.plant_id===sceneLink.value!.plant_id):undefined)
const valid=computed(()=>!!sceneLink.value)
const isZhijinDemo=computed(()=>sceneLink.value?.scene_id==='zhijin_pilot')
const isPrototypeDraft=computed(()=>sceneLink.value?.asset_role==='prototype_model')
// E3.1 仅开发态可见的本地落点核验入口（只对 sjk_hydropower_sim_v0_1）。
const isDev=import.meta.env.DEV
const isSjkSim=computed(()=>sceneLink.value?.scene_id==='sjk_hydropower_sim_v0_1')
const gridAvailable=computed(()=>profile.value!==null&&supportsSjkCorridor(profile.value))
const gridVisible=ref(false),gridIssue=ref('')
const gridSummary=shallowRef<GridSummary|null>(null)
function toggleGrid(){
 const show=!gridVisible.value
 gridIssue.value=''
 try{
  const summary=sceneCanvas.value?.setGridVisible(show)
  if(show&&!summary){gridIssue.value='当前场景无法显示仿真塔线。';return}
  if(summary)gridSummary.value=summary
  gridVisible.value=show
  if(show)sceneCanvas.value?.focusGrid('station')
 }catch(e){gridIssue.value=e instanceof Error?e.message:'仿真塔线加载失败。'}
}
const checkResults=ref<LocalRegistrationPointResult[]>([])
const fmt3=(v:[number,number,number])=>v.map(n=>n.toFixed(3)).join(', ')
function runCheck(){checkResults.value=sceneCanvas.value?.runLocalRegistrationCheck()??[]}
const requestedSnapshot=computed(()=>{
 const snap=conn.snapshot.value
 return snap&&(!alertRunId.value||snap.run_id===alertRunId.value)?snap:null
})
// Backend snapshot -> overlay patches, only when the run binds to the current scene.
const runPatches=computed(()=>{
 const snap=requestedSnapshot.value
 if(!snap||!profile.value)return {patches:[] as ActiveFirePatch[],bindingError:null as string|null}
 return snapshotToActiveFirePatches(snap,{plant_id:profile.value.plant_id,scene_id:profile.value.scene_id,asset_version:profile.value.asset_version,coordinate_frame_id:profile.value.coordinate_frame_id})
})
const bindingError=computed(()=>runPatches.value.bindingError)
const firePatches=computed(()=>isZhijinDemo.value?activeFirePatches.value:runPatches.value.patches)
const latestObservation=computed(()=>{
 const s=requestedSnapshot.value,p=profile.value
 if(!s||!p||s.plant_id!==p.plant_id||s.scene_id!==p.scene_id||s.asset_version!==p.asset_version
   ||!p.coordinate_frame_id||s.coordinate_frame_id!==p.coordinate_frame_id)return null
 return s
})
const observationExpired=ref(false)
watch(()=>latestObservation.value?.observation_expires_at,(deadline,_,onCleanup)=>{
 const remaining=deadline?Date.parse(deadline)-Date.now():Infinity
 observationExpired.value=remaining<=0
 if(remaining>0&&Number.isFinite(remaining)){
  const timer=window.setTimeout(()=>{observationExpired.value=true},remaining)
  onCleanup(()=>window.clearTimeout(timer))
 }
},{immediate:true})
const latestFlame=computed(()=>latestObservation.value?.flame??null)
const flameEstimate=computed(()=>{
 const flame=latestFlame.value
 return flame&&!observationExpired.value&&flame.glb_sha256===profile.value?.asset?.sha256?flame:null
})
// 离线重建回放或跟随服务端期间临时隐藏实时单帧火焰图层，退出后恢复。
const replayActive=ref(false)
const followActive=ref(false)
const effectiveFlameEstimate=computed(()=>(replayActive.value||followActive.value)?null:flameEstimate.value)
function onReplayVoxels(points:Float32Array|null,voxelSizeM:number){sceneCanvas.value?.setVoxelLayer(points,voxelSizeM)}
function onReplayActive(a:boolean){replayActive.value=a}
function onFollowVoxels(points:Float32Array|null,voxelSizeM:number){sceneCanvas.value?.setVoxelLayer(points,voxelSizeM)}
function onFollowActive(a:boolean){followActive.value=a}
function onPlantPreviewToggle(visible:boolean){sceneCanvas.value?.setPlantPreviewVisible(visible)}
function onPlantPreviewFocus(view:'oblique'|'top'){sceneCanvas.value?.framePlantPreview(view)}
const flameStatus=computed(()=>{
 if(!latestObservation.value){
  if(bindingError.value)return '运行与当前三维场景不匹配。'
  if(conn.error.value&&alertRunId.value)return '未能读取火情观测。'
  return alertRunId.value?'正在连接火情观测…':'等待火情观测。'
 }
 if(latestObservation.value.state_status!=='observation')return '等待该次运行的首帧观测。'
 if(observationExpired.value)return '最近一帧已过期，等待新观测。'
 if(latestObservation.value.result_origin!=='yolo')return '接口测试数据未生成火焰剖面。'
 if(latestObservation.value.fire_detected===false)return '本帧未检出火焰，不代表已熄灭。'
 if(latestFlame.value&&!flameEstimate.value)return '火焰剖面与当前模型版本不符。'
 if(!flameEstimate.value)return '已检出火焰，当前帧没有可用的三维剖面。'
 if(renderMode.value==='software')return '当前浏览器不支持显示火焰剖面。'
 return '已显示单视角火焰剖面'
})
function focusFire(){sceneCanvas.value?.focusFire()}
function focusFlame(){sceneCanvas.value?.focusFlame()}
let focusedKey=''
watch([flameEstimate,canvasKey,alertRunId],async([f,key,id])=>{
 if(!f||!id||renderMode.value!=='webgl')return
 const focusKey=`${key}:${id}`
 if(focusedKey===focusKey)return
 await nextTick()
 if(flameEstimate.value!==f)return
 focusedKey=focusKey
 focusFlame()
})
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
function resetSceneState(){
 profile.value=null;objects.value=[];markers.value=[];selected.value=null;error.value=''
 gridVisible.value=false;gridIssue.value='';gridSummary.value=null
}
function retry(){resetSceneState();attempt.value++}
// 场景切换（scene_id 变化）时清空上一场景状态，避免旧 profile/对象残留到新场景的加载或失败画面。
watch(()=>String(route.params.sceneId),()=>resetSceneState())
function choose(event:Event){sceneCanvas.value?.select((event.target as HTMLSelectElement).value||null,true)}
onMounted(()=>{loadCatalog();load()})
</script>
<template>
 <main class="scene-layout">
  <header class="scene-heading"><div><RouterLink class="back-link" :to="{path:'/atlas',query:backQuery}"><ArrowLeft :size="16"/>返回电厂详情</RouterLink><h1>{{profile?.display_name??'正在读取场景'}}<span v-if="profile" class="tag">{{profile.scene_badge}}</span></h1><p v-if="plant">{{plant.properties.name}} · {{plant.properties.source_province}}</p></div><div v-if="profile?.study_area_stat" class="scene-size"><strong>{{profile.study_area_stat}}</strong></div></header>
  <div class="scene-workspace">
   <section class="viewer-frame">
    <SceneCanvas v-if="dataReady&&valid&&sceneLink" :key="canvasKey" ref="sceneCanvas" :profile-url="assetUrl(sceneLink.profile_uri)" :fire-patches="firePatches" :flame-estimate="effectiveFlameEstimate" @loaded="loaded" @selected="selected=$event" @error="error=$event" @mode="renderMode=$event" @overlay-issue="overlayIssue=$event"/>
    <div v-else class="loader-overlay" role="status"><h3>{{dataError||(dataReady?'场景不存在':'正在读取场景索引')}}</h3><button v-if="dataError" @click="loadCatalog">重新加载目录</button></div>
    <div v-if="profile" class="viewer-toolbar"><button v-if="flameEstimate&&renderMode==='webgl'" @click="focusFlame"><Flame :size="17"/>聚焦火焰</button><button v-if="!isZhijinDemo&&firePatches.length" @click="focusFire"><Flame :size="17"/>聚焦火区</button><button v-if="profile.cameras.plant" @click="sceneCanvas?.frame('plant')"><Focus :size="17"/>厂区取景</button><button v-if="profile.cameras.whole_terrain" @click="sceneCanvas?.frame('whole_terrain')"><Mountain :size="17"/>全域地形</button><button v-if="!profile.cameras.whole_terrain" @click="sceneCanvas?.frame('panorama')"><Mountain :size="17"/>全景</button><button @click="sceneCanvas?.frame('default')" title="恢复初始取景"><RotateCcw :size="17"/>恢复默认视角</button></div>
    <div class="viewer-badges"><span v-if="gridVisible" class="tag neutral">仿真塔线 · 非实际走向</span><span v-if="flameEstimate&&renderMode==='webgl'" class="tag danger"><Flame :size="13"/>单视角火焰剖面</span><template v-if="isZhijinDemo"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>火情数据未接入</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>数据来源：仿真</span><span v-else class="tag amber">回放中 · 当前无火区</span></template><span v-else-if="profile?.asset_role==='prototype_model'" class="tag amber">{{profile.scene_badge}}</span><span v-else class="tag amber">正式模型待接入</span><span v-if="profile?.terrain_mesh_name" class="tag neutral">高程示意色 · 非植被或火险</span></div>
    <div class="viewer-bottom"><span><MousePointer2 :size="14"/>拖动旋转 · 滚轮缩放 · 右键平移</span><span class="axis-label" :title="isSjkSim?'Unity 与此模型的局部坐标可对齐；真实经纬度、北向和高程基准尚未核准。':undefined">{{isSjkSim?'局部坐标（米）· 未做地理配准':isPrototypeDraft?'文件米制轴 · 地理方向待核实 / 米':'X 东 · Y 上 · Z 南 / 米'}}</span></div>
   </section>
   <aside class="scene-inspector">
    <section v-if="alertRunId||isSjkSim" class="demo-panel" aria-live="polite">
     <div class="panel-eyebrow">火情观测<Flame :size="16"/></div>
     <p class="live-flame-status">{{flameStatus}}</p>
     <p v-if="(alertRunId||latestObservation)&&conn.error.value" class="small muted">{{latestObservation?'观测连接异常，保留最近有效的结果。':'未能连接观测。'}}</p>
     <button v-if="alertRunId&&(conn.status.value==='error'||conn.status.value==='disconnected'||conn.runId.value!==alertRunId)"
         class="secondary-button" @click="connectAlert">重新连接观测</button>
     <p v-if="latestObservation?.observation_time_s!=null" class="small muted">观测 {{conn.observationTimeLabel.value}} · {{latestObservation.input_source==='simulation'?'数据来源：仿真':'数据来源：现场影像'}}</p>
     <p v-if="flameEstimate" class="small muted">随新抓拍更新；落点为估计值，火焰深度未测。地形与厂区仍使用已有模型。</p>
    </section>
    <PlantPreviewPanel v-if="isSjkSim" :profile="profile" @toggle="onPlantPreviewToggle" @focus="onPlantPreviewFocus" />
    <SjkGridPanel v-if="gridAvailable" :visible="gridVisible" :webgl="renderMode==='webgl'" :summary="gridSummary" :issue="gridIssue"
       @toggle="toggleGrid" @focus="sceneCanvas?.focusGrid($event)" />
    <MultiviewReplayPanel v-if="isSjkSim" :profile="profile" :disabled="followActive" @voxels="onReplayVoxels" @active="onReplayActive" />
    <ReconstructionFollowPanel v-if="isSjkSim" :profile="profile" :run-id="alertRunId" :run="conn.run.value" :disabled="replayActive" @voxels="onFollowVoxels" @active="onFollowActive" />
    <section v-if="isSjkSim" class="create-run-panel">
      <div class="panel-eyebrow">新建重建运行<Plus :size="16"/></div>
      <p class="small muted">从当前双江口场景配置创建一次重建运行并自动连接，run_id 写入当前链接（刷新或重开可回到同一次运行）。</p>
      <button class="primary-button" :disabled="!profile || creatingRun" @click="createReconstructionRun">
        {{ creatingRun ? '创建中…' : '新建重建运行' }}
      </button>
      <p v-if="createRunError" class="notice error" role="alert">{{ createRunError }}</p>
    </section>
    <details v-if="alertRunId" class="connection-details"><summary>观测连接详情</summary><RunConnectionPanel/></details>
    <RunConnectionPanel v-else/>
    <div v-if="bindingError" class="notice error" role="alert">{{bindingError}}</div>
    <div v-if="overlayIssue" class="notice amber" role="status">{{overlayIssue}}</div>
    <section v-if="isDev&&isSjkSim" class="dev-panel">
     <div class="panel-eyebrow">本地落点核验（仅开发态）<Box :size="16"/></div>
     <p class="small muted">按 sjk_local_registration_v1.json 的 unity_world_to_glb 转换 P5/P6，只对地形网格 team_fbx_terrain_129 做垂直射线检测。</p>
     <button class="secondary-button" :disabled="!profile" @click="runCheck">核验 P5 / P6 落点</button>
     <ul v-if="checkResults.length" class="check-list">
      <li v-for="r in checkResults" :key="r.id" class="check-item" :data-point-id="r.id">
       <strong>{{r.id}}</strong>
       <div class="small muted">转换点（GLB m）：<span class="mono cv">{{fmt3(r.converted_glb_xyz)}}</span></div>
       <div class="small muted">命中点（GLB m）：<span class="mono hit">{{r.hit_glb_xyz?fmt3(r.hit_glb_xyz):'未命中'}}</span></div>
       <div class="small muted">矩阵残差 <span class="mono mres">{{r.matrix_residual_m.toExponential(3)}}</span> m · 射线残差 <span class="mono rres">{{r.raycast_residual_m==null?'—':r.raycast_residual_m.toExponential(3)}}</span> m</div>
       <div v-if="r.id==='P6'" class="small" :class="r.x_axis_reversed?'check-pass':'check-fail'">X 轴反向：{{r.x_axis_reversed?'已验证（glb X = +2500 m = −(mesh_local X)）':'未通过'}}</div>
      </li>
     </ul>
    </section>
    <div class="panel-eyebrow">场景检查<Box :size="16"/></div>
    <div v-if="profile" class="loaded-status">{{profile.display_name}}已加载<span>{{statsText}}</span></div>
    <p v-if="profile?.ui_notice" class="notice amber">{{profile.ui_notice}}</p>
    <p v-if="renderMode==='software'" class="notice amber">当前浏览器不支持 WebGL，已使用兼容显示。地形为原始顶点粗采样，光照为近似效果；GPU 渲染与性能尚待验证。<template v-if="isZhijinDemo&&activeFirePatches.length">兼容模式不支持火区覆盖层显示，火情告警仅同步至地图与详情。</template><template v-if="profile?.capabilities.reference_markers">兼容模式不渲染参考标记。</template></p>
    <div v-if="!profile" class="notice" :class="{error:!!error}">{{error?'模型加载失败':'正在加载场景资源'}}<button v-if="error" class="secondary-button" @click="retry">重新加载</button></div>
    <section v-if="isZhijinDemo" class="demo-panel">
     <div class="panel-eyebrow">火情回放<Flame :size="16"/></div>
     <div v-if="demoDisabled" class="notice amber"><ShieldQuestion :size="14"/>当前场景暂不支持显示火区。</div>
     <p v-else-if="dataState==='loading'" class="small muted">正在读取回放数据…</p>
     <div v-else-if="dataState==='unavailable'" class="notice error">回放数据不可用<button class="secondary-button" @click="load">重新加载</button></div>
     <template v-else-if="dataState==='ready'">
      <div class="demo-status"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>火情数据未接入</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>数据来源：仿真</span><span v-else class="tag amber">回放中 · 当前无火区</span><span class="demo-time">{{t_s.toFixed(1)}} / {{demo?.duration_s??0}} s</span></div>
      <div class="demo-controls"><button v-if="!isDemoOn" @click="play"><Flame :size="14"/>开始回放</button><template v-else><button @click="play" :disabled="status==='ended'"><Play :size="14"/>播放</button><button @click="pause" :disabled="!playing"><Pause :size="14"/>暂停</button><button @click="reset"><RotateCcw :size="14"/>重置</button><button @click="close"><X :size="14"/>关闭</button></template></div>
      <p class="small muted">数据来源：仿真，非真实火情、非算法识别、非经验证风险评估。</p>
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
      <dl class="facts"><div v-if="selected.display_height_m!==undefined"><dt>模型显示高度</dt><dd>{{selected.display_height_m.toFixed(2)}} m</dd></div><div v-if="selected.original_GBA_height_prediction_m!==undefined"><dt>原始 GBA 高度预测</dt><dd>{{selected.original_GBA_height_prediction_m.toFixed(2)}} m</dd></div><div><dt>火险评估</dt><dd>未接入</dd></div></dl>
      <p v-if="selected.object_id==='B01'" class="notice amber">30 m 拱顶为展示假设；原始约 7.30 m 预测独立保留。设施身份尚未确认。</p>
      <p v-else-if="selected.object_id==='CH01'" class="notice">240 m 为报告记载；外径与收分仍为展示假设，非本次实测。</p>
      <p v-else-if="selected.object_id.startsWith('CT-')" class="notice amber">150 m 为展示假设；塔壳、支撑与平台均未完成实地核验。</p>
      <p v-else-if="selected.object_id==='terrain'" class="notice">{{profile?.asset?.textures_present?'贴图地形（队友影像原字节保留）；未配准，不代表实际坝址或厂区位置。':'混合来源高程与人工估计平台，无卫星贴图。颜色不代表真实地表类型或风险。'}}</p>
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
.connection-details{margin:12px 0}
.create-run-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin:12px 0;background:#122436}
.create-run-panel .panel-eyebrow{margin-bottom:10px}
.create-run-panel .primary-button{margin-top:6px}
.live-flame-status{margin:6px 0}
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
.dev-panel{border:1px solid var(--border);border-radius:8px;padding:14px;margin-top:16px;background:#0d1a26}
.dev-panel .panel-eyebrow{margin-bottom:10px}
.dev-panel .secondary-button{margin-top:6px}
.check-list{list-style:none;margin:10px 0 0;padding:0}
.check-item{border-top:1px solid var(--border);padding:8px 0;display:flex;flex-direction:column;gap:4px}
.check-item:first-child{border-top:0;padding-top:2px}
.mono{font-family:ui-monospace,monospace;font-size:.75rem;word-break:break-all}
.check-pass{color:#7ee0a3}
.check-fail{color:#ff8a80}
</style>
