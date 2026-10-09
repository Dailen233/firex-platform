import * as THREE from 'three'

interface Face {points:Float32Array;fill:string}
interface ProjectedFace {xy:number[];depth:number;fill:string}
/** Compatibility display only: projects real GLB vertices to Canvas2D.
 * Terrain uses a coarser grid of the original vertices; facility meshes are retained.
 * This is not a substitute for WebGL, geometry accuracy or GPU performance acceptance.
 */
export class SoftwareRenderer {
 readonly domElement=document.createElement('canvas')
 private context=this.domElement.getContext('2d')!
 private width=1;private height=1;private faces:Face[]=[];private model:THREE.Object3D|null=null
 outputColorSpace=THREE.SRGBColorSpace;toneMapping=THREE.NoToneMapping;toneMappingExposure=1
 setPixelRatio(_value:number){}
 setClearColor(_value:string){}
 setSize(width:number,height:number,_updateStyle:boolean){this.width=Math.round(width);this.height=Math.round(height);this.domElement.width=this.width;this.domElement.height=this.height}
 private prepare(root:THREE.Object3D){
  this.model=root;this.faces=[];root.updateMatrixWorld(true)
  const sun=new THREE.Vector3(.4,.8,.3).normalize()
  root.traverse(o=>{
   if(!(o instanceof THREE.Mesh))return
   const position=o.geometry.getAttribute('position'),colour=o.geometry.getAttribute('color'),index=o.geometry.index
   const material=(Array.isArray(o.material)?o.material[0]:o.material) as THREE.MeshStandardMaterial
   const baseColour=material.color??new THREE.Color('#b8c1cc')
   const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3(),normal=new THREE.Vector3(),edge=new THREE.Vector3()
   const pushFace=(i:number,j:number,k:number)=>{
    a.fromBufferAttribute(position,i).applyMatrix4(o.matrixWorld);b.fromBufferAttribute(position,j).applyMatrix4(o.matrixWorld);c.fromBufferAttribute(position,k).applyMatrix4(o.matrixWorld)
    normal.subVectors(b,a).cross(edge.subVectors(c,a)).normalize()
    const shade=.68+.32*Math.abs(normal.dot(sun)),co=new THREE.Color()
    if(colour)co.setRGB((colour.getX(i)+colour.getX(j)+colour.getX(k))/3,(colour.getY(i)+colour.getY(j)+colour.getY(k))/3,(colour.getZ(i)+colour.getZ(j)+colour.getZ(k))/3).multiply(baseColour)
    else co.copy(baseColour)
    co.multiplyScalar(shade)
    this.faces.push({points:new Float32Array([...a.toArray(),...b.toArray(),...c.toArray()]),fill:co.getStyle()})
   }
   // v4 terrain is a documented 401×401 regular height grid. Never assume this for a future asset.
   if(o.name==='geometry_0'&&position.count===160801){
    const step=6,n=401
    for(let z=0;z<n-1;z+=step)for(let x=0;x<n-1;x+=step){const x2=Math.min(x+step,n-1),z2=Math.min(z+step,n-1);pushFace(z*n+x,z*n+x2,z2*n+x);pushFace(z*n+x2,z2*n+x2,z2*n+x)}
   }else if(index){for(let i=0;i<index.count;i+=3)pushFace(index.getX(i),index.getX(i+1),index.getX(i+2))}
   else for(let i=0;i<position.count;i+=3)pushFace(i,i+1,i+2)
  })
 }
 render(scene:THREE.Scene,camera:THREE.PerspectiveCamera){
  const root=scene.children.find(o=>o instanceof THREE.Group)
  if(root&&root!==this.model)this.prepare(root)
  camera.updateMatrixWorld();const matrix=new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse)
  const v=new THREE.Vector3(),projected:ProjectedFace[]=[]
  for(const face of this.faces){
   const xy:number[]=[],zs:number[]=[];let behind=false
   for(let i=0;i<9;i+=3){v.set(face.points[i]!,face.points[i+1]!,face.points[i+2]!).applyMatrix4(matrix);if(v.z>1||v.z< -1)behind=true;xy.push((v.x+1)*this.width/2,(1-v.y)*this.height/2);zs.push(v.z)}
   if(behind||xy.every((a,i)=>i%2===1||a<0)||xy.every((a,i)=>i%2===1||a>this.width)||xy.every((a,i)=>i%2===0||a<0)||xy.every((a,i)=>i%2===0||a>this.height))continue
   projected.push({xy,depth:(zs[0]!+zs[1]!+zs[2]!)/3,fill:face.fill})
  }
  projected.sort((a,b)=>b.depth-a.depth)
  const context=this.context;context.fillStyle='#0c1927';context.fillRect(0,0,this.width,this.height)
  for(const f of projected){context.beginPath();context.moveTo(f.xy[0]!,f.xy[1]!);context.lineTo(f.xy[2]!,f.xy[3]!);context.lineTo(f.xy[4]!,f.xy[5]!);context.closePath();context.fillStyle=f.fill;context.fill()}
  // Selected-object frame, using the BoxHelper that already follows the original model coordinates.
  for(const o of scene.children){if(!(o instanceof THREE.BoxHelper))continue;const pos=o.geometry.getAttribute('position'),index=o.geometry.index;if(!index)continue
   context.strokeStyle='#6affd2';context.lineWidth=1.5;context.beginPath()
   for(let i=0;i<index.count;i+=2){v.fromBufferAttribute(pos,index.getX(i)).applyMatrix4(matrix);context.moveTo((v.x+1)*this.width/2,(1-v.y)*this.height/2);v.fromBufferAttribute(pos,index.getX(i+1)).applyMatrix4(matrix);context.lineTo((v.x+1)*this.width/2,(1-v.y)*this.height/2)}context.stroke()
  }
 }
 dispose(){this.faces=[];this.model=null;this.domElement.width=1;this.domElement.height=1}
 forceContextLoss(){}
}
