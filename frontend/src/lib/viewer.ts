import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { ActiveFirePatch, FireLevel, FireRing, ReferenceMarker, SceneObject, SceneProfile } from './types'
import { assetUrl, readJson, resolveResource } from './data'
import { sampleHeightOnTerrain } from './terrain-sampling'
import { SoftwareRenderer } from './software-renderer'
import { CONTROL_POINTS, TERRAIN_MESH_NAME, UNITY_WORLD_TO_GLB, type LocalRegistrationPointResult } from './dev/sjk-local-registration'

export type FrameKind = 'default' | 'plant' | 'whole_terrain' | 'panorama'
export interface ViewerCallbacks {progress:(percent:number,message:string)=>void;loaded:(profile:SceneProfile,objects:SceneObject[],markers:ReferenceMarker[])=>void;selected:(object:SceneObject|null)=>void;mode:(mode:'webgl'|'software')=>void;overlayIssue?:(message:string|null)=>void}
function releaseModel(root:THREE.Object3D){
 const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>()
 root.traverse(o=>{if(o instanceof THREE.Mesh){geometries.add(o.geometry);for(const m of Array.isArray(o.material)?o.material:[o.material])materials.add(m)}})
 for(const m of materials){for(const v of Object.values(m))if(v instanceof THREE.Texture)textures.add(v);m.dispose()}
 for(const t of textures)t.dispose();for(const g of geometries)g.dispose()
}
function fireColor(level:FireLevel,intensity:number){
 const base=new THREE.Color(level==='critical'?0xff2d1f:level==='warning'?0xff6a1a:0xff9a3c)
 return base.multiplyScalar(0.6+0.4*Math.min(1,Math.max(0,intensity)))
}
export class ModelViewer {
 private renderer:THREE.WebGLRenderer|SoftwareRenderer;private scene=new THREE.Scene();private camera=new THREE.PerspectiveCamera(45,1,1,20000)
 private controls:OrbitControls;private resizeObserver:ResizeObserver;private abort=new AbortController()
 private rafId=0;private disposed=false;private root:THREE.Group|null=null;private objects:SceneObject[]=[]
 private meshes:THREE.Mesh[]=[];private selectedBox:THREE.BoxHelper|null=null;private profile:SceneProfile|null=null
 private previousCameraPosition=new THREE.Vector3();private hasPreviousCameraPosition=false
 private fireOverlay:THREE.Group|null=null;private referenceMarkers:THREE.Group|null=null
 private terrainMesh:THREE.Mesh|null=null;private pendingFirePatches:ActiveFirePatch[]|null=null
 private pointerStart={x:0,y:0};private pointer=new THREE.Vector2();private raycaster=new THREE.Raycaster()
 constructor(private host:HTMLElement,private callback:ViewerCallbacks){
  // A disabled cloud GPU must remain visible as a limitation, not a false GLB failure.
  const probe=document.createElement('canvas').getContext('webgl2')
  if(probe){probe.getExtension('WEBGL_lose_context')?.loseContext();try{this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});callback.mode('webgl')}catch{this.renderer=new SoftwareRenderer();callback.mode('software')}}
  else{this.renderer=new SoftwareRenderer();callback.mode('software')}
  this.renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.5));this.renderer.setClearColor('#0c1927')
  this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.15
  this.renderer.domElement.setAttribute('aria-label','三维模型：拖动旋转、滚轮缩放、右键平移')
  this.host.appendChild(this.renderer.domElement)
  this.scene.add(new THREE.HemisphereLight(0xe0efff,0x9a9981,2.5))
  const sun=new THREE.DirectionalLight(0xfff4df,2.6);sun.position.set(2000,4000,2500);this.scene.add(sun)
  this.controls=new OrbitControls(this.camera,this.renderer.domElement)
  this.controls.enableDamping=true;this.controls.dampingFactor=0.12;this.controls.minDistance=20;this.controls.maxDistance=14000
  this.controls.maxPolarAngle=Math.PI*0.49;this.controls.addEventListener('change',this.requestRender)
  this.renderer.domElement.addEventListener('pointerdown',this.onPointerDown)
  this.renderer.domElement.addEventListener('pointerup',this.onPointerUp)
  this.resizeObserver=new ResizeObserver(this.resize);this.resizeObserver.observe(host)
  this.resize()
 }
 private resize=()=>{
  if(this.disposed)return
  const w=this.host.clientWidth,h=this.host.clientHeight;if(!w||!h)return
  this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.renderer.setSize(w,h,false);this.requestRender()
 }
 private requestRender=()=>{if(!this.disposed&&!this.rafId)this.rafId=requestAnimationFrame(this.render)}
 private render=()=>{this.rafId=0;if(this.disposed)return;this.controls.update();this.resolveCameraCollision();this.renderer.render(this.scene,this.camera)}
 /** Sweep the camera from its previous position to the proposed position. Stop just before
  * the first scene mesh so orbit, zoom and pan cannot move the viewpoint through geometry. */
 private resolveCameraCollision(){
  const current=this.camera.position
  if(!this.hasPreviousCameraPosition){this.previousCameraPosition.copy(current);this.hasPreviousCameraPosition=true;return}
  const movement=current.clone().sub(this.previousCameraPosition)
  const distance=movement.length()
  if(distance>1e-4){
   this.raycaster.set(this.previousCameraPosition,movement.multiplyScalar(1/distance))
   this.raycaster.near=0;this.raycaster.far=distance
   const hit=this.raycaster.intersectObjects(this.meshes,false)[0]
   if(hit?.face){
    const normal=hit.face.normal.clone().applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize()
    const direction=current.clone().sub(this.previousCameraPosition).normalize()
    if(normal.dot(direction)>0)normal.negate()
    const clearance=Math.max(2,this.camera.near*2)
    current.copy(hit.point).addScaledVector(normal,clearance)
   }
  }
  this.previousCameraPosition.copy(current)
 }
 private onPointerDown=(event:PointerEvent)=>{this.pointerStart={x:event.clientX,y:event.clientY}}
 private onPointerUp=(event:PointerEvent)=>{
  if(this.disposed||event.button!==0||Math.hypot(event.clientX-this.pointerStart.x,event.clientY-this.pointerStart.y)>5)return
  if(!this.profile?.capabilities.object_selection){this.select(null);return}
  const rect=this.renderer.domElement.getBoundingClientRect();this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1)
  this.raycaster.setFromCamera(this.pointer,this.camera)
  const hit=this.raycaster.intersectObjects(this.meshes,false)[0]
  if(!hit){this.select(null);return}
  // Name mapping is valid only after this asset's SHA and unique nodes are checked.
  const record=this.objects.find(o=>o.glb_node_name===hit.object.name)
  this.select(record?.object_id??null)
 }
 async load(profileUrl:string){
  const signal=this.abort.signal
  this.callback.progress(0,'读取场景配置')
  const profile=await readJson<SceneProfile>(profileUrl,signal)
  if(!profile.scene_id||!profile.model_uri)throw new Error('场景配置缺少 scene_id 或 model_uri')
  // 对象表：必需对象表却缺失 → 加载失败；未声明对象表 → 可浏览但无对象选择。
  let registryObjects:SceneObject[]=[]
  if(profile.object_registry_required){
   if(!profile.object_registry_uri)throw new Error('场景声明必需对象表，但未提供对象表路径')
   const registry=await readJson<{objects:SceneObject[]}>(resolveResource(profile.object_registry_uri,profileUrl),signal)
   registryObjects=registry.objects
  }else if(profile.object_registry_uri){
   try{registryObjects=(await readJson<{objects:SceneObject[]}>(resolveResource(profile.object_registry_uri,profileUrl),signal)).objects}catch{registryObjects=[]}
  }
  // 参考标记（仅当能力开关开启且绑定本场景）。
  let markers:ReferenceMarker[]=[]
  if(profile.capabilities.reference_markers&&profile.overlay_markers_uri){
   try{
    const data=await readJson<{markers:ReferenceMarker[]}>(assetUrl(profile.overlay_markers_uri),signal)
    markers=data.markers.filter(m=>m.scene_id===profile.scene_id&&m.asset_version===profile.asset_version)
   }catch{markers=[]}
  }
  const modelLabel=profile.display_name??profile.scene_id
  this.callback.progress(5,`下载模型（${modelLabel}）`)
  const response=await fetch(resolveResource(profile.model_uri,profileUrl),{signal:AbortSignal.any([signal,AbortSignal.timeout(45000)])})
  if(!response.ok)throw new Error(`模型读取失败（HTTP ${response.status}）`)
  const parts:Uint8Array[]=[];let size=0
  const totalBytes=profile.asset?.bytes
  if(response.body){const reader=response.body.getReader();while(true){const part=await reader.read();if(part.done)break;parts.push(part.value);size+=part.value.length;if(totalBytes)this.callback.progress(5+Math.min(75,size/totalBytes*75),`下载模型（${modelLabel}）`);else this.callback.progress(5,`下载模型 ${(size/1048576).toFixed(1)} MB`)}}
  else{const bytes=new Uint8Array(await response.arrayBuffer());parts.push(bytes);size=bytes.length}
  const buffer=new Uint8Array(size);let offset=0;for(const part of parts){buffer.set(part,offset);offset+=part.length}
  if(totalBytes&&size!==totalBytes)throw new Error('模型文件大小与交接记录不一致')
  // crypto.subtle is available on HTTPS and localhost. Byte/node checks still apply on plain HTTP LAN previews.
  if(profile.asset?.sha256&&globalThis.crypto?.subtle){
   const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))).map(b=>b.toString(16).padStart(2,'0')).join('')
   if(hash!==profile.asset.sha256)throw new Error('模型文件哈希与交接记录不一致')
  }
  if(this.disposed)return
  this.callback.progress(85,'解析几何并核对对象')
  const gltf=await new GLTFLoader().parseAsync(buffer.buffer,new URL('.',profileUrl).href)
  if(this.disposed){releaseModel(gltf.scene);return}
  this.root=gltf.scene;this.objects=registryObjects;this.profile=profile
  this.meshes=[];this.root.traverse(o=>{if(o instanceof THREE.Mesh)this.meshes.push(o)})
  this.terrainMesh=profile.terrain_mesh_name?this.meshes.find(o=>o.name===profile.terrain_mesh_name)??null:null
  // 对象表一致性仅在声明必需对象表时校验，不强制其他场景有织金对象表。
  if(profile.object_registry_required){
   const names=this.meshes.map(o=>o.name)
   const objectMeshes=profile.asset?.object_meshes??null
   if(objectMeshes!=null&&(this.meshes.length!==objectMeshes||new Set(names).size!==names.length||registryObjects.length!==objectMeshes||registryObjects.some(o=>!names.includes(o.glb_node_name))))throw new Error('对象表与 GLB 节点未能完整对应')
  }
  // Preserve the handed-off local coordinate frame. Fit the camera, never the model.
  if(!this.root.position.equals(new THREE.Vector3())||!this.root.scale.equals(new THREE.Vector3(1,1,1))||!this.root.quaternion.equals(new THREE.Quaternion()))throw new Error('模型根变换不符合局部坐标约定')
  this.scene.add(this.root)
  this.applyCameraLimits(profile)
  this.frame('default')
  this.renderer.domElement.setAttribute('aria-label',`${modelLabel}：拖动旋转、滚轮缩放、右键平移`)
  this.callback.progress(100,'模型已加载');this.callback.loaded(profile,registryObjects,markers)
  this.setReferenceMarkers(markers)
  if(this.pendingFirePatches){const p=this.pendingFirePatches;this.pendingFirePatches=null;this.setFirePatches(p)}
  this.requestRender()
 }
 private applyCameraLimits(p:SceneProfile){
  this.camera.fov=p.cameras.vertical_fov_degrees;this.camera.near=p.camera_limits.near;this.camera.far=p.camera_limits.far
  this.controls.minDistance=p.camera_limits.min_distance;this.controls.maxDistance=p.camera_limits.max_distance
  this.camera.updateProjectionMatrix()
 }
 private applyCamera(cam:{position:[number,number,number];target:[number,number,number]}){
  const target=new THREE.Vector3(...cam.target);let position=new THREE.Vector3(...cam.position)
  // Adapt preset to the viewport's limiting FOV, including a narrow portrait canvas.
  const ratio=Math.max(1,1/this.camera.aspect)
  position=target.clone().add(position.sub(target).multiplyScalar(ratio))
  this.camera.position.copy(position);this.controls.target.copy(target);this.camera.updateProjectionMatrix();this.controls.update();this.requestRender()
 }
 frame(kind:FrameKind){
  if(!this.profile)return
  const c=this.profile.cameras
  if(kind==='panorama'){this.frameBounds(c.panorama.padding_factor);return}
  const cam=kind==='plant'?c.plant:kind==='whole_terrain'?c.whole_terrain:c.default
  if(cam)this.applyCamera(cam)
 }
 private frameBounds(padding:number){
  const box=new THREE.Box3()
  if(this.profile?.bounds_local_m){box.set(new THREE.Vector3(...this.profile.bounds_local_m.min),new THREE.Vector3(...this.profile.bounds_local_m.max))}
  else{for(const m of this.meshes)box.expandByObject(m)}
  if(box.isEmpty())return
  const center=box.getCenter(new THREE.Vector3())
  const radius=box.getBoundingSphere(new THREE.Sphere()).radius
  const fov=this.camera.fov*Math.PI/180
  const dist=(radius/Math.sin(fov/2))*padding*Math.max(1,1/this.camera.aspect)
  const dir=new THREE.Vector3(1,0.65,1).normalize()
  this.camera.position.copy(center.clone().addScaledVector(dir,dist))
  this.controls.target.copy(center);this.camera.updateProjectionMatrix();this.controls.update();this.requestRender()
 }
 /** 相机对准当前火区覆盖层（不改动几何坐标，仅取景）。 */
 frameFire(){
  if(!this.fireOverlay)return
  const box=new THREE.Box3().setFromObject(this.fireOverlay)
  if(box.isEmpty())return
  const size=box.getSize(new THREE.Vector3())
  box.expandByScalar(Math.max(size.length()*0.2,40))
  const center=box.getCenter(new THREE.Vector3())
  const radius=box.getBoundingSphere(new THREE.Sphere()).radius
  const fov=this.camera.fov*Math.PI/180
  const dist=(radius/Math.sin(fov/2))*1.25*Math.max(1,1/this.camera.aspect)
  const dir=new THREE.Vector3(0.5,0.85,1).normalize()
  this.camera.position.copy(center.clone().addScaledVector(dir,dist))
  this.controls.target.copy(center);this.camera.updateProjectionMatrix();this.controls.update();this.requestRender()
 }
 /** E3.1 开发态本地落点核验：按 unity_world_to_glb 转 P5/P6，只对地形网格做垂直射线检测。
 *  不改变模型、不叠火区；仅返回转换点/命中点/残差供开发界面展示。 */
