<script setup lang="ts">
import { ref,onMounted,onBeforeUnmount } from 'vue'
import { ModelViewer } from '../lib/viewer'
import type { SceneManifest,SceneObject } from '../lib/types'
const props=defineProps<{manifestUrl:string}>()
const emit=defineEmits<{loaded:[manifest:SceneManifest,objects:SceneObject[]];selected:[object:SceneObject|null];error:[message:string];mode:[mode:'webgl'|'software']}>()
const host=ref<HTMLDivElement>(),percent=ref(0),message=ref('准备三维查看器'),ready=ref(false),error=ref('')
let viewer:ModelViewer|null=null;let destroyed=false
onMounted(async()=>{
 try{
  viewer=new ModelViewer(host.value!,{mode:m=>emit('mode',m),progress:(p,m)=>{if(!destroyed){percent.value=Math.round(p);message.value=m}},loaded:(m,o)=>{if(!destroyed){ready.value=true;emit('loaded',m,o)}},selected:o=>emit('selected',o)})
  await viewer.load(props.manifestUrl)
 }catch(e){if(destroyed)return;error.value=e instanceof Error?e.message:'模型加载失败';viewer?.dispose();viewer=null;emit('error',error.value)}
})
onBeforeUnmount(()=>{destroyed=true;viewer?.dispose();viewer=null})
defineExpose({frame:(kind:'plant'|'whole_terrain')=>viewer?.framePreset(kind),select:(id:string|null,focus=false)=>viewer?.select(id,focus)})
</script>
<template><div ref="host" class="scene-canvas"><div v-if="!ready&&!error" class="loader-overlay" role="status"><div class="loader-mark"></div><h3>{{message}}</h3><div class="progress-track"><div :style="{width:`${percent}%`}"></div></div><p>{{percent}}% · 约 6.72 MB</p></div><div v-if="error" class="loader-overlay error-state" role="alert"><h3>三维模型加载失败</h3><p>{{error}}</p><p class="muted">可在右侧重试，或返回电厂详情。</p></div></div></template>
