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
import type { VoxelLayerMode } from '../lib/voxel-shell'
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
  if(show&&!summary){gridIssue.value='当前场景暂时无法显示输电线路参考。';return}
  if(summary)gridSummary.value=summary
  gridVisible.value=show
  if(show)sceneCanvas.value?.focusGrid('station')
 }catch{gridIssue.value='输电线路参考暂时无法显示。'}
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
const voxelFrame=shallowRef<{points:Float32Array;sizeM:number}|null>(null)
const voxelMode=ref<VoxelLayerMode>('points')
const drawnVoxelMode=ref<VoxelLayerMode|null>(null)
function paintVoxelFrame(){
 const frame=voxelFrame.value
 drawnVoxelMode.value=sceneCanvas.value?.setVoxelLayer(frame?.points??null,frame?.sizeM??0,voxelMode.value)??null
}
function setVoxelFrame(points:Float32Array|null,voxelSizeM:number){
 voxelFrame.value=points?.length?{points,sizeM:voxelSizeM}:null
 paintVoxelFrame()
}
function toggleVoxelShell(){
 voxelMode.value=voxelMode.value==='points'?'shell':'points'
 paintVoxelFrame()
}
function onReplayVoxels(points:Float32Array|null,voxelSizeM:number){if(!followActive.value)setVoxelFrame(points,voxelSizeM)}
function onReplayActive(a:boolean){replayActive.value=a}
function onFollowVoxels(points:Float32Array|null,voxelSizeM:number){if(!replayActive.value)setVoxelFrame(points,voxelSizeM)}
function onFollowActive(a:boolean){followActive.value=a}
watch(alertRunId,()=>{if(!replayActive.value)setVoxelFrame(null,0)})
function onPlantPreviewToggle(visible:boolean){sceneCanvas.value?.setPlantPreviewVisible(visible)}
function onPlantPreviewFocus(view:'oblique'|'top'){sceneCanvas.value?.framePlantPreview(view)}
const flameStatus=computed(()=>{
 if(!latestObservation.value){
  if(bindingError.value)return '火情数据与当前三维场景不匹配。'
  if(conn.error.value&&alertRunId.value)return '暂时无法读取火情信息。'
  return alertRunId.value?'正在连接火情数据…':'等待火情信息。'
 }
 if(latestObservation.value.state_status!=='observation')return '尚未收到本次任务的第一条观测信息。'
 if(observationExpired.value)return '最近一次观测已过期，正在等待新信息。'
 if(latestObservation.value.result_origin!=='yolo')return '当前为平台测试数据，未生成火焰位置。'
 if(latestObservation.value.fire_detected===false)return '本次影像未发现火焰；这不等于确认无火。'
 if(latestFlame.value&&!flameEstimate.value)return '火焰位置与当前三维场景无法对应。'
 if(!flameEstimate.value)return '已发现火焰信息，但暂时无法显示三维位置。'
 if(renderMode.value==='software')return '当前浏览器暂不支持显示三维火焰位置。'
 return '已根据单视角信息估算火焰位置。'
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
const backQuery=computed(()=>({
 ...(route.query.mode==='grid'?{mode:'grid',...(typeof route.query.area==='string'?{area:route.query.area}:{})}:plant.value?{province:plant.value.properties.province_code}:{}),
 plant:sceneLink.value?.plant_id??''
}))
const statsText=computed(()=>{
 if(!profile.value)return ''
 return `${objects.value.length} 项场景内容 · 点击设施查看信息`
})
const sceneSizeText=computed(()=>{
 if(!profile.value)return ''
 if(profile.value.asset_role==='public_reference_terrain')return '建议浏览范围：约 100 km²'
 if(profile.value.asset_role==='prototype_model')return '厂区概念模型 · 展示范围待确认'
 if(isSjkSim.value)return '约 10 × 10 km · 场景展示范围'
 if(isZhijinDemo.value)return '约 4 × 4 km · 地形预览范围'
 return '三维场景预览'
})
const sceneTitle=computed(()=>{
 if(!profile.value)return '正在准备三维场景'
 if(profile.value.asset_role==='public_reference_terrain')return '双江口周边地形预览'
 if(profile.value.asset_role==='prototype_model')return `${plant.value?.properties.name??'场站'}概念预览`
 if(isSjkSim.value)return '双江口电站三维预览'
 return `${plant.value?.properties.name??'电厂'}三维预览`
})
const sceneBadgeText=computed(()=>{
 if(!profile.value)return ''
 if(profile.value.asset_role==='public_reference_terrain')return '公开地形参考'
 if(profile.value.asset_role==='prototype_model')return '厂区概念模型'
 if(isSjkSim.value)return '演示场景 · 位置尚未核实'
 return '三维预览'
})
const sceneNotice=computed(()=>{
 if(!profile.value)return ''
 if(profile.value.asset_role==='public_reference_terrain')return '使用公开地形资料展示周边山地，不是电厂和大坝的精细模型。'
 if(profile.value.asset_role==='prototype_model')return '这是厂区布局概念预览，设施位置尚未与真实厂区校准。'
 if(isSjkSim.value)return '此场景用于查看厂区和周边环境，布局与位置尚未完成实地核验。'
 return '此三维场景用于辅助浏览，具体设施信息和地理位置请以核实后的资料为准。'
})
const sceneScopeText=computed(()=>{
 if(!profile.value)return ''
 if(profile.value.asset_role==='public_reference_terrain')return '周边山地数据用于地形浏览，不代表厂区实景。'
 if(profile.value.asset_role==='prototype_model')return '概念模型用于展示布局构想，不代表设施实际位置。'
 if(isSjkSim.value)return '可查看场区和参考输电线路；画面不代表实测布局。'
 return '场景范围和设施细节仅供浏览参考，尚未完成实地核验。'
})
const sceneLocationText=computed(()=>{
 if(!profile.value)return ''
 if(profile.value.asset_role==='public_reference_terrain')return '地形位置来自公开资料；与厂区模型的对齐仍需核验。'
 if(profile.value.asset_role==='prototype_model')return '模型尚未与真实地理位置和方向校准。'
 if(isSjkSim.value)return '场景坐标用于三维浏览，真实经纬度、方向和高程仍待核验。'
 return '场景与真实地理位置的对应关系仍需进一步核实。'
})
function loaded(p:SceneProfile,o:SceneObject[],m:ReferenceMarker[]){profile.value=p;objects.value=o;markers.value=m;error.value=''}
function resetSceneState(){
 profile.value=null;objects.value=[];markers.value=[];selected.value=null;error.value=''
 gridVisible.value=false;gridIssue.value='';gridSummary.value=null
 voxelMode.value='points';setVoxelFrame(null,0)
}
function retry(){resetSceneState();attempt.value++}
// 场景切换（scene_id 变化）时清空上一场景状态，避免旧 profile/对象残留到新场景的加载或失败画面。
watch(()=>String(route.params.sceneId),()=>resetSceneState())
function choose(event:Event){sceneCanvas.value?.select((event.target as HTMLSelectElement).value||null,true)}
onMounted(()=>{loadCatalog();load()})
</script>
<template>
 <main class="scene-layout">
  <header class="scene-heading"><div><RouterLink class="back-link" :to="{path:'/atlas',query:backQuery}"><ArrowLeft :size="16"/>返回场站信息</RouterLink><h1>{{sceneTitle}}<span v-if="profile" class="tag">{{sceneBadgeText}}</span></h1><p v-if="plant">{{plant.properties.name}} · {{plant.properties.source_province}}</p></div><div v-if="profile" class="scene-size"><strong>{{sceneSizeText}}</strong></div></header>
  <div class="scene-workspace">
   <section class="viewer-frame">
    <SceneCanvas v-if="dataReady&&valid&&sceneLink" :key="canvasKey" ref="sceneCanvas" :profile-url="assetUrl(sceneLink.profile_uri)" :fire-patches="firePatches" :flame-estimate="effectiveFlameEstimate" @loaded="loaded" @selected="selected=$event" @error="error=$event" @mode="renderMode=$event" @overlay-issue="overlayIssue=$event"/>
    <div v-else class="loader-overlay" role="status"><h3>{{dataError||(dataReady?'这个三维场景暂不可用':'正在准备三维场景')}}</h3><button v-if="dataError" @click="loadCatalog">重新加载</button></div>
    <div v-if="profile" class="viewer-toolbar">
     <button v-if="flameEstimate&&renderMode==='webgl'" @click="focusFlame"><Flame :size="17"/>定位火焰</button>
     <button v-if="!isZhijinDemo&&firePatches.length" @click="focusFire"><Flame :size="17"/>定位火情</button>
     <button v-if="profile.cameras.plant" @click="sceneCanvas?.frame('plant')"><Focus :size="17"/>电厂近景</button>
     <button v-if="profile.cameras.whole_terrain" @click="sceneCanvas?.frame('whole_terrain')"><Mountain :size="17"/>周边全景</button>
     <button v-if="!profile.cameras.whole_terrain" @click="sceneCanvas?.frame('panorama')"><Mountain :size="17"/>全景</button>
     <button @click="sceneCanvas?.frame('default')" title="恢复初始取景"><RotateCcw :size="17"/>恢复默认视角</button>
     <button v-if="isSjkSim&&renderMode==='webgl'&&voxelFrame" type="button" :aria-pressed="voxelMode==='shell'"
             title="切换同一次重建的点状显示和立体轮廓" @click="toggleVoxelShell"><Box :size="17"/>重建轮廓</button>
     <button v-if="drawnVoxelMode" type="button" @click="sceneCanvas?.focusVoxels()"><Focus :size="17"/>定位重建结果</button>
    </div>
    <div class="viewer-badges"><span v-if="drawnVoxelMode==='shell'" class="tag amber">三维重建轮廓 · 预览结果</span><span v-else-if="voxelMode==='shell'&&drawnVoxelMode==='points'" class="tag neutral" role="status">暂无法显示立体轮廓，已保留点状结果</span><span v-if="gridVisible" class="tag neutral">输电线路位置示意</span><span v-if="flameEstimate&&renderMode==='webgl'" class="tag danger"><Flame :size="13"/>火焰位置估算（依据单个视角）</span><template v-if="isZhijinDemo"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>暂无火情观测</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>模拟火情数据</span><span v-else class="tag amber">回放中 · 本时刻未显示火点</span></template><span v-else-if="profile?.asset_role==='prototype_model'" class="tag amber">{{sceneBadgeText}}</span><span v-else class="tag amber">场景位置和布局尚未核实</span><span v-if="profile?.terrain_mesh_name" class="tag neutral">地形颜色仅表示高低，不代表植被或火险</span></div>
    <div class="viewer-bottom"><span><MousePointer2 :size="14"/>拖动旋转 · 滚轮缩放 · 右键平移</span><span class="axis-label">场景位置仅供参考，详情见下方说明</span></div>
   </section>
   <aside class="scene-inspector">
    <section v-if="alertRunId||isSjkSim" class="demo-panel" aria-live="polite">
     <div class="panel-eyebrow">火情动态<Flame :size="16"/></div>
     <p class="live-flame-status">{{flameStatus}}</p>
     <p v-if="(alertRunId||latestObservation)&&conn.error.value" class="small muted">{{latestObservation?'数据连接异常，暂时保留最近收到的信息。':'暂时无法连接火情数据。'}}</p>
     <button v-if="alertRunId&&(conn.status.value==='error'||conn.status.value==='disconnected'||conn.runId.value!==alertRunId)"
         class="secondary-button" @click="connectAlert">重新连接数据</button>
     <p v-if="latestObservation?.observation_time_s!=null" class="small muted">观测 {{conn.observationTimeLabel.value}} · {{latestObservation.input_source==='simulation'?'模拟数据':'现场影像'}}</p>
     <p v-if="flameEstimate" class="small muted">火焰位置为估计值，深度尚无法测量；周边地形和厂区使用当前三维场景。</p>
    </section>
    <PlantPreviewPanel v-if="isSjkSim" :profile="profile" @toggle="onPlantPreviewToggle" @focus="onPlantPreviewFocus" />
    <SjkGridPanel v-if="gridAvailable" :visible="gridVisible" :webgl="renderMode==='webgl'" :summary="gridSummary" :issue="gridIssue"
       @toggle="toggleGrid" @focus="sceneCanvas?.focusGrid($event)" />
    <MultiviewReplayPanel v-if="isSjkSim" :profile="profile" :disabled="followActive" @voxels="onReplayVoxels" @active="onReplayActive" />
    <ReconstructionFollowPanel v-if="isSjkSim" :profile="profile" :run-id="alertRunId" :run="conn.run.value" :disabled="replayActive" @voxels="onFollowVoxels" @active="onFollowActive" />
    <section v-if="isSjkSim" class="create-run-panel">
      <div class="panel-eyebrow">三维重建任务<Plus :size="16"/></div>
      <p class="small muted">创建一项新的三维重建任务，平台会自动连接任务结果。刷新页面后仍可继续查看。</p>
      <button class="primary-button" :disabled="!profile || creatingRun" @click="createReconstructionRun">
        {{ creatingRun ? '正在创建…' : '开始重建' }}
      </button>
      <p v-if="createRunError" class="notice error" role="alert">{{ createRunError }}</p>
    </section>
    <details v-if="alertRunId" class="connection-details"><summary>连接信息</summary><RunConnectionPanel/></details>
    <RunConnectionPanel v-else/>
    <div v-if="bindingError" class="notice error" role="alert">{{bindingError}}</div>
    <div v-if="overlayIssue" class="notice amber" role="status">{{overlayIssue}}</div>
    <details v-if="isDev&&isSjkSim" class="dev-panel">
     <summary>高级模型校核</summary>
     <p class="small muted">检查参考位置是否落在当前地形表面。下方结果用于内部校核。</p>
     <button class="secondary-button" :disabled="!profile" @click="runCheck">检查参考点位置</button>
     <ul v-if="checkResults.length" class="check-list">
      <li v-for="r in checkResults" :key="r.id" class="check-item" :data-point-id="r.id">
       <strong>{{r.id}}</strong>
       <div class="small muted">转换点（GLB m）：<span class="mono cv">{{fmt3(r.converted_glb_xyz)}}</span></div>
       <div class="small muted">命中点（GLB m）：<span class="mono hit">{{r.hit_glb_xyz?fmt3(r.hit_glb_xyz):'未命中'}}</span></div>
       <div class="small muted">矩阵残差 <span class="mono mres">{{r.matrix_residual_m.toExponential(3)}}</span> m · 射线残差 <span class="mono rres">{{r.raycast_residual_m==null?'—':r.raycast_residual_m.toExponential(3)}}</span> m</div>
       <div v-if="r.id==='P6'" class="small" :class="r.x_axis_reversed?'check-pass':'check-fail'">X 轴反向：{{r.x_axis_reversed?'已验证（glb X = +2500 m = −(mesh_local X)）':'未通过'}}</div>
      </li>
     </ul>
    </details>
    <div class="panel-eyebrow">场景概况<Box :size="16"/></div>
    <div v-if="profile" class="loaded-status">三维场景已准备好<span>{{statsText}}</span></div>
    <p v-if="sceneNotice" class="notice amber">{{sceneNotice}}</p>
    <p v-if="renderMode==='software'" class="notice amber">当前使用兼容显示，画面细节可能较少。<template v-if="isZhijinDemo&&activeFirePatches.length">火情位置会同步显示在地图和场站信息中。</template><template v-if="profile?.capabilities.reference_markers">部分位置标记在此模式下不可见。</template></p>
    <div v-if="!profile" class="notice" :class="{error:!!error}">{{error?'三维场景加载失败':'正在加载三维场景'}}<button v-if="error" class="secondary-button" @click="retry">重新加载</button></div>
    <section v-if="isZhijinDemo" class="demo-panel">
     <div class="panel-eyebrow">火情过程回放<Flame :size="16"/></div>
     <div v-if="demoDisabled" class="notice amber"><ShieldQuestion :size="14"/>当前场景暂时无法显示火情位置。</div>
     <p v-else-if="dataState==='loading'" class="small muted">正在读取回放数据…</p>
     <div v-else-if="dataState==='unavailable'" class="notice error">火情回放暂时不可用<button class="secondary-button" @click="load">重新加载</button></div>
     <template v-else-if="dataState==='ready'">
      <div class="demo-status"><span v-if="!isDemoOn" class="tag neutral"><ShieldQuestion :size="13"/>暂无火情观测</span><span v-else-if="activeFirePatches.length" class="tag danger"><Flame :size="13"/>模拟火情数据</span><span v-else class="tag amber">回放中 · 当前未显示火点</span><span class="demo-time">{{t_s.toFixed(1)}} / {{demo?.duration_s??0}} s</span></div>
      <div class="demo-controls"><button v-if="!isDemoOn" @click="play"><Flame :size="14"/>开始回放</button><template v-else><button @click="play" :disabled="status==='ended'"><Play :size="14"/>播放</button><button @click="pause" :disabled="!playing"><Pause :size="14"/>暂停</button><button @click="reset"><RotateCcw :size="14"/>重置</button><button @click="close"><X :size="14"/>关闭</button></template></div>
      <p class="small muted">此处为模拟数据，不代表现场火情或经过验证的风险评估结果。</p>
     </template>
    </section>
    <details v-if="profile?.capabilities.reference_markers&&markers.length" class="markers-panel">
     <summary>参考位置（展开查看）</summary>
     <p class="small muted">以下位置来自公开地图资料，仅用于场景定位参考；标记高度并非设施实测高度。</p>
     <ul class="marker-list">
      <li v-for="m in markers" :key="m.marker_id"><div class="marker-line"><strong>{{m.label}}</strong></div><p class="small muted coord">{{m.lon_lat_wgs84[0]}}, {{m.lon_lat_wgs84[1]}}（WGS84）</p><p class="small muted">局部 {{m.local_xyz_m.map(v=>v.toFixed(1)).join(', ')}} m</p></li>
     </ul>
    </details>
    <template v-if="profile?.capabilities.object_selection">
     <label class="object-label" for="object-select">查找场站设施</label><select id="object-select" :value="selected?.object_id??''" :disabled="!profile" @change="choose"><option value="">选择设施，或点击模型中的建筑</option><option v-for="o in objects" :key="o.object_id" :value="o.object_id">{{o.display_name}}</option></select>
     <section v-if="selected" class="object-detail"><h2>{{selected.display_name}}</h2><div class="tags"><span class="tag amber">{{selected.object_id==='terrain'?'估算地形':identityLabel(selected.identity_status)}}</span><span class="tag neutral">{{heightLabel(selected)}}</span></div>
      <dl class="facts"><div v-if="selected.display_height_m!==undefined"><dt>场景显示高度</dt><dd>{{selected.display_height_m.toFixed(2)}} m</dd></div><div v-if="selected.original_GBA_height_prediction_m!==undefined"><dt>公开资料高度参考</dt><dd>{{selected.original_GBA_height_prediction_m.toFixed(2)}} m</dd></div><div><dt>火险评估</dt><dd>暂无评估结果</dd></div></dl>
      <p v-if="selected.object_id==='B01'" class="notice amber">拱顶高度为场景展示设定，设施身份和实际尺寸尚未核实。</p>
      <p v-else-if="selected.object_id==='CH01'" class="notice">高度来自公开报告；外形和尺寸尚未实地核实。</p>
      <p v-else-if="selected.object_id.startsWith('CT-')" class="notice amber">冷却塔高度和外形为场景展示设定，尚未实地核实。</p>
      <p v-else-if="selected.object_id==='terrain'" class="notice">{{profile?.asset?.textures_present?'地形图片仅供场景展示，尚未与真实坝址或厂区位置校准。':'地形由公开高程资料和估计平台构成，没有卫星影像。颜色只表示场景效果，不代表真实地表或风险。'}}</p>
      <p v-else class="small muted">设施外形和高度来自公开资料整理，功能与实际位置仍需现场核实。</p>
      <details><summary>查看信息核验情况</summary><p class="small">设施身份：{{selected.identity_status}}</p><p class="small">高度依据：{{selected.height_status}}</p><p class="small">位置依据：{{selected.position_status}}</p><p v-if="selected.shape_status" class="small">外形依据：{{selected.shape_status}}</p><p class="small">场景编号：{{selected.object_id}}</p></details>
     </section>
     <div v-else class="object-placeholder"><MousePointer2 :size="27"/><h3>查看场站设施</h3><p>点击模型中的设施，即可查看名称、尺寸和资料说明。</p></div>
    </template>
    <section class="scene-notes"><h3><Info :size="15"/>场景说明</h3><p v-if="sceneScopeText">{{sceneScopeText}}</p><p v-if="sceneLocationText">{{sceneLocationText}}</p><details><summary>查看数据来源</summary><div v-for="s in profile?.sources_and_attribution" :key="s.name" class="attribution"><a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{s.name}}<ExternalLink :size="12"/></a><span v-else>{{s.name}}</span><p class="small muted">{{s.licence??s.attribution??s.notice??'参考资料'}}</p></div></details><details v-if="profile?.limitations?.length"><summary>场景精度与限制</summary><ul class="limits"><li v-for="(l,i) in profile.limitations" :key="i" class="small muted">{{l}}</li></ul></details></section>
   </aside>
  </div>
 </main>
</template>
<style scoped>
.viewer-toolbar button[aria-pressed="true"]{border-color:#a66d38;color:#ffd095}
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
.markers-panel summary{cursor:pointer;font-weight:600;color:#cfe3ee}
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
