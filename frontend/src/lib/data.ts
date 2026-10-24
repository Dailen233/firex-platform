import { shallowRef } from 'vue'
import type { Plant, Boundaries, SceneLink } from './types'
import { EXPECTED_SAMPLE_PLANTS } from './catalog-config'

export const assetUrl = (path: string) => new URL(`${import.meta.env.BASE_URL}${path}`, window.location.origin).href
export const resolveResource = (resource: string, manifestUrl: string) => new URL(resource, manifestUrl).href
export async function readJson<T>(url:string, signal?:AbortSignal):Promise<T> {
  const requestSignal=signal?AbortSignal.any([signal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000)
  const res=await fetch(url,{signal:requestSignal})
  if(!res.ok) throw new Error(`资源读取失败（HTTP ${res.status}）`)
  try{return await res.json() as T}catch{throw new Error('资源不是有效的 JSON 文件')}
}
export const plants=shallowRef<Plant[]>([])
export const boundaries=shallowRef<Boundaries|null>(null)
export const boundaryLines=shallowRef<Boundaries|null>(null)
export const sceneLinks=shallowRef<SceneLink[]>([])
export const dataError=shallowRef('')
export const boundaryError=shallowRef('')
export const dataReady=shallowRef(false)
let inFlight:Promise<void>|null=null
export async function loadCatalog(){
  if(dataReady.value && boundaries.value && !boundaryError.value) return
  if(inFlight) return inFlight
  inFlight=(async()=>{
    dataError.value=''; boundaryError.value=''
    try {
      const [collection,index]=await Promise.all([
        readJson<{features:Plant[]}>(assetUrl('data/plants_frontend.geojson')),
        readJson<{scenes:SceneLink[]}>(assetUrl('data/scene_index.json')),
      ])
      if(collection.features.length!==EXPECTED_SAMPLE_PLANTS||new Set(collection.features.map(p=>p.properties.plant_id)).size!==EXPECTED_SAMPLE_PLANTS) throw new Error('电厂目录格式不符合首轮交接约定')
      plants.value=collection.features;sceneLinks.value=index.scenes;dataReady.value=true
    }catch(e){dataError.value=e instanceof Error?e.message:'目录读取失败'}
    try{
      const [b,l]=await Promise.all([readJson<Boundaries>(assetUrl('data/provinces.geojson')),readJson<Boundaries>(assetUrl('data/boundary-lines.geojson'))])
      if(b.features.length!==34)throw new Error('省级边界数量校验失败')
      boundaries.value=b;boundaryLines.value=l
    }catch(e){boundaryError.value=e instanceof Error?e.message:'边界读取失败'}
  })().finally(()=>{inFlight=null})
  return inFlight
}
export function relatedPlants(code:string){return plants.value.filter(p=>p.properties.related_province_codes.includes(code))}
// 正式模型场景（asset_role=formal_model）：仅织金。参考底座等预览资产不在其中。
export function sceneFor(id:string){return sceneLinks.value.find(s=>s.plant_id===id&&s.asset_role==='formal_model')}
// 公开参考底座场景（asset_role=public_reference_terrain）：双江口山地参考。
export function referenceSceneFor(id:string){return sceneLinks.value.find(s=>s.plant_id===id&&s.asset_role==='public_reference_terrain')}
// 按场景 ID 取链接（SceneView 路由 /scene/:sceneId 使用）。
export function sceneBySceneId(sceneId:string){return sceneLinks.value.find(s=>s.scene_id===sceneId)}
export function capacityScope(p:Plant){
  switch(p.properties.plant_id){
    case 'GEM_HYDRO_WUDONGDE':return '电站总装机容量；三峡集团资料'
    case 'GEM_HYDRO_XIANGJIABA':return '2025-11-10 官方报道总装机；非实时出力'
    case 'GEM_COAL_ZHIJIN':return '一期两台 660 MW 运行机组；未计入扩建'
    case 'GEM_HYDRO_XILUODU':return 'GEM 电站容量；当前运行调整待核查'
    case 'GEM_HYDRO_SHUANGJIANGKOU':return 'GEM 记录 2000 MW（4×500 MW）；口径待核'
    default:return 'GEM 名义装机容量；非实时出力'
  }
}
export function identityLabel(status:string){
  if(status.includes('unverified')||status==='unassigned')return '身份未核实'
  if(status.includes('report'))return '资料参考'
  return '参考对象，待核实'
}
export function heightLabel(o:{object_id:string;height_status?:string}){
  if(o.object_id==='terrain')return '地形与平台估计'
  if(o.object_id==='CH01')return '报告记载高度；外形仍含假设'
  if(o.object_id==='B01'||o.object_id.startsWith('CT-'))return '展示假设，非实测'
  return '资料预测，非实测'
}
