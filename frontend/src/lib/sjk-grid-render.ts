import * as THREE from 'three'
import { conductorAttachment, type GridCorridor } from './sjk-grid'
import type { GridSupport } from './sjk-grid'

type XYZ = [number, number, number]
type Segment = [XYZ, XYZ]

/** Batched steel members and two separately colored conductor sets.
 *  导线节点已由 sjk-grid 使用视效抬升量单独抬高，不改变塔脚或地形坐标。 */
export function makeSjkGridLayer(corridor: GridCorridor) {
  const group = new THREE.Group()
  group.name = 'sjk-simulated-grid-corridor'
  const steel: Segment[] = []
  for (const s of corridor.supports) {
    if (s.id === 'S0') {
      const [left,right] = s.feet as [XYZ,XYZ]
      const topLeft: XYZ = [left[0],s.y+s.heightM,left[2]]
      const topRight: XYZ = [right[0],s.y+s.heightM,right[2]]
      steel.push([left,topLeft],[right,topRight],[topLeft,topRight])
      for (let phase = 0; phase < 3; phase++) {
        const y = conductorAttachment(s,1,phase)[1]
        steel.push([[left[0],y,left[2]],[right[0],y,right[2]]])
      }
      continue
    }
    const section = (t: number, radius: number): XYZ[] =>
      [[-1,-1],[-1,1],[1,1],[1,-1]].map(([u,v]) => [
        s.x + radius * (u! * s.sideX - v! * s.sideZ),
        s.y + s.heightM * t,
        s.z + radius * (u! * s.sideZ + v! * s.sideX),
      ])
    const bands = [s.feet,section(0.48,2.7),section(0.78,1.8),section(1,1.25)]
    for (let j = 1; j < bands.length; j++) {
      const lo = bands[j - 1]!, hi = bands[j]!
      for (let i = 0; i < 4; i++) {
        const next = (i + 1) % 4
        steel.push([lo[i]!,hi[i]!],[hi[i]!,hi[next]!],[lo[i]!,hi[next]!],[lo[next]!,hi[i]!])
      }
    }
    for (let phase = 0; phase < 3; phase++) {
      const a = conductorAttachment(s,1,phase), b = conductorAttachment(s,2,phase)
      steel.push([a,b],[[s.x, a[1]+4, s.z], a],[[s.x,b[1]+4,s.z],b])
    }
  }
  const geometry = new THREE.CylinderGeometry(0.43,0.43,1,5)
  const memberMaterial = new THREE.MeshBasicMaterial({color:0xa6c0cc})
  const members = new THREE.InstancedMesh(geometry,memberMaterial,steel.length)
  const matrix = new THREE.Matrix4(), rotation = new THREE.Quaternion()
  const a = new THREE.Vector3(), b = new THREE.Vector3(), delta = new THREE.Vector3(), dir = new THREE.Vector3()
  const position = new THREE.Vector3(), scale = new THREE.Vector3(), up = new THREE.Vector3(0,1,0)
  steel.forEach(([p,q],i) => {
    a.set(...p);b.set(...q);delta.subVectors(b,a)
    rotation.setFromUnitVectors(up,dir.copy(delta).normalize())
    matrix.compose(position.addVectors(a,b).multiplyScalar(0.5),rotation,scale.set(1,delta.length(),1))
    members.setMatrixAt(i,matrix)
  })
  members.computeBoundingBox()
  members.computeBoundingSphere()
  group.add(members)

  for (const [circuit,color] of [[1,0x55efdc],[2,0xa2ddff]] as const) {
    const positions: number[] = []
    for (const span of corridor.conductors) {
      if (span.circuit !== circuit) continue
      for (let i = 1; i < span.xyz.length; i++) positions.push(...span.xyz[i - 1]!, ...span.xyz[i]!)
    }
    const wires = new THREE.BufferGeometry()
    wires.setAttribute('position',new THREE.Float32BufferAttribute(positions,3))
    group.add(new THREE.LineSegments(wires,new THREE.LineBasicMaterial({color,toneMapped:false})))
  }

  const boxFor = (supports: GridSupport[]) => {
    const box = new THREE.Box3()
    for (const s of supports) {
      box.expandByPoint(new THREE.Vector3(s.x-24,s.y-10,s.z-24))
      box.expandByPoint(new THREE.Vector3(s.x+24,s.y+s.heightM+15,s.z+24))
    }
    return box
  }
  return {
    group,
    summary: corridor.summary,
    bounds: boxFor(corridor.supports),
    stationBounds: boxFor(corridor.supports.slice(0,3)),
    dispose() {
      for (const child of group.children) {
        if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments) {
          child.geometry.dispose()
          child.material.dispose()
        }
        if (child instanceof THREE.InstancedMesh) child.dispose()
      }
    },
  }
}
