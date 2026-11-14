<script setup lang="ts">
import { ref,onMounted,onBeforeUnmount,watch } from 'vue'
import * as echarts from 'echarts/core'
import { GeoComponent,TooltipComponent } from 'echarts/components'
import { ScatterChart,LinesChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import type { Boundaries,Plant } from '../lib/types'
import { RotateCcw } from 'lucide-vue-next'
echarts.use([GeoComponent,TooltipComponent,ScatterChart,LinesChart,CanvasRenderer])
const props=defineProps<{boundaries:Boundaries;lines:Boundaries|null;plants:Plant[];province:string;selectedPlant:string;demoActive:boolean;testPlantId:string;firePlants:{plantId:string;label?:string;statusText:string}[]}>()
const emit=defineEmits<{province:[code:string];plant:[id:string]}>()
const host=ref<HTMLDivElement>();let chart:echarts.ECharts|null=null;let observer:ResizeObserver|null=null
interface MapBounds{minLon:number;minLat:number;maxLon:number;maxLat:number}
interface MapViewport{center?:number[];zoom?:number}
const provinceBounds=new Map<string,MapBounds>()
let nationalBounds:MapBounds|null=null
let lastSelectionKey:string|null=null
let userViewport:MapViewport|null=null
function boundsFromCoordinates(coordinates:unknown):MapBounds|null{
 const bounds:MapBounds={minLon:Infinity,minLat:Infinity,maxLon:-Infinity,maxLat:-Infinity}
 function visit(value:unknown){
  if(!Array.isArray(value))return
  if(typeof value[0]==='number'&&typeof value[1]==='number'){
   const [lon,lat]=value
   if(Number.isFinite(lon)&&Number.isFinite(lat)){
    bounds.minLon=Math.min(bounds.minLon,lon);bounds.minLat=Math.min(bounds.minLat,lat)
    bounds.maxLon=Math.max(bounds.maxLon,lon);bounds.maxLat=Math.max(bounds.maxLat,lat)
   }
   return
  }
  value.forEach(visit)
 }
 visit(coordinates)
 return Number.isFinite(bounds.minLon)?bounds:null
}
function mergeBounds(a:MapBounds|null,b:MapBounds):MapBounds{
 return a?{minLon:Math.min(a.minLon,b.minLon),minLat:Math.min(a.minLat,b.minLat),maxLon:Math.max(a.maxLon,b.maxLon),maxLat:Math.max(a.maxLat,b.maxLat)}:b
}
function indexBounds(){
 provinceBounds.clear();nationalBounds=null
 for(const feature of props.boundaries.features){
  const bounds=boundsFromCoordinates(feature.geometry.coordinates)
  if(!bounds)continue
  nationalBounds=mergeBounds(nationalBounds,bounds)
  const code=feature.properties.code
  if(code)provinceBounds.set(code,bounds)
 }
}
function focusForSelection():MapViewport{
 const plant=props.plants.find(p=>p.properties.plant_id===props.selectedPlant)
 if(plant)return{center:[...plant.geometry.coordinates],zoom:5.5}
 const bounds=provinceBounds.get(props.province)
 if(bounds&&nationalBounds){
  const width=Math.max(bounds.maxLon-bounds.minLon,0.1)
  const height=Math.max(bounds.maxLat-bounds.minLat,0.1)
  const mapWidth=nationalBounds.maxLon-nationalBounds.minLon
  const mapHeight=nationalBounds.maxLat-nationalBounds.minLat
  const zoom=Math.min((mapWidth/width)*0.78,(mapHeight/height)*0.78,6)
  return{center:[(bounds.minLon+bounds.maxLon)/2,(bounds.minLat+bounds.maxLat)/2],zoom:Math.max(1,zoom)}
 }
 return{zoom:1}
}
function currentViewport():MapViewport|null{
 const options=chart?.getOption().geo
 const geo=Array.isArray(options)?options[0]:options
 if(!geo)return null
 const center=geo.center?.map(Number)
 return{...(center?.length===2?{center}:{}),...(typeof geo.zoom==='number'?{zoom:geo.zoom}:{})}
}
function selectionKey(){return`${props.province}|${props.selectedPlant}`}
function draw(resetFocus=false){
 if(!chart)return
 const key=selectionKey()
 const selectionChanged=key!==lastSelectionKey
 const viewport=!resetFocus&&!selectionChanged?(userViewport??currentViewport()):null
 if(selectionChanged||resetFocus)userViewport=null
 const focus=viewport??focusForSelection()
 lastSelectionKey=key
 const regions=props.boundaries.features.map(f=>({name:f.properties.name,itemStyle:{areaColor:f.properties.code===props.province?'#226553':props.plants.some(p=>p.properties.related_province_codes.includes(f.properties.code??''))?'#1b3542':'#152636'},label:{show:['贵州省','四川省','云南省','台湾省'].includes(f.properties.name),color:'#aebfd1',fontSize:14}}))
 const points=props.plants.filter(p=>!props.province||p.properties.related_province_codes.includes(props.province))
 const testPoints=points.filter(p=>p.properties.plant_id===props.testPlantId)
 const firePoints=points.filter(p=>props.firePlants.some(f=>f.plantId===p.properties.plant_id))
 const lines=props.lines?.features.flatMap(f=>f.geometry.type==='MultiLineString'?(f.geometry.coordinates as number[][][]).map(coords=>({coords})):[])??[]
 chart.setOption({
  animation:false,backgroundColor:'transparent',
  tooltip:{trigger:'item',backgroundColor:'#142538',borderColor:'#365163',textStyle:{color:'#e2ecf5'},formatter:(p:unknown)=>{
    const params=p as {seriesType?:string;data?:{plantId?:string};name:string}
    const plant=props.plants.find(x=>x.properties.plant_id===params.data?.plantId)
    if(plant){
     const fire=props.firePlants.find(f=>f.plantId===plant.properties.plant_id)
     const s=fire?`${fire.label??'数据来源：接口测试'} · ${fire.statusText}`:plant.properties.plant_id==='GEM_COAL_ZHIJIN'&&props.demoActive?'数据来源：仿真':plant.properties.plant_id===props.testPlantId?'接口测试数据':'火情数据未接入'
     return `${plant.properties.name}<br/>${plant.properties.capacity_mw?.toLocaleString()??'未知'} MW · ${s}`
    }
    const code=props.boundaries.features.find(f=>f.properties.name===params.name)?.properties.code
    return `${params.name}<br/>${props.plants.filter(p=>p.properties.related_province_codes.includes(code??'')).length} 个关联样例`
  }},
  geo:{map:'firex-provinces',roam:true,scaleLimit:{min:0.8,max:6},layoutCenter:['50%','51%'],layoutSize:'98%',aspectScale:0.75,selectedMode:false,...focus,
    label:{show:false},itemStyle:{areaColor:'#152636',borderColor:'#406072',borderWidth:0.65},emphasis:{itemStyle:{areaColor:'#2b5261'},label:{color:'#f4fbff',fontSize:14}},regions},
  series:[{type:'lines',coordinateSystem:'geo',polyline:true,silent:true,data:lines,lineStyle:{color:'#627d90',width:1,opacity:0.75}},
   {type:'scatter',coordinateSystem:'geo',symbolSize:(val:number[],params:unknown)=>((params as {data:{plantId:string}}).data.plantId===props.selectedPlant?17:10),
    itemStyle:{color:'#56e3bb',borderColor:'#c4ffe8',borderWidth:1.5,shadowColor:'#4eddb8',shadowBlur:10},
    data:points.map(p=>({name:p.properties.name,value:[...p.geometry.coordinates,1],plantId:p.properties.plant_id})),z:10},
   {type:'scatter',coordinateSystem:'geo',symbolSize:14,itemStyle:{color:'#ff9a3c',borderColor:'#ffd9a8',borderWidth:1.5,shadowColor:'#ff9a3c',shadowBlur:12},data:testPoints.map(p=>({name:p.properties.name,value:[...p.geometry.coordinates,1],plantId:p.properties.plant_id})),z:11},
   {type:'scatter',coordinateSystem:'geo',symbolSize:15,itemStyle:{color:'#ff6b6b',borderColor:'#ffd0d0',borderWidth:1.5,shadowColor:'#ff6b6b',shadowBlur:14},data:firePoints.map(p=>({name:p.properties.name,value:[...p.geometry.coordinates,1],plantId:p.properties.plant_id})),z:12}],
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
 chart.on('georoam',()=>{userViewport=currentViewport()})
 observer=new ResizeObserver(()=>chart?.resize());observer.observe(host.value!);indexBounds();draw()
})
watch(()=>[props.province,props.selectedPlant,props.plants,props.demoActive,props.testPlantId,props.firePlants],()=>draw())
onBeforeUnmount(()=>{observer?.disconnect();chart?.dispose();chart=null})
</script>
<template><div class="map-frame"><div ref="host" class="map-canvas" aria-label="中国省级地图，选择省份或电厂后自动定位和放大，可滚轮缩放"></div><button class="map-reset icon-button" @click="draw(true)" aria-label="重置地图取景" title="重置地图取景"><RotateCcw :size="17"/></button><div class="map-legend"><span class="sample-dot"></span>电厂样例<span class="fire-dot"></span>收到火情观测<span class="legend-line"></span>省级边界</div></div></template>
<style scoped>
.fire-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ff6b6b;box-shadow:0 0 6px #ff6b6b}
</style>
