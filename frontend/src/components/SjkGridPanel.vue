<script setup lang="ts">
import { onBeforeUnmount,onMounted,shallowRef } from 'vue'
import { Cable,ExternalLink,Focus } from 'lucide-vue-next'
import { assetUrl,readJson } from '../lib/data'
import type { GridSummary } from '../lib/sjk-grid'

type PublicOutgoing = {
  from:string;to:string;reference_voltage_kv:number;circuit_count_in_approval:number;
  route_length_per_circuit_approx_km:number;source_urls:string[];
}
defineProps<{visible:boolean;webgl:boolean;summary:GridSummary|null;issue:string}>()
defineEmits<{toggle:[];focus:[view:'station'|'corridor']}>()
const reference=shallowRef<PublicOutgoing|null>(null)
const unavailable=shallowRef(false)
const abort=new AbortController()
onMounted(async()=>{
  try{reference.value=await readJson<PublicOutgoing>(assetUrl('data/shuangjiangkou/official_outgoing_line_reference.json'),abort.signal)}
  catch{if(!abort.signal.aborted)unavailable.value=true}
})
onBeforeUnmount(()=>abort.abort())
</script>

<template>
 <section class="grid-panel" aria-label="输电线路信息">
  <h3><Cable :size="17"/>输电线路</h3>
  <div class="grid-reference">
   <span class="grid-label">公开资料中的线路关系</span>
   <template v-if="reference">
    <ol class="grid-topology">
     <li>{{reference.from}}</li>
     <li class="grid-connection">{{reference.circuit_count_in_approval}} 回 · {{reference.reference_voltage_kv}} kV</li>
     <li>{{reference.to}}</li>
    </ol>
    <p class="small muted">资料记载线路长度约 {{reference.route_length_per_circuit_approx_km}} 公里；实际杆塔位置尚未接入。</p>
    <a v-if="reference.source_urls[1]" class="grid-source" :href="reference.source_urls[1]" target="_blank" rel="noopener noreferrer">查看公开资料<ExternalLink :size="11"/></a>
   </template>
   <p v-else class="small muted">{{unavailable?'暂时无法读取公开接线资料。':'正在读取公开接线资料…'}}</p>
  </div>
  <div class="grid-simulation">
   <span class="grid-label">输电线路位置参考</span>
   <p class="small muted">场景中的杆塔和双回线路仅作展示，路径、塔位和高度均非实测，不可用于判断安全净空。</p>
   <p v-if="summary" class="grid-stats">{{(summary.lengthM/1000).toFixed(1)}} km · 1 座门架 · {{summary.towers}} 基塔</p>
   <div v-if="visible" class="grid-legend" aria-label="导线图例"><span>第一回</span><span>第二回</span></div>
   <p v-if="!webgl" class="small muted">当前浏览器暂不支持显示三维线路。</p>
   <div class="grid-actions">
    <button type="button" :disabled="!webgl" :aria-pressed="visible" @click="$emit('toggle')">{{visible?'隐藏线路参考':'显示线路参考'}}</button>
    <template v-if="visible">
     <button type="button" @click="$emit('focus','station')"><Focus :size="13"/>站端取景</button>
     <button type="button" @click="$emit('focus','corridor')"><Focus :size="13"/>走廊全景</button>
    </template>
   </div>
   <p v-if="issue" class="small grid-issue" role="alert">{{issue}}</p>
  </div>
 </section>
</template>

<style scoped>
.grid-panel{background:#112233;border:1px solid #2a4959;border-radius:8px;padding:14px;margin:12px 0}
.grid-panel h3{display:flex;align-items:center;gap:8px;margin-bottom:11px;color:#edf7fd}
.grid-panel h3 svg,.grid-source{color:#83e8d7}
.grid-label{display:block;color:#b3cddd;font-size:.75rem;font-weight:600;margin-bottom:6px}
.grid-topology{display:grid;gap:3px;list-style:none;padding:0 0 0 12px;margin:0 0 7px;border-left:2px solid #527280;font-size:.8rem;color:#e2eff6}
.grid-connection{font-size:.73rem;color:#81decb}
.grid-panel p{font-size:.75rem;margin-bottom:7px}
.grid-source{display:inline-flex;align-items:center;gap:5px;font-size:.73rem}
.grid-simulation{border-top:1px solid #294151;margin-top:11px;padding-top:10px}
.grid-panel .grid-stats{color:#a2e5dc;font-variant-numeric:tabular-nums}
.grid-legend{display:flex;gap:12px;color:#c3d8e3;font-size:.71rem;margin-bottom:8px}
.grid-legend span{display:inline-flex;align-items:center;gap:5px}
.grid-legend span::before{content:'';width:11px;height:2px;background:#55efdc}
.grid-legend span+span::before{background:#a2ddff}
.grid-actions{display:flex;flex-wrap:wrap;gap:5px}
.grid-actions button{display:inline-flex;align-items:center;gap:4px;font-size:.73rem;padding:5px 8px}
.grid-actions button:first-child{border-color:#3f827a;color:#a2f1dd;background:#173b3e}
.grid-panel .grid-issue{color:#ffd29b;margin-top:7px}
</style>
