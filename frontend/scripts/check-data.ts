import { readFileSync,writeFileSync,mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import assert from 'node:assert/strict'
import type { Plant,SceneLink,SceneObject,SceneManifest,Boundaries,SceneProfile,ReferenceMarker } from '../src/lib/types.ts'
import { validateFireStateDemo,resolveActivePatches,pointInRingXZ } from '../src/lib/fire-demo-schema.ts'
import { EXPECTED_SAMPLE_PLANTS } from '../src/lib/catalog-config.ts'
import { sampleHeightOnTerrain } from '../src/lib/terrain-sampling.ts'
import { validateRunState,snapshotToActiveFirePatches,revisionDecision,validateSnapshotAgainstRun,type BackendRunState,type BackendRunRecord,type SceneBinding } from '../src/lib/backend-contract.ts'
// 脚本位于 frontend/scripts/，路径解析与 cwd 无关：
// - public/* 资源相对于 frontend/ 解析；
// - evidence/* 产物写回仓库根，避免生成 frontend/evidence 重复目录。
const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = join(frontendDir, '..')
const checks:{id:string;result:string}[]=[]
function check(id:string,run:()=>void){run();checks.push({id,result:'passed'})}
const read=<T>(path:string):T=>JSON.parse(readFileSync(join(frontendDir,path),'utf8')) as T
const plants=read<{features:Plant[]}>('public/data/plants_frontend.geojson').features
const links=read<{scenes:SceneLink[]}>('public/data/scene_index.json').scenes
const manifest=read<SceneManifest>('public/models/zhijin-v4/scene_manifest.json')
const objects=read<{objects:SceneObject[]}>('public/models/zhijin-v4/object_registry.json').objects
const boundaries=read<Boundaries>('public/data/provinces.geojson')
const model=readFileSync(join(frontendDir,'public/models/zhijin-v4/assets/zhijin_scene_v4.glb'))
const sjkModel=readFileSync(join(frontendDir,'public/models/shuangjiangkou-reference-v1/terrain_reference.glb'))
const sjkProfile=read<SceneProfile>('public/models/shuangjiangkou-reference-v1/scene_profile.json')
const sjkCoord=read<{coordinate_frame_id:string;proposed_study_area:{projected_area_km2:number;is_actual_model_delivery_extent:boolean}}>('public/data/shuangjiangkou/coordinate_reference.json')
const sjkOverlay=read<{markers:ReferenceMarker[]}>('public/data/shuangjiangkou/overlay_demo_reference.json')
const sjkStudy=read<{features:{properties:{is_proposed?:boolean}}[]}>('public/data/shuangjiangkou/study_area_proposed.geojson')
const protoTerrain=read<SceneProfile>('public/models/sjk-prototype-v0.1/scene_profile_terrain.json')
const protoConcept=read<SceneProfile>('public/models/sjk-prototype-v0.1/scene_profile_concept.json')
const protoTerrainGlb=readFileSync(join(frontendDir,'public/models/sjk-prototype-v0.1/team_terrain_untextured_m.glb'))
const protoConceptGlb=readFileSync(join(frontendDir,'public/models/sjk-prototype-v0.1/sjk_concept_layout.glb'))
const simProfile=read<SceneProfile>('public/models/sjk-hydropower-sim-v0.1/scene_profile.json')
const simRegistry=read<{scene_id:string;coordinate_frame_id:string;objects:SceneObject[]}>('public/models/sjk-hydropower-sim-v0.1/scene_objects.json')
const simObjects=simRegistry.objects
const simGlb=readFileSync(join(frontendDir,'public/models/sjk-hydropower-sim-v0.1/sjk_hydropower_sim_v0_1.glb'))
check('DATA-01-unique-plant-ids',()=>{assert.equal(plants.length,EXPECTED_SAMPLE_PLANTS);assert.equal(new Set(plants.map(p=>p.properties.plant_id)).size,EXPECTED_SAMPLE_PLANTS)})
check('DATA-02-associated-province-counts',()=>{for(const [code,n] of [['520000',1],['510000',7],['530000',4],['110000',0]] as const)assert.equal(plants.filter(p=>p.properties.related_province_codes.includes(code)).length,n)})
check('DATA-03-primary-province-is-associated',()=>{for(const p of plants)assert.ok(p.properties.related_province_codes.includes(p.properties.province_code))})
check('DATA-04-unknown-fire-stays-null',()=>{for(const p of plants){assert.equal(p.properties.current_alert_level,null);assert.equal(p.properties.fire_monitoring_status,'not_connected')}})
check('DATA-05-province-geometry-and-join',()=>{assert.equal(boundaries.features.length,34);assert.equal(new Set(boundaries.features.map(f=>f.properties.code)).size,34);for(const f of boundaries.features){assert.match(f.properties.code!,/^\d{6}$/);assert.ok(['Polygon','MultiPolygon'].includes(f.geometry.type))}for(const p of plants)for(const code of p.properties.related_province_codes)assert.ok(boundaries.features.some(f=>f.properties.code===code))})
check('DATA-06-scene-links-and-formal-ready',()=>{
 assert.equal(links.length,5)
 const formal=links.filter(l=>l.asset_role==='formal_model')
 const ref=links.filter(l=>l.asset_role==='public_reference_terrain')
 const proto=links.filter(l=>l.asset_role==='prototype_model')
 assert.equal(formal.length,1);assert.equal(formal[0]!.plant_id,'GEM_COAL_ZHIJIN');assert.equal(formal[0]!.scene_id,manifest.scene_id)
 assert.equal(ref.length,1);assert.equal(ref[0]!.scene_id,'shuangjiangkou_reference_terrain');assert.equal(ref[0]!.formal_model_ready,false)
 assert.equal(proto.length,3)
 assert.deepEqual(proto.map(l=>l.scene_id).sort(),['sjk_facility_concept_v0_1','sjk_hydropower_sim_v0_1','sjk_team_terrain_draft_v0_1'])
 for(const p of proto){assert.equal(p.plant_id,'GEM_HYDRO_SHUANGJIANGKOU');assert.equal(p.formal_model_ready,false)}
 assert.equal(plants.filter(p=>p.properties.scene_ready).length,1)
})
check('ASSET-01-original-byte-hash',()=>{assert.equal(model.length,6717876);assert.equal(createHash('sha256').update(model).digest('hex'),'ee33bc331332d7345bb73e3a1363f9ce49234da7ec3424996ec5670f07a3aa37')})
check('ASSET-02-glb-structure',()=>{assert.equal(model.readUInt32LE(0),0x46546c67);assert.equal(model.readUInt32LE(4),2);assert.equal(model.readUInt32LE(8),model.length)})
const glb=JSON.parse(model.subarray(20,20+model.readUInt32LE(12)).toString('utf8')) as {nodes:{name:string;mesh?:number;translation?:number[];rotation?:number[];scale?:number[]}[];meshes:{primitives:{indices:number}[]}[];accessors:{count:number}[]}
check('ASSET-03-registry-mesh-identity',()=>{const nodes=glb.nodes.filter(n=>n.mesh!==undefined);assert.equal(nodes.length,38);assert.equal(objects.length,38);assert.equal(new Set(objects.map(o=>o.object_id)).size,38);for(const o of objects)assert.equal(nodes.filter(n=>n.name===o.glb_node_name).length,1)})
check('ASSET-04-triangle-count',()=>{assert.equal(glb.meshes.reduce((sum,m)=>sum+m.primitives.reduce((s,p)=>s+glb.accessors[p.indices]!.count/3,0),0),340572)})
check('ASSET-05-display-assumptions-preserved',()=>{assert.equal(objects.find(o=>o.object_id==='B01')!.display_height_m,30);assert.equal(objects.find(o=>o.object_id==='CT-A')!.display_height_m,150);assert.equal(objects.find(o=>o.object_id==='CH01')!.display_height_m,240);assert.ok(objects.find(o=>o.object_id==='B01')!.original_GBA_height_prediction_m!<8)})
check('DATA-07-official-capacity-conflict-preserved',()=>{const p=plants.find(p=>p.properties.plant_id==='GEM_HYDRO_XIANGJIABA')!;assert.equal(p.properties.capacity_mw,6400);assert.equal(p.properties.capacity_source_conflict!.gem_value_mw,7750)})
check('SJK-01-reference-profile-asset',()=>{
 assert.equal(sjkProfile.scene_id,'shuangjiangkou_reference_terrain')
 assert.equal(sjkProfile.asset_role,'public_reference_terrain')
 assert.equal(sjkProfile.formal_model_ready,false)
 assert.equal(sjkProfile.asset.bytes,sjkModel.length)
 assert.equal(createHash('sha256').update(sjkModel).digest('hex'),sjkProfile.asset.sha256)
 assert.equal(sjkProfile.asset.sha256,'1f699b50e750607ae1410517fef4aeacf931418f516b2bf195d4b2ffd497a468')
 assert.equal(sjkProfile.asset.vertex_count,40401);assert.equal(sjkProfile.asset.triangles,80000)
})
check('SJK-02-reference-glb-structure',()=>{assert.equal(sjkModel.readUInt32LE(0),0x46546c67);assert.equal(sjkModel.readUInt32LE(4),2);assert.equal(sjkModel.readUInt32LE(8),sjkModel.length)})
check('SJK-03-markers-frame-consistent',()=>{
 assert.equal(sjkOverlay.markers.length,3)
 for(const m of sjkOverlay.markers){
  assert.equal(m.scene_id,sjkProfile.scene_id);assert.equal(m.asset_version,sjkProfile.asset_version)
  assert.equal(m.coordinate_frame_id,sjkProfile.coordinate_frame_id);assert.equal(m.coordinate_frame_id,sjkCoord.coordinate_frame_id)
  assert.ok(m.local_xyz_m.every(Number.isFinite));assert.ok(m.lon_lat_wgs84.every(Number.isFinite))
  assert.equal(m.surface_y_m,m.local_xyz_m[1]-m.display_offset_m)
 }
})
check('SJK-04-study-area-proposed',()=>{
 assert.equal(sjkStudy.features.length,1);assert.equal(sjkStudy.features[0]!.properties.is_proposed,true)
 assert.equal(sjkCoord.proposed_study_area.is_actual_model_delivery_extent,false);assert.equal(sjkCoord.proposed_study_area.projected_area_km2,100)
})
check('SJK-05-formal-model-not-ready-and-points-sourced',()=>{
 const p=plants.find(p=>p.properties.plant_id==='GEM_HYDRO_SHUANGJIANGKOU')!
 assert.equal(p.properties.scene_ready,false);assert.equal(p.properties.formal_model_status,'awaiting_file');assert.equal(p.properties.scene_id,null)
 assert.equal(p.geometry.coordinates[0],101.92361870372959);assert.equal(p.geometry.coordinates[1],31.792757792141334)
 const ms=p.properties.research_area_markers
 assert.ok(ms&&ms.length===3)
 for(const m of ms){assert.equal(m.verification_status,'public_map_reference');assert.ok(m.source_url&&m.source_url.startsWith('https://www.openstreetmap.org/'))}
})
check('PROTO-01-terrain-draft-asset',()=>{
 assert.equal(protoTerrain.scene_id,'sjk_team_terrain_draft_v0_1')
 assert.equal(protoTerrain.asset_role,'prototype_model')
 assert.equal(protoTerrain.formal_model_ready,false);assert.equal(protoTerrain.registration_status,'unregistered')
 assert.equal(protoTerrain.capabilities.fire_patch_overlay,false);assert.equal(protoTerrain.capabilities.object_selection,false)
 assert.equal(protoTerrain.model_uri,'team_terrain_untextured_m.glb');assert.equal(protoTerrain.terrain_mesh_name,'team_fbx_terrain_129')
 assert.equal(protoTerrain.asset.bytes,protoTerrainGlb.length)
 assert.equal(createHash('sha256').update(protoTerrainGlb).digest('hex'),protoTerrain.asset.sha256)
 assert.equal(protoTerrain.asset.sha256,'fc61cb277f115af0537967d8324b9c43c7042b1d5a6c0f5ec45f075641dd0789')
 assert.equal(protoTerrain.asset.triangles,32768);assert.equal(protoTerrain.asset.vertex_count,16641)
})
check('PROTO-02-concept-draft-asset',()=>{
 assert.equal(protoConcept.scene_id,'sjk_facility_concept_v0_1')
 assert.equal(protoConcept.asset_role,'prototype_model')
 assert.equal(protoConcept.formal_model_ready,false);assert.equal(protoConcept.registration_status,'unregistered')
 assert.equal(protoConcept.capabilities.fire_patch_overlay,false);assert.equal(protoConcept.capabilities.object_selection,false)
 assert.equal(protoConcept.model_uri,'sjk_concept_layout.glb');assert.equal(protoConcept.terrain_mesh_name,null)
 assert.equal(protoConcept.asset.bytes,protoConceptGlb.length)
 assert.equal(createHash('sha256').update(protoConceptGlb).digest('hex'),protoConcept.asset.sha256)
 assert.equal(protoConcept.asset.sha256,'41fd0be44fcc0c99b51e9b4005a345151d0f518ad8ec85d9eaacfb151d252d88')
 assert.equal(protoConcept.asset.mesh_count,7)
})
check('PROTO-03-glb-root-transform-identity',()=>{
 for(const glb of [protoTerrainGlb,protoConceptGlb]){
  assert.equal(glb.readUInt32LE(0),0x46546c67);assert.equal(glb.readUInt32LE(4),2);assert.equal(glb.readUInt32LE(8),glb.length)
  const j=JSON.parse(glb.subarray(20,20+glb.readUInt32LE(12)).toString('utf8')) as {scenes:{nodes:number[]}[];nodes:{matrix?:number[];translation?:number[];rotation?:number[];scale?:number[]}[]}
  const root=j.nodes[j.scenes[0]!.nodes[0]!]!
  assert.equal(root.matrix??null,null);assert.equal(root.translation??null,null);assert.equal(root.rotation??null,null);assert.equal(root.scale??null,null)
 }
})
check('PROTO-04-unregistered-frame-isolated',()=>{
 for(const p of [protoTerrain,protoConcept]){
  assert.notEqual(p.coordinate_frame_id,'SJK_REFERENCE_UTM47N_EGM2008_v1')
  assert.ok(p.coordinate_frame_id!.includes('UNREGISTERED')||p.coordinate_frame_id!.includes('STAGING'))
 }
})
check('SIM-01-profile-asset',()=>{
 assert.equal(simProfile.scene_id,'sjk_hydropower_sim_v0_1')
 assert.equal(simProfile.plant_id,'GEM_HYDRO_SHUANGJIANGKOU')
 assert.equal(simProfile.asset_role,'prototype_model');assert.equal(simProfile.formal_model_ready,false)
 assert.equal(simProfile.registration_status,'unregistered');assert.equal(simProfile.scene_badge,'模拟厂区 · 未配准')
 assert.equal(simProfile.capabilities.fire_patch_overlay,false);assert.equal(simProfile.capabilities.object_selection,true)
 assert.equal(simProfile.model_uri,'sjk_hydropower_sim_v0_1.glb');assert.equal(simProfile.object_registry_uri,'scene_objects.json')
 assert.equal(simProfile.terrain_mesh_name,null);assert.equal(simProfile.asset.textures_present,true)
 assert.equal(simProfile.asset.bytes,simGlb.length)
 assert.equal(createHash('sha256').update(simGlb).digest('hex'),simProfile.asset.sha256)
 assert.equal(simProfile.asset.sha256,'722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91')
 assert.equal(simProfile.asset.triangles,45506);assert.equal(simProfile.asset.vertex_count,41919)
 assert.equal(simProfile.asset.mesh_count,13);assert.equal(simProfile.asset.object_meshes,13)
})
check('SIM-02-glb-structure-root-identity-texture',()=>{
 assert.equal(simGlb.readUInt32LE(0),0x46546c67);assert.equal(simGlb.readUInt32LE(4),2);assert.equal(simGlb.readUInt32LE(8),simGlb.length)
 const j=JSON.parse(simGlb.subarray(20,20+simGlb.readUInt32LE(12)).toString('utf8')) as {scenes:{nodes:number[]}[];nodes:{name?:string;mesh?:number;matrix?:number[];translation?:number[];rotation?:number[];scale?:number[]}[];images?:{mimeType?:string}[]}
 const root=j.nodes[j.scenes[0]!.nodes[0]!]!
 assert.equal(root.matrix??null,null);assert.equal(root.translation??null,null);assert.equal(root.rotation??null,null);assert.equal(root.scale??null,null)
 assert.ok(j.images&&j.images.some(i=>i.mimeType==='image/png'))
})
check('SIM-03-registry-bijective',()=>{
 const nodes=(JSON.parse(simGlb.subarray(20,20+simGlb.readUInt32LE(12)).toString('utf8')) as {nodes:{name?:string;mesh?:number}[]}).nodes.filter(n=>n.mesh!==undefined)
 assert.equal(nodes.length,13);assert.equal(simObjects.length,13)
 assert.equal(new Set(simObjects.map(o=>o.object_id)).size,13)
 assert.equal(new Set(simObjects.map(o=>o.glb_node_name)).size,13)
 for(const o of simObjects)assert.equal(nodes.filter(n=>n.name===o.glb_node_name).length,1)
 assert.equal(simRegistry.scene_id,simProfile.scene_id);assert.equal(simRegistry.coordinate_frame_id,simProfile.coordinate_frame_id)
})
check('SIM-04-unregistered-frame-isolated',()=>{
 assert.notEqual(simProfile.coordinate_frame_id,'SJK_REFERENCE_UTM47N_EGM2008_v1')
 assert.ok(simProfile.coordinate_frame_id!.includes('UNREGISTERED'))
})
const fireRaw=read<unknown>('public/data/fire_state_demo.json')
const fireResult=validateFireStateDemo(fireRaw)
check('FIRE-DEMO-01-contract-valid',()=>{assert.ok(fireResult.ok,fireResult.ok?'':`演示契约校验失败：${fireResult.errors.join('；')}`);if(fireResult.ok)assert.equal(fireResult.demo.patches.length,2)})
check('FIRE-DEMO-02-keyframe-boundaries',()=>{
 if(!fireResult.ok)throw new Error('演示契约无效')
 const d=fireResult.demo
 const active=(t:number)=>resolveActivePatches(d,t).map(p=>p.patch_id).sort()
 assert.deepEqual(active(0),[])
 assert.deepEqual(active(20),['DEMO-ZHIJIN-P01'])
 assert.deepEqual(active(40),['DEMO-ZHIJIN-P01','DEMO-ZHIJIN-P02'])
 assert.deepEqual(active(80),['DEMO-ZHIJIN-P02'])
 assert.deepEqual(active(120),['DEMO-ZHIJIN-P02'])
})
check('FIRE-DEMO-03-ring-point-test',()=>{
 if(!fireResult.ok)throw new Error('演示契约无效')
 const ring=fireResult.demo.patches[0]!.rings[0]!.ring_xz
 assert.ok(pointInRingXZ(1000,-1000,ring))
 assert.ok(!pointInRingXZ(800,-1000,ring))
 assert.ok(!pointInRingXZ(2000,-1000,ring))
})
check('FIRE-DEMO-04-rejects-invalid',()=>{
 const base=()=>({schema:'Fire-X fire_state demo',schema_version:'1.0',is_mock:true,demo_origin:'synthetic_demo_rule',plant_id:'GEM_COAL_ZHIJIN',scene_id:'zhijin_pilot',duration_s:100,patches:[{patch_id:'P1',plant_id:'GEM_COAL_ZHIJIN',scene_id:'zhijin_pilot',is_mock:true,rings:[{ring_xz:[[0,0],[100,0],[100,100],[0,100]],ground_offset_m:0.5}],keyframes:[{t_s:0,active:true}]}],rules:{spread_note:'x',disclaimer:'y'}})
 const a=base();a.schema_version='9.9';assert.equal(validateFireStateDemo(a).ok,false)
 const b=base();b.patches[0]!.rings[0]!.ring_xz=[[0,0],[10,10],[0,10],[10,0]];assert.equal(validateFireStateDemo(b).ok,false)
 const c=base();c.patches[0]!.rings[0]!.ring_xz=[[0,0],[3000,0],[3000,100],[0,100]];assert.equal(validateFireStateDemo(c).ok,false)
 const d=base();d.patches.push({patch_id:'P1',plant_id:'GEM_COAL_ZHIJIN',scene_id:'zhijin_pilot',is_mock:true,rings:[{ring_xz:[[0,0],[10,0],[10,10],[0,10]],ground_offset_m:0.5}],keyframes:[]});assert.equal(validateFireStateDemo(d).ok,false)
 const e=base();e.is_mock=false;assert.equal(validateFireStateDemo(e).ok,false)
 const f=base();f.patches[0]!.rings[0]!.ground_offset_m=1.5;assert.equal(validateFireStateDemo(f).ok,false)
 const g=base();g.patches[0]!.rings[0]!.ground_offset_m=1.0;assert.equal(validateFireStateDemo(g).ok,true)
})
check('SAMPLE-01-noncoplanar-triangle-height',()=>{
 // 2x2 非共面合成地形：顶点 (0,0,0)(50,0,0)(0,0,50)(50,100,50)，索引 [0,1,2, 1,3,2]。
 const positions=[0,0,0, 50,0,0, 0,0,50, 50,100,50]
 const indices=[0,1,2, 1,3,2]
 // XZ=(25,25) 在三角(0,1,2)面上，实际高度 0（双线性会给 25）。
 assert.equal(sampleHeightOnTerrain(25,25,positions,indices),0)
 // XZ=(37.5,37.5) 在三角(1,3,2)斜面上，实际高度 50。
 assert.equal(sampleHeightOnTerrain(37.5,37.5,positions,indices),50)
 // 范围外 -> null。
 assert.equal(sampleHeightOnTerrain(60,60,positions,indices),null)
})
check('BACKEND-01-state-validation-rejects-invalid',()=>{
 const base={run_id:'r1',plant_id:'P',scene_id:'S',asset_version:'v1',coordinate_frame_id:'F',input_source:'simulation',schema_version:'1.0',state_status:'observation',revision:1,observation_time_s:5.0,result_origin:'fixture',provider_version:'1.0',evidence_capture_ids:['c1'],patches:[{patch_id:'p1',geometry:[[0,0],[1,0],[1,1],[0,0]]}],produced_at:'2026-01-01T00:00:00Z',time_basis:'simulation_relative',simulation_time_origin_s:10.0,time_origin_utc:null}
 assert.equal(validateRunState(base).ok,true)
 assert.equal(validateRunState({...base,revision:-1.5}).ok,false) // 负小数 revision
 assert.equal(validateRunState({...base,revision:1.5}).ok,false) // 非整数 revision
 assert.equal(validateRunState({...base,input_source:'weird'}).ok,false) // 未知 input_source
 assert.equal(validateRunState({...base,result_origin:null}).ok,false) // 缺失来源
 assert.equal(validateRunState({...base,evidence_capture_ids:[123]}).ok,false) // 非字符串证据 ID
 assert.equal(validateRunState({...base,patches:[{patch_id:'p1',geometry:[[0,0],[1,0],[1,1],[0,1]]}]}).ok,false) // 未闭合
})
check('BACKEND-02-mapping-requires-frame-and-binding',()=>{
 const snap:BackendRunState={run_id:'r1',plant_id:'P',scene_id:'S',asset_version:'v1',coordinate_frame_id:null,input_source:'simulation',schema_version:'1.0',state_status:'observation',revision:1,observation_time_s:5.0,result_origin:'fixture',provider_version:'1.0',evidence_capture_ids:['c1'],patches:[{patch_id:'p1',geometry:[[0,0],[1,0],[1,1],[0,0]]}],produced_at:'x',time_basis:'simulation_relative',simulation_time_origin_s:10.0,time_origin_utc:null}
 const binding:SceneBinding={plant_id:'P',scene_id:'S',asset_version:'v1',coordinate_frame_id:'F'}
 const r1=snapshotToActiveFirePatches(snap,binding) // 观测缺失坐标系 -> 拒绝
 assert.equal(r1.patches.length,0);assert.ok(r1.bindingError)
 const r2=snapshotToActiveFirePatches({...snap,coordinate_frame_id:'F'},{...binding,plant_id:'OTHER'}) // plant 不符
 assert.equal(r2.patches.length,0);assert.ok(r2.bindingError)
 const r3=snapshotToActiveFirePatches({...snap,coordinate_frame_id:'F'},binding) // 匹配
 assert.equal(r3.patches.length,1);assert.equal(r3.bindingError,null);assert.equal(r3.patches[0]!.patch_id,'p1')
})
check('BACKEND-03-revision-decision',()=>{
 assert.equal(revisionDecision(2,3),'accept')
 assert.equal(revisionDecision(2,2),'duplicate')
 assert.equal(revisionDecision(2,1),'regression')
})
check('BACKEND-04-binding-mismatch',()=>{
 const run:BackendRunRecord={run_id:'r1',plant_id:'P',scene_id:'S',asset_version:'v1',coordinate_frame_id:'F',input_source:'simulation',schema_version:'1.0',created_at:'x',simulation_time_origin_s:10.0,time_origin_utc:null}
 const snap:BackendRunState={run_id:'r1',plant_id:'P',scene_id:'S',asset_version:'v1',coordinate_frame_id:'F',input_source:'simulation',schema_version:'1.0',state_status:'observation',revision:1,observation_time_s:5.0,result_origin:'fixture',provider_version:'1.0',evidence_capture_ids:['c1'],patches:[{patch_id:'p1',geometry:[[0,0],[1,0],[1,1],[0,0]]}],produced_at:'x',time_basis:'simulation_relative',simulation_time_origin_s:10.0,time_origin_utc:null}
 assert.equal(validateSnapshotAgainstRun(run,snap),null)
 assert.ok(validateSnapshotAgainstRun({...run,run_id:'r2'},snap))
 assert.ok(validateSnapshotAgainstRun({...run,plant_id:'Q'},snap))
 assert.ok(validateSnapshotAgainstRun(run,{...snap,coordinate_frame_id:'G'}))
})
mkdirSync(join(repoRoot,'evidence'),{recursive:true});writeFileSync(join(repoRoot,'evidence/data-checks.json'),JSON.stringify({date:'2026-10-11',count:checks.length,checks},null,2)+'\n')
console.log(JSON.stringify({checks:checks.length,result:'passed',model_sha256:manifest.asset.sha256,province_count:34}))
