import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { ActiveFirePatch, FireLevel, SceneManifest, SceneObject } from './types'
import { readJson,resolveResource } from './data'
import { pointInRingXZ } from './fire-demo-schema'
import { SoftwareRenderer } from './software-renderer'

export interface ViewerCallbacks {progress:(percent:number,message:string)=>void;loaded:(manifest:SceneManifest,objects:SceneObject[])=>void;selected:(object:SceneObject|null)=>void;mode:(mode:'webgl'|'software')=>void}
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
 private frame=0;private disposed=false;private root:THREE.Group|null=null;private objects:SceneObject[]=[]
 private meshes:THREE.Mesh[]=[];private selectedBox:THREE.BoxHelper|null=null;private manifest:SceneManifest|null=null
 private fireOverlay:THREE.Group|null=null;private terrainMesh:THREE.Mesh|null=null;private pendingFirePatches:ActiveFirePatch[]|null=null
 private pointerStart={x:0,y:0};private pointer=new THREE.Vector2();private raycaster=new THREE.Raycaster()
 constructor(private host:HTMLElement,private callback:ViewerCallbacks){
  // A disabled cloud GPU must remain visible as a limitation, not a false GLB failure.
  const probe=document.createElement('canvas').getContext('webgl2')
  if(probe){probe.getExtension('WEBGL_lose_context')?.loseContext();try{this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});callback.mode('webgl')}catch{this.renderer=new SoftwareRenderer();callback.mode('software')}}
  else{this.renderer=new SoftwareRenderer();callback.mode('software')}
  this.renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.5));this.renderer.setClearColor('#0c1927')
  this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.15
  this.renderer.domElement.setAttribute('aria-label','织金三维模型：拖动旋转、滚轮缩放；设施列表支持键盘选择')
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
 private requestRender=()=>{if(!this.disposed&&!this.frame)this.frame=requestAnimationFrame(this.render)}
 private render=()=>{this.frame=0;if(this.disposed)return;this.controls.update();this.renderer.render(this.scene,this.camera)}
 private onPointerDown=(event:PointerEvent)=>{this.pointerStart={x:event.clientX,y:event.clientY}}
 private onPointerUp=(event:PointerEvent)=>{
  if(this.disposed||event.button!==0||Math.hypot(event.clientX-this.pointerStart.x,event.clientY-this.pointerStart.y)>5)return
  const rect=this.renderer.domElement.getBoundingClientRect();this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1)
  this.raycaster.setFromCamera(this.pointer,this.camera)
  const hit=this.raycaster.intersectObjects(this.meshes,false)[0]
  if(!hit){this.select(null);return}
  // Name mapping is valid only after this asset's SHA and unique nodes are checked.
  const record=this.objects.find(o=>o.glb_node_name===hit.object.name)
  this.select(record?.object_id??null)
 }
 async load(manifestUrl:string){
  const signal=this.abort.signal
  this.callback.progress(0,'读取场景配置与对象表')
  const manifest=await readJson<SceneManifest>(manifestUrl,signal)
  if(manifest.scene_id!=='zhijin_pilot'||manifest.asset_version!=='v4')throw new Error('场景编号或模型版本不匹配')
  const registry=await readJson<{objects:SceneObject[]}>(resolveResource(manifest.object_registry_uri,manifestUrl),signal)
  this.callback.progress(5,'下载织金 v4 模型')
  const response=await fetch(resolveResource(manifest.model_uri,manifestUrl),{signal:AbortSignal.any([signal,AbortSignal.timeout(45000)])})
  if(!response.ok)throw new Error(`模型读取失败（HTTP ${response.status}）`)
  const parts:Uint8Array[]=[];let size=0
  if(response.body){const reader=response.body.getReader();while(true){const part=await reader.read();if(part.done)break;parts.push(part.value);size+=part.value.length;this.callback.progress(5+Math.min(75,size/manifest.asset.bytes*75),'下载织金 v4 模型')}}
  else{const bytes=new Uint8Array(await response.arrayBuffer());parts.push(bytes);size=bytes.length}
  const buffer=new Uint8Array(size);let offset=0;for(const part of parts){buffer.set(part,offset);offset+=part.length}
  if(size!==manifest.asset.bytes)throw new Error('模型文件大小与交接记录不一致')
  // crypto.subtle is available on HTTPS and localhost. Byte/node checks still apply on plain HTTP LAN previews.
  if(globalThis.crypto?.subtle){
   const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))).map(b=>b.toString(16).padStart(2,'0')).join('')
   if(hash!==manifest.asset.sha256)throw new Error('模型文件哈希与交接记录不一致')
  }
  if(this.disposed)return
  this.callback.progress(85,'解析几何并核对对象')
  const gltf=await new GLTFLoader().parseAsync(buffer.buffer,new URL('.',manifestUrl).href)
  if(this.disposed){releaseModel(gltf.scene);return}
  this.root=gltf.scene;this.objects=registry.objects;this.manifest=manifest
  this.root.traverse(o=>{if(o instanceof THREE.Mesh)this.meshes.push(o)})
  this.terrainMesh=this.meshes.find(o=>o.name==='geometry_0')??null
  const names=this.meshes.map(o=>o.name)
  if(this.meshes.length!==manifest.asset.object_meshes||new Set(names).size!==names.length||registry.objects.length!==38||registry.objects.some(o=>!names.includes(o.glb_node_name)))throw new Error('对象表与 GLB 节点未能完整对应')
  // Preserve the handed-off local coordinate frame. Fit the camera, never the model.
  if(!this.root.position.equals(new THREE.Vector3())||!this.root.scale.equals(new THREE.Vector3(1,1,1))||!this.root.quaternion.equals(new THREE.Quaternion()))throw new Error('模型根变换不符合局部坐标约定')
  this.scene.add(this.root);this.framePreset('plant')
  this.callback.progress(100,'模型已加载');this.callback.loaded(manifest,registry.objects)
  if(this.pendingFirePatches){const p=this.pendingFirePatches;this.pendingFirePatches=null;this.setFirePatches(p)}
  this.requestRender()
 }
 framePreset(kind:'plant'|'whole_terrain'){
  if(!this.manifest)return
  const p=this.manifest.camera_presets[kind],target=new THREE.Vector3(...p.target_local_xyz_m)
  this.camera.fov=p.vertical_fov_degrees;this.camera.near=p.near_m;this.camera.far=p.far_m
  let position=new THREE.Vector3(...p.position_local_xyz_m)
  // Adapt preset to the viewport's limiting FOV, including a narrow portrait canvas.
  const ratio=Math.max(1,1/this.camera.aspect)
  position=target.clone().add(position.sub(target).multiplyScalar(ratio))
  this.camera.position.copy(position);this.controls.target.copy(target);this.camera.updateProjectionMatrix();this.controls.update();this.requestRender()
 }
 select(id:string|null,focus=false){
  if(this.selectedBox){this.scene.remove(this.selectedBox);this.selectedBox.geometry.dispose();(this.selectedBox.material as THREE.Material).dispose();this.selectedBox=null}
  const object=this.objects.find(o=>o.object_id===id)??null
  if(object){const mesh=this.meshes.find(o=>o.name===object.glb_node_name)
   if(mesh&&object.object_id!=='terrain'){this.selectedBox=new THREE.BoxHelper(mesh,0x6affd2);this.scene.add(this.selectedBox)}
   if(focus){if(object.object_id==='terrain')this.framePreset('whole_terrain');else{
    const target=new THREE.Vector3(...object.focus_local_xyz_m),bounds=new THREE.Box3(new THREE.Vector3(...object.bounds_local_xyz_m[0]),new THREE.Vector3(...object.bounds_local_xyz_m[1]))
    const length=Math.max(bounds.getSize(new THREE.Vector3()).length()*1.8,180)*Math.max(1,1/this.camera.aspect)
    this.camera.position.copy(target.clone().add(new THREE.Vector3(1,0.7,1).normalize().multiplyScalar(length)));this.controls.target.copy(target);this.controls.update()
   }}
  }
  this.callback.selected(object);this.requestRender()
 }
 /** 贴地火区覆盖层：复用 geometry_0 原三角网格（401×401，顶点序 z*401+x），
  * 以三角质心是否落入火区环判定纳入，绝不改写原几何/根变换。 */
 setFirePatches(patches:ActiveFirePatch[]){
  if(this.disposed)return
  if(!this.terrainMesh){this.pendingFirePatches=patches.length?patches:null;return}
  this.pendingFirePatches=null;this.disposeFireOverlay()
  if(patches.length===0)return
  const pos=this.terrainMesh.geometry.getAttribute('position') as THREE.BufferAttribute
  if(pos.count!==160801)return // 仅支持交接的 v4 地形网格；未来资产不假设
  const n=401
  const targets=patches.flatMap(p=>p.rings.map(ring=>{
   let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity
   for(const [x,z] of ring.ring_xz){if(x<minX)minX=x;if(x>maxX)maxX=x;if(z<minZ)minZ=z;if(z>maxZ)maxZ=z}
   return {pts:ring.ring_xz,offset:ring.ground_offset_m??0.5,color:fireColor(p.level,p.intensity),minX,maxX,minZ,maxZ}
  }))
  const included=new Map<string,{i0:number;i1:number;i2:number;offset:number;color:THREE.Color}>()
  const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3()
  const addTri=(i0:number,i1:number,i2:number)=>{
   a.fromBufferAttribute(pos,i0);b.fromBufferAttribute(pos,i1);c.fromBufferAttribute(pos,i2)
   const cx=(a.x+b.x+c.x)/3,cz=(a.z+b.z+c.z)/3
   for(const t of targets){
    if(cx<t.minX||cx>t.maxX||cz<t.minZ||cz>t.maxZ)continue
    if(pointInRingXZ(cx,cz,t.pts)){
     const key=[i0,i1,i2].sort((p,q)=>p-q).join(',')
     if(!included.has(key))included.set(key,{i0,i1,i2,offset:t.offset,color:t.color})
     return
    }
   }
  }
  for(let z=0;z<n-1;z++)for(let x=0;x<n-1;x++){
   const x2=x+1,z2=z+1
   const i00=z*n+x,i10=z*n+x2,i01=z2*n+x,i11=z2*n+x2
   addTri(i00,i10,i01);addTri(i10,i11,i01)
  }
  if(included.size===0)return
  const positions=new Float32Array(included.size*9),colors=new Float32Array(included.size*9)
  let w=0
  for(const t of included.values()){
   for(const vi of [t.i0,t.i1,t.i2]){
    positions[w*3]=pos.getX(vi);positions[w*3+1]=pos.getY(vi)+t.offset;positions[w*3+2]=pos.getZ(vi)
    colors[w*3]=t.color.r;colors[w*3+1]=t.color.g;colors[w*3+2]=t.color.b;w++
   }
  }
  const geo=new THREE.BufferGeometry()
  geo.setAttribute('position',new THREE.BufferAttribute(positions,3))
  geo.setAttribute('color',new THREE.BufferAttribute(colors,3))
  geo.computeBoundingBox();geo.computeBoundingSphere()
  const mat=new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:0.55,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1,side:THREE.DoubleSide})
  const mesh=new THREE.Mesh(geo,mat);mesh.renderOrder=10
  this.fireOverlay=new THREE.Group();this.fireOverlay.name='fire-demo-overlay';this.fireOverlay.add(mesh)
  this.scene.add(this.fireOverlay);this.requestRender()
 }
 private disposeFireOverlay(){
  if(this.fireOverlay){
   this.fireOverlay.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose()}})
   this.scene.remove(this.fireOverlay);this.fireOverlay=null
  }
 }
 dispose(){
  if(this.disposed)return;this.disposed=true;this.abort.abort();cancelAnimationFrame(this.frame)
  this.resizeObserver.disconnect();this.controls.removeEventListener('change',this.requestRender);this.controls.dispose()
  this.renderer.domElement.removeEventListener('pointerdown',this.onPointerDown);this.renderer.domElement.removeEventListener('pointerup',this.onPointerUp)
  if(this.selectedBox){this.selectedBox.geometry.dispose();(this.selectedBox.material as THREE.Material).dispose()}
  if(this.root)releaseModel(this.root)
  this.disposeFireOverlay();this.terrainMesh=null;this.pendingFirePatches=null
  this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();this.meshes=[];this.objects=[];this.root=null
 }
}
