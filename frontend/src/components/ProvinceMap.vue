<script setup lang="ts">
import { ref,onMounted,onBeforeUnmount,watch } from 'vue'
import * as echarts from 'echarts/core'
import { GeoComponent,TooltipComponent } from 'echarts/components'
import { ScatterChart,LinesChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import type { Boundaries,Plant } from '../lib/types'
import { RotateCcw } from 'lucide-vue-next'
echarts.use([GeoComponent,TooltipComponent,ScatterChart,LinesChart,CanvasRenderer])
const props=defineProps<{boundaries:Boundaries;lines:Boundaries|null;plants:Plant[];province:string;selectedPlant:string;demoActive:boolean}>()
const emit=defineEmits<{province:[code:string];plant:[id:string]}>()
const host=ref<HTMLDivElement>();let chart:echarts.ECharts|null=null;let observer:ResizeObserver|null=null
function draw(){
 if(!chart)return
 const regions=props.boundaries.features.map(f=>({name:f.properties.name,itemStyle:{areaColor:f.properties.code===props.province?'#226553':props.plants.some(p=>p.properties.related_province_codes.includes(f.properties.code??''))?'#1b3542':'#152636'},label:{show:['贵州省','四川省','云南省','台湾省'].includes(f.properties.name),color:'#aebfd1',fontSize:14}}))
 const points=props.plants.filter(p=>!props.province||p.properties.related_province_codes.includes(props.province))
 const lines=props.lines?.features.flatMap(f=>f.geometry.type==='MultiLineString'?(f.geometry.coordinates as number[][][]).map(coords=>({coords})):[])??[]
 chart.setOption({
  animation:false,backgroundColor:'transparent',
  tooltip:{trigger:'item',backgroundColor:'#142538',borderColor:'#365163',textStyle:{color:'#e2ecf5'},formatter:(p:unknown)=>{
    const params=p as {seriesType?:string;data?:{plantId?:string};name:string}
    const plant=props.plants.find(x=>x.properties.plant_id===params.data?.plantId)
    if(plant)return `${plant.properties.name}<br/>${plant.properties.capacity_mw?.toLocaleString()??'未知'} MW · ${plant.properties.plant_id==='GEM_COAL_ZHIJIN'&&props.demoActive?'演示告警（合成）':'尚未接入火情'}`
    const code=props.boundaries.features.find(f=>f.properties.name===params.name)?.properties.code
    return `${params.name}<br/>${props.plants.filter(p=>p.properties.related_province_codes.includes(code??'')).length} 个关联样例`
  }},
  geo:{map:'firex-provinces',roam:true,scaleLimit:{min:0.8,max:6},layoutCenter:['50%','51%'],layoutSize:'98%',aspectScale:0.75,selectedMode:false,
    label:{show:false},itemStyle:{areaColor:'#152636',borderColor:'#406072',borderWidth:0.65},emphasis:{itemStyle:{areaColor:'#2b5261'},label:{color:'#f4fbff',fontSize:14}},regions},
  series:[{type:'lines',coordinateSystem:'geo',polyline:true,silent:true,data:lines,lineStyle:{color:'#627d90',width:1,opacity:0.75}},
   {type:'scatter',coordinateSystem:'geo',symbolSize:(val:number[],params:unknown)=>((params as {data:{plantId:string}}).data.plantId===props.selectedPlant?17:10),
    itemStyle:{color:'#56e3bb',borderColor:'#c4ffe8',borderWidth:1.5,shadowColor:'#4eddb8',shadowBlur:10},
    data:points.map(p=>({name:p.properties.name,value:[...p.geometry.coordinates,1],plantId:p.properties.plant_id})),z:10}],
 },{notMerge:true})
}
onMounted(()=>{
 // Geometry is parsed from the downloaded polygons. No hand-drawn outline is used.
 echarts.registerMap('firex-provinces',props.boundaries as Parameters<typeof echarts.registerMap>[1])
 chart=echarts.init(host.value!,undefined,{renderer:'canvas'})
 chart.on('click',(params)=>{
  const data=params.data as {plantId?:string}|undefined
  if(data?.plantId){emit('plant',data.plantId);return}
  const code=props.boundaries.features.find(f=>f.properties.name===params.name)?.properties.code
  if(code)emit('province',code)
 })
 observer=new ResizeObserver(()=>chart?.resize());observer.observe(host.value!);draw()
})
watch(()=>[props.province,props.selectedPlant,props.plants,props.demoActive],draw)
onBeforeUnmount(()=>{observer?.disconnect();chart?.dispose();chart=null})
</script>
<template><div class="map-frame"><div ref="host" class="map-canvas" aria-label="中国省级地图，省份列表可提供键盘操作"></div><button class="map-reset icon-button" @click="draw" aria-label="重置地图取景" title="重置地图取景"><RotateCcw :size="17"/></button><div class="map-legend"><span class="sample-dot"></span>电厂样例<span class="legend-line"></span>省级边界</div></div></template>
