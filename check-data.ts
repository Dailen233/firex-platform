import { readFileSync,writeFileSync,mkdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import assert from 'node:assert/strict'
import type { Plant,SceneLink,SceneObject,SceneManifest,Boundaries } from '../src/lib/types.ts'
const checks:{id:string;result:string}[]=[]
function check(id:string,run:()=>void){run();checks.push({id,result:'passed'})}
const read=<T>(path:string):T=>JSON.parse(readFileSync(path,'utf8')) as T
const plants=read<{features:Plant[]}>('public/data/plants_frontend.geojson').features
const links=read<{scenes:SceneLink[]}>('public/data/scene_index.json').scenes
const manifest=read<SceneManifest>('public/models/zhijin-v4/scene_manifest.json')
const objects=read<{objects:SceneObject[]}>('public/models/zhijin-v4/object_registry.json').objects
const boundaries=read<Boundaries>('public/data/provinces.geojson')
const model=readFileSync('public/models/zhijin-v4/assets/zhijin_scene_v4.glb')
check('DATA-01-unique-plant-ids',()=>{assert.equal(plants.length,7);assert.equal(new Set(plants.map(p=>p.properties.plant_id)).size,7)})
check('DATA-02-associated-province-counts',()=>{for(const [code,n] of [['520000',1],['510000',6],['530000',4],['110000',0]] as const)assert.equal(plants.filter(p=>p.properties.related_province_codes.includes(code)).length,n)})
check('DATA-03-primary-province-is-associated',()=>{for(const p of plants)assert.ok(p.properties.related_province_codes.includes(p.properties.province_code))})
check('DATA-04-unknown-fire-stays-null',()=>{for(const p of plants){assert.equal(p.properties.current_alert_level,null);assert.equal(p.properties.fire_monitoring_status,'not_connected')}})
check('DATA-05-province-geometry-and-join',()=>{assert.equal(boundaries.features.length,34);assert.equal(new Set(boundaries.features.map(f=>f.properties.code)).size,34);for(const f of boundaries.features){assert.match(f.properties.code!,/^\d{6}$/);assert.ok(['Polygon','MultiPolygon'].includes(f.geometry.type))}for(const p of plants)for(const code of p.properties.related_province_codes)assert.ok(boundaries.features.some(f=>f.properties.code===code))})
check('DATA-06-only-zhijin-has-model',()=>{assert.equal(links.length,1);assert.equal(links[0]!.plant_id,'GEM_COAL_ZHIJIN');assert.equal(links[0]!.scene_id,manifest.scene_id);assert.equal(plants.filter(p=>p.properties.scene_ready).length,1)})
check('ASSET-01-original-byte-hash',()=>{assert.equal(model.length,6717876);assert.equal(createHash('sha256').update(model).digest('hex'),'ee33bc331332d7345bb73e3a1363f9ce49234da7ec3424996ec5670f07a3aa37')})
check('ASSET-02-glb-structure',()=>{assert.equal(model.readUInt32LE(0),0x46546c67);assert.equal(model.readUInt32LE(4),2);assert.equal(model.readUInt32LE(8),model.length)})
const glb=JSON.parse(model.subarray(20,20+model.readUInt32LE(12)).toString('utf8')) as {nodes:{name:string;mesh?:number;translation?:number[];rotation?:number[];scale?:number[]}[];meshes:{primitives:{indices:number}[]}[];accessors:{count:number}[]}
check('ASSET-03-registry-mesh-identity',()=>{const nodes=glb.nodes.filter(n=>n.mesh!==undefined);assert.equal(nodes.length,38);assert.equal(objects.length,38);assert.equal(new Set(objects.map(o=>o.object_id)).size,38);for(const o of objects)assert.equal(nodes.filter(n=>n.name===o.glb_node_name).length,1)})
check('ASSET-04-triangle-count',()=>{assert.equal(glb.meshes.reduce((sum,m)=>sum+m.primitives.reduce((s,p)=>s+glb.accessors[p.indices]!.count/3,0),0),340572)})
check('ASSET-05-display-assumptions-preserved',()=>{assert.equal(objects.find(o=>o.object_id==='B01')!.display_height_m,30);assert.equal(objects.find(o=>o.object_id==='CT-A')!.display_height_m,150);assert.equal(objects.find(o=>o.object_id==='CH01')!.display_height_m,240);assert.ok(objects.find(o=>o.object_id==='B01')!.original_GBA_height_prediction_m!<8)})
check('DATA-07-official-capacity-conflict-preserved',()=>{const p=plants.find(p=>p.properties.plant_id==='GEM_HYDRO_XIANGJIABA')!;assert.equal(p.properties.capacity_mw,6400);assert.equal(p.properties.capacity_source_conflict!.gem_value_mw,7750)})
mkdirSync('evidence',{recursive:true});writeFileSync('evidence/data-checks.json',JSON.stringify({date:'2026-10-09',count:checks.length,checks},null,2)+'\n')
console.log(JSON.stringify({checks:checks.length,result:'passed',model_sha256:manifest.asset.sha256,province_count:34}))
