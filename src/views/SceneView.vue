<script setup lang="ts">
import { computed,onMounted,ref,shallowRef } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft,Mountain,Focus,RotateCcw,MousePointer2,Info,ExternalLink,Box,ShieldQuestion } from 'lucide-vue-next'
import SceneCanvas from '../components/SceneCanvas.vue'
import { loadCatalog,dataReady,dataError,sceneFor,assetUrl,heightLabel,identityLabel } from '../lib/data'
import type { SceneManifest,SceneObject } from '../lib/types'
const route=useRoute();const sceneCanvas=ref<InstanceType<typeof SceneCanvas>>();const manifest=shallowRef<SceneManifest|null>(null)
const objects=shallowRef<SceneObject[]>([]),selected=shallowRef<SceneObject|null>(null),error=ref(''),attempt=ref(0)
const renderMode=ref<'webgl'|'software'>('webgl')
const sceneLink=computed(()=>sceneFor('GEM_COAL_ZHIJIN'))
const valid=computed(()=>route.params.sceneId==='zhijin_pilot'&&!!sceneLink.value)
const backQuery=computed(()=>({...(typeof route.query.province==='string'?{province:route.query.province}:{province:'520000'}),plant:'GEM_COAL_ZHIJIN'}))
function loaded(m:SceneManifest,o:SceneObject[]){manifest.value=m;objects.value=o;error.value=''}
function retry(){manifest.value=null;objects.value=[];selected.value=null;error.value='';attempt.value++}
function choose(event:Event){sceneCanvas.value?.select((event.target as HTMLSelectElement).value||null,true)}
onMounted(loadCatalog)
</script>
<template>
 <main class="scene-layout">
  <header class="scene-heading"><div><RouterLink class="back-link" :to="{path:'/atlas',query:backQuery}"><ArrowLeft :size="16"/>返回电厂详情</RouterLink><h1>织金电厂与周边山地<span class="tag">试建场景 · v4</span></h1><p>国能织金发电有限公司 · 贵州省织金县八步街道</p></div><div class="scene-size"><strong>16<span>km²</span></strong><small>4 × 4 km 试建研究区</small></div></header>
  <div class="scene-workspace">
   <section class="viewer-frame">
    <SceneCanvas v-if="dataReady&&valid" :key="attempt" ref="sceneCanvas" :manifest-url="assetUrl(sceneLink!.manifest_uri)" @loaded="loaded" @selected="selected=$event" @error="error=$event" @mode="renderMode=$event"/>
    <div v-else class="loader-overlay" role="status"><h3>{{dataError|| (dataReady?'场景不存在':'正在读取场景索引')}}</h3><button v-if="dataError" @click="loadCatalog">重试目录</button></div>
    <div v-if="manifest" class="viewer-toolbar"><button @click="sceneCanvas?.frame('plant')"><Focus :size="17"/>厂区取景</button><button @click="sceneCanvas?.frame('whole_terrain')"><Mountain :size="17"/>全域地形</button><button @click="sceneCanvas?.frame('plant')" title="恢复初始取景"><RotateCcw :size="17"/>重置视角</button></div>
    <div class="viewer-badges"><span class="tag neutral"><ShieldQuestion :size="13"/>尚未接入火情</span><span class="tag neutral">高程示意色 · 非植被或火险</span></div>
    <div class="viewer-bottom"><span><MousePointer2 :size="14"/>拖动旋转 · 滚轮缩放 · 右键平移 · 单击对象</span><span class="axis-label">X 东 · Y 上 · Z 南 / 米</span></div>
   </section>
   <aside class="scene-inspector">
    <div class="panel-eyebrow">场景检查<Box :size="16"/></div>
    <div v-if="manifest" class="loaded-status">原始 v4 GLB 已加载<span>38 个对象 · 340,572 个三角形</span></div>
    <p v-if="renderMode==='software'" class="notice amber">当前浏览器不支持 WebGL，已使用兼容显示。地形为原始顶点粗采样，光照为近似效果；GPU 渲染与性能尚待验证。</p>
    <div v-if="!manifest" class="notice" :class="{error:!!error}">{{error?'模型暂不可用':'正在加载场景资源'}}<button v-if="error" class="secondary-button" @click="retry">重新加载</button></div>
    <label class="object-label" for="object-select">定位对象</label><select id="object-select" :value="selected?.object_id??''" :disabled="!manifest" @change="choose"><option value="">选择对象，或在模型上单击</option><option v-for="o in objects" :key="o.object_id" :value="o.object_id">{{o.object_id}} · {{o.display_name}}</option></select>
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
    <section class="scene-notes"><h3><Info :size="15"/>使用范围</h3><p>16 km² 为试建研究区，不是电厂本体面积。无卫星纹理，未验收真实场景精度。</p><p>模型采用局部米制坐标。Y 为源高程减 1000 m，不是离地高度。模型根变换保持原样。</p><details><summary>数据来源与署名</summary><div v-for="s in manifest?.sources_and_attribution" :key="s.name" class="attribution"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{s.name}}<ExternalLink :size="12"/></a><p class="small muted">{{s.licence??s.attribution??s.notice??'原交接资料参考'}}</p></div></details></section>
   </aside>
  </div>
 </main>
</template>
