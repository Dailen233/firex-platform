// 多视角重建回放：解析离线重建的 summary.json 与二进制体素 PLY，
// 体素坐标直接使用原 GLB 局部米制坐标，供三维页以 THREE.Points 叠加显示。

export interface MultiviewReplayGroup {
  group_id: string
  simulation_time_s: number
  source_camera_count: number
  candidate_voxel_count: number
  glb_sha256: string | null
  boundsMin: [number, number, number]
  boundsMax: [number, number, number]
}

export interface MultiviewReplaySummary {
  scene_id: string
  asset_version: string
  coordinate_frame_id: string
  voxel_size_m: number
  groups: MultiviewReplayGroup[]
}

export interface VoxelPly {
  vertex_count: number
  xyz: Float32Array
}

interface RawGroup {
  group_id?: string
  simulation_time_s?: number
  source_camera_count?: number
  candidate_voxel_count?: number
  terrain_clip?: { glb_sha256?: string }
  candidate_bounds_xyz_m?: [number[], number[]]
}

export function parseMultiviewSummary(text: string): MultiviewReplaySummary {
  let raw: Record<string, unknown>
  try {
    raw = JSON.parse(text) as Record<string, unknown>
  } catch {
    throw new Error('summary.json 不是有效 JSON。')
  }
  if (typeof raw.scene_id !== 'string' || !raw.scene_id) throw new Error('summary.json 缺少场景 ID。')
  if (typeof raw.asset_version !== 'string' || !raw.asset_version) throw new Error('summary.json 缺少资产版本。')
  if (typeof raw.coordinate_frame_id !== 'string' || !raw.coordinate_frame_id) throw new Error('summary.json 缺少坐标系 ID。')
  const rawGroups = raw.groups
  if (!Array.isArray(rawGroups) || rawGroups.length === 0) throw new Error('summary.json 缺少重建分组。')
  const groups: MultiviewReplayGroup[] = rawGroups.map((g) => {
    const group = g as RawGroup
    if (typeof group.group_id !== 'string' || !group.group_id) throw new Error('分组缺少 group_id。')
    if (typeof group.simulation_time_s !== 'number') throw new Error(`分组 ${group.group_id} 缺少 simulation_time_s。`)
    if (typeof group.source_camera_count !== 'number' || typeof group.candidate_voxel_count !== 'number') {
      throw new Error(`分组 ${group.group_id} 缺少重建机位数或候选体素数。`)
    }
    const b = group.candidate_bounds_xyz_m
    const hasBounds = Array.isArray(b) && Array.isArray(b[0]) && Array.isArray(b[1])
    return {
      group_id: group.group_id,
      simulation_time_s: group.simulation_time_s,
      source_camera_count: group.source_camera_count,
      candidate_voxel_count: group.candidate_voxel_count,
      glb_sha256: group.terrain_clip?.glb_sha256 ?? null,
      boundsMin: (hasBounds ? [b![0]![0], b![0]![1], b![0]![2]] : [0, 0, 0]) as [number, number, number],
      boundsMax: (hasBounds ? [b![1]![0], b![1]![1], b![1]![2]] : [0, 0, 0]) as [number, number, number],
    }
  }).sort((a, b) => a.simulation_time_s - b.simulation_time_s)
  return {
    scene_id: raw.scene_id,
    asset_version: raw.asset_version,
    coordinate_frame_id: raw.coordinate_frame_id,
    voxel_size_m: typeof raw.voxel_size_m === 'number' ? raw.voxel_size_m : 0,
    groups,
  }
}

// 二进制小端 PLY：element vertex + property float x/y/z（体素中心点）。
export function parseVoxelPly(buffer: ArrayBuffer): VoxelPly {
  const bytes = new Uint8Array(buffer)
  const headerText = new TextDecoder('ascii').decode(bytes.slice(0, 4096))
  const marker = headerText.indexOf('end_header')
  if (marker < 0) throw new Error('PLY 缺少 end_header。')
  const header = headerText.slice(0, marker)
  const vertexMatch = header.match(/element\s+vertex\s+(\d+)/)
  if (!vertexMatch) throw new Error('PLY 缺少 element vertex。')
  const count = Number(vertexMatch[1])
  const props = [...header.matchAll(/property\s+float\s+(\w+)/g)].map((m) => m[1])
  const xi = props.indexOf('x')
  const yi = props.indexOf('y')
  const zi = props.indexOf('z')
  if (xi < 0 || yi < 0 || zi < 0) throw new Error('PLY 顶点缺少 x/y/z 属性。')
  const stride = props.length
  let dataOffset = marker + 'end_header'.length
  while (dataOffset < bytes.length && (bytes[dataOffset] === 0x0a || bytes[dataOffset] === 0x0d)) dataOffset++
  if (dataOffset + count * stride * 4 > bytes.length) throw new Error('PLY 顶点数据长度不足。')
  const view = new DataView(buffer)
  const xyz = new Float32Array(count * 3)
  for (let i = 0; i < count; i++) {
    const base = dataOffset + i * stride * 4
    xyz[i * 3] = view.getFloat32(base + xi * 4, true)
    xyz[i * 3 + 1] = view.getFloat32(base + yi * 4, true)
    xyz[i * 3 + 2] = view.getFloat32(base + zi * 4, true)
  }
  return { vertex_count: count, xyz }
}

// 从 PLY 文件名提取 group_id（group_01-voxels.ply -> group_01）。
export function plyGroupId(fileName: string): string | null {
  const m = /^(group_\S+?)-voxels\.ply$/i.exec(fileName.trim())
  return m ? m[1]! : null
}
