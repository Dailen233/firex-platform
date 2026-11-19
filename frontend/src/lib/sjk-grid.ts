// Local simulation corridor. It is deliberately independent of the public
// outgoing-line record, which has no verified geographic route or tower table.
import type { SceneObject, SceneProfile } from './types'

type XYZ = [number, number, number]
type Site = { id: string; x: number; z: number; heightM: number }
export type GridSupport = Site & { y: number; sideX: number; sideZ: number }
export type Tower = GridSupport & { feet: XYZ[] }
export type GridSpan = { circuit: 1 | 2; phase: number; xyz: XYZ[] }
export interface GridSummary {
  towers: number
  spans: number
  lengthM: number
}
export interface GridCorridor {
  supports: Tower[]
  conductors: GridSpan[]
  summary: GridSummary
}

export const SJK_CORRIDOR_SCENE_ID = 'sjk_hydropower_sim_v0_1'
export const SJK_CORRIDOR_TERRAIN = 'team_fbx_terrain_129'
export function supportsSjkCorridor(profile: SceneProfile): boolean {
  return profile.scene_id === SJK_CORRIDOR_SCENE_ID
    && profile.asset_version === 'hydro-sim-v0.1-local'
    && profile.coordinate_frame_id === 'SJK_TEAM_FBX_FILE_METRE_UNREGISTERED_v1'
    && profile.asset.sha256 === '722b8514a17715f3c109b1cbaa8259dc958c8f212af71cd1c0ae75608566fb91'
}

// Entirely local X/Z, in metres. The first support is the simulated outgoing
// gantry on the existing substation terrace; the last tower ends the study
// segment and is not a model of the distant receiving substation.
const sites: Site[] = [
  {id:'S0',x:-138,z:8,heightM:36},
  {id:'D01',x:-435,z:-6,heightM:56},
  {id:'D02',x:-730,z:-35,heightM:56},
  {id:'D03',x:-1035,z:-65,heightM:56},
  {id:'D04',x:-1340,z:-94,heightM:56},
  {id:'D05',x:-1680,z:-162,heightM:56},
  {id:'D06',x:-1985,z:-342,heightM:56},
  {id:'D07',x:-2180,z:-625,heightM:56},
  {id:'D08',x:-2360,z:-915,heightM:56},
  {id:'D09',x:-2545,z:-1235,heightM:56},
  {id:'D10',x:-2765,z:-1560,heightM:56},
  {id:'D11',x:-2980,z:-1880,heightM:56},
  {id:'D12',x:-3200,z:-2210,heightM:56},
  {id:'D13',x:-3420,z:-2495,heightM:56},
]

export function conductorAttachment(support: GridSupport, circuit: 1 | 2, phase: number): XYZ {
  const side = (circuit === 1 ? -1 : 1) * (12 - 1.5 * phase)
  return [
    support.x + support.sideX * side,
    support.y + support.heightM - 3 - 6 * phase,
    support.z + support.sideZ * side,
  ]
}

export function buildSjkCorridor(
  profile: SceneProfile,
  objects: readonly SceneObject[],
  terrainY: (x: number, z: number) => number | null,
): GridCorridor {
  if (!supportsSjkCorridor(profile)) throw new Error('仿真走廊与当前模型版本不匹配。')
  const terrace = objects.find(o => o.object_id === 'grid_terrace')
  const yard = objects.find(o => o.object_id === 'transformer_yard')
  if (!terrace || !yard) throw new Error('缺少模拟升压区或出线区，无法定位站端门架。')

  const supports = sites.map((site, i): Tower => {
    let y = terrainY(site.x, site.z)
    if (y === null || !Number.isFinite(y)) throw new Error(`仿真支点 ${site.id} 无法落到地形上。`)
    if (i === 0) {
      const [lo, hi] = yard.bounds_local_xyz_m
      const terraceY = terrace.bounds_local_xyz_m[1][1]
      if (site.x < lo[0] || site.x > hi[0] || site.z < lo[2] || site.z > hi[2]
          || !Number.isFinite(terraceY) || terraceY < y) {
        throw new Error('站端门架与模拟台地不一致。')
      }
      y = terraceY
    }
    const before = sites[Math.max(0, i - 1)]!
    const after = sites[Math.min(sites.length - 1, i + 1)]!
    const dx = after.x - before.x, dz = after.z - before.z
    const length = Math.hypot(dx, dz)
    const sideX = -dz / length, sideZ = dx / length
    const footprint = i === 0 ? [[-13.5,0],[13.5,0]] : [[-5,-5],[-5,5],[5,5],[5,-5]]
    const feet = footprint.map(([u,v]): XYZ => {
      const x = site.x + u! * sideX - v! * sideZ
      const z = site.z + u! * sideZ + v! * sideX
      const footY = i === 0 ? y : terrainY(x,z)
      if (footY === null || !Number.isFinite(footY)) throw new Error(`仿真支点 ${site.id} 的塔脚无法落到地形上。`)
      return [x, footY, z]
    })
    return {...site, y, sideX, sideZ, feet}
  })

  let lengthM = 0
  const conductors: GridSpan[] = []
  for (let i = 1; i < supports.length; i++) {
    const start = supports[i - 1]!, end = supports[i]!
    const distance = Math.hypot(start.x - end.x, start.z - end.z)
    lengthM += distance
    // Visual sag only; this is not a conductor, load, or clearance calculation.
    const sag = Math.min(distance * 0.022, 10)
    const steps = Math.ceil(distance / 6)
    for (const circuit of [1, 2] as const) {
      for (let phase = 0; phase < 3; phase++) {
        const a = conductorAttachment(start, circuit, phase)
        const b = conductorAttachment(end, circuit, phase)
        const xyz: XYZ[] = []
        for (let j = 0; j <= steps; j++) {
          const t = j / steps
          xyz.push([
            a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t - 4 * sag * t * (1 - t),
            a[2] + (b[2] - a[2]) * t,
          ])
        }
        conductors.push({circuit, phase, xyz})
      }
    }
  }
  return {supports, conductors, summary:{towers:supports.length - 1, spans:supports.length - 1, lengthM}}
}