runLocalRegistrationCheck(): LocalRegistrationPointResult[] {
  const terrain = this.meshes.find((m) => m.name === TERRAIN_MESH_NAME)
  if (!terrain) return []
  const m = UNITY_WORLD_TO_GLB.flat()
  const matrix = new THREE.Matrix4().set(
    m[0], m[1], m[2], m[3],
    m[4], m[5], m[6], m[7],
    m[8], m[9], m[10], m[11],
    m[12], m[13], m[14], m[15],
  )
  const raycaster = new THREE.Raycaster()
  const down = new THREE.Vector3(0, -1, 0)
  const results: LocalRegistrationPointResult[] = []
  for (const cp of CONTROL_POINTS) {
    const glb = new THREE.Vector3(...cp.unity_world_xyz).applyMatrix4(matrix)
    const expected = new THREE.Vector3(...cp.expected_glb_xyz)
    const origin = new THREE.Vector3(glb.x, glb.y + 4000, glb.z)
    raycaster.set(origin, down)
    raycaster.far = 8000
    const hit = raycaster.intersectObject(terrain, false)[0] ?? null
    const xReversed: boolean | null =
      cp.id === 'P6' ? Math.abs(glb.x - (-cp.unity_mesh_local_xyz[0])) < 1e-6 : null
    results.push({
      id: cp.id,
      unity_world_xyz: cp.unity_world_xyz,
      converted_glb_xyz: [glb.x, glb.y, glb.z],
      expected_glb_xyz: cp.expected_glb_xyz,
      matrix_residual_m: glb.distanceTo(expected),
      hit_glb_xyz: hit ? [hit.point.x, hit.point.y, hit.point.z] : null,
      raycast_residual_m: hit ? glb.distanceTo(hit.point) : null,
      x_axis_reversed: xReversed,
    })
  }
  return results
}
select(id:string|null,focus=false){
  if(this.selectedBox){this.scene.remove(this.selectedBox);this.selectedBox.geometry.dispose();(this.selectedBox.material as THREE.Material).dispose();this.selectedBox=null}
  const object=this.objects.find(o=>o.object_id===id)??null
  if(object){const mesh=this.meshes.find(o=>o.name===object.glb_node_name)
   if(mesh&&object.object_id!=='terrain'){this.selectedBox=new THREE.BoxHelper(mesh,0x6affd2);this.scene.add(this.selectedBox)}
   if(focus){if(object.object_id==='terrain')this.frame('whole_terrain');else{
    const target=new THREE.Vector3(...object.focus_local_xyz_m),bounds=new THREE.Box3(new THREE.Vector3(...object.bounds_local_xyz_m[0]),new THREE.Vector3(...object.bounds_local_xyz_m[1]))
    const length=Math.max(bounds.getSize(new THREE.Vector3()).length()*1.8,180)*Math.max(1,1/this.camera.aspect)
    this.camera.position.copy(target.clone().add(new THREE.Vector3(1,0.7,1).normalize().multiplyScalar(length)));this.controls.target.copy(target);this.controls.update()
   }}
  }
  this.callback.selected(object);this.requestRender()
 }
 setReferenceMarkers(markers:ReferenceMarker[]){
  this.disposeReferenceMarkers()
  if(!markers.length||!this.profile?.capabilities.reference_markers)return
  this.referenceMarkers=new THREE.Group();this.referenceMarkers.name='reference-markers'
  const color=0x6affd2
  for(const m of markers){
   const [x,y,z]=m.local_xyz_m
   const sphere=new THREE.Mesh(new THREE.SphereGeometry(22,16,16),new THREE.MeshBasicMaterial({color}))
   sphere.position.set(x,y,z);this.referenceMarkers.add(sphere)
   const lineGeo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x,m.surface_y_m,z),new THREE.Vector3(x,y,z)])
   const line=new THREE.Line(lineGeo,new THREE.LineBasicMaterial({color,transparent:true,opacity:0.6}))
   this.referenceMarkers.add(line)
  }
  this.scene.add(this.referenceMarkers);this.requestRender()
 }
 private disposeReferenceMarkers(){
  if(this.referenceMarkers){
   this.referenceMarkers.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.Line){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose()}})
   this.scene.remove(this.referenceMarkers);this.referenceMarkers=null
  }
 }
 /** 实际三角面高度采样：按地形网格真实索引/三角面做重心插值，而非角点双线性。
  * 采样失败或超出地形范围返回 null，绝不静默用 y=0 代替。 */
 private sampleTerrainHeight(x:number,z:number):number|null{
  const mesh=this.terrainMesh
  if(!mesh)return null
  const pos=mesh.geometry.getAttribute('position') as THREE.BufferAttribute
  const positions=pos.array as ArrayLike<number>
  const indices=mesh.geometry.index?mesh.geometry.index.array as ArrayLike<number>:null
  return sampleHeightOnTerrain(x,z,positions,indices)
 }
 /** 沿地形采样的闭合轮廓（线环）。任一点采样失败则整环返回 null，交由上层提示。 */
 private buildFireOutline(ring:FireRing,offset:number,color:THREE.Color):THREE.Line|null{
  const pts=ring.ring_xz,points:THREE.Vector3[]=[]
  const MAX_SEG=25
  for(let i=0;i<pts.length-1;i++){
   const [x1,z1]=pts[i]!,[x2,z2]=pts[i+1]!
   const steps=Math.max(1,Math.ceil(Math.hypot(x2-x1,z2-z1)/MAX_SEG))
   for(let s=0;s<steps;s++){
    const t=s/steps,x=x1+(x2-x1)*t,z=z1+(z2-z1)*t
    const y=this.sampleTerrainHeight(x,z)
    if(y===null)return null
    points.push(new THREE.Vector3(x,y+offset,z))
   }
  }
  const [fx,fz]=pts[0]!,fy=this.sampleTerrainHeight(fx,fz)
  if(fy===null)return null
  points.push(new THREE.Vector3(fx,fy+offset,fz))
  const geo=new THREE.BufferGeometry().setFromPoints(points)
  return new THREE.Line(geo,new THREE.LineBasicMaterial({color,transparent:true,opacity:0.95}))
 }
 /** 贴地火区覆盖层：闭合轮廓沿实际地形三角面采样（本轮停用不准确的质心透明填充）。
   * 绝不改写原几何/根变换；清空/替换/失败均安排重绘，成功或清空后清除失效的 overlayIssue。 */
 setFirePatches(patches:ActiveFirePatch[]){
  if(this.disposed)return
  if(!this.profile?.capabilities.fire_patch_overlay){this.pendingFirePatches=null;return}
  if(!this.terrainMesh){this.pendingFirePatches=patches.length?patches:null;return}
  this.pendingFirePatches=null
  this.disposeFireOverlay()
  this.requestRender() // 场景内容已变（覆盖层被移除），立即重绘
  if(patches.length===0){this.callback.overlayIssue?.(null);return}
  const group=new THREE.Group();group.name='fire-overlay'
  const issues:string[]=[]
  for(const p of patches){
   const color=fireColor(p.level,p.intensity)
   for(const ring of p.rings){
    const line=this.buildFireOutline(ring,ring.ground_offset_m??0.5,color)
    if(line)group.add(line);else issues.push(`patch ${p.patch_id} 轮廓采样失败或超出地形范围`)
   }
  }
  if(group.children.length===0){
   this.callback.overlayIssue?.(issues.length?issues.join('；'):'火区覆盖层无可显示轮廓')
   return
  }
  this.fireOverlay=group
  this.scene.add(this.fireOverlay)
  this.callback.overlayIssue?.(issues.length?issues.join('；'):null)
  this.requestRender()
 }
 private disposeFireOverlay(){
  if(this.fireOverlay){
   this.fireOverlay.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.Line){o.geometry.dispose();const m=o.material;if(Array.isArray(m))m.forEach(x=>x.dispose());else m.dispose()}})
   this.scene.remove(this.fireOverlay);this.fireOverlay=null
  }
 }
 dispose(){
  if(this.disposed)return;this.disposed=true;this.abort.abort();cancelAnimationFrame(this.rafId)
  this.resizeObserver.disconnect();this.controls.removeEventListener('change',this.requestRender);this.controls.dispose()
  this.renderer.domElement.removeEventListener('pointerdown',this.onPointerDown);this.renderer.domElement.removeEventListener('pointerup',this.onPointerUp)
  if(this.selectedBox){this.selectedBox.geometry.dispose();(this.selectedBox.material as THREE.Material).dispose()}
  if(this.root)releaseModel(this.root)
  this.disposeFireOverlay();this.disposeReferenceMarkers();this.terrainMesh=null;this.pendingFirePatches=null
  this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();this.meshes=[];this.objects=[];this.root=null;this.profile=null
 }
}
