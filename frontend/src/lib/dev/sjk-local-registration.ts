// E3.1 本地落点核验（仅开发态）。
// 数据来源：~/下载/FireX_SJK_Local_Registration_20261107.zip 内 sjk_local_registration_v1.json。
// unity_world_to_glb 为嵌套行主序，列向量左乘：p_glb = M @ [x, y, z, 1]^T。
// 该矩阵含 X 轴反射（线性部分 diag(-1,+1,+1)，行列式 -1），仅用于本模型与已核验
// 静态地形实例的对齐，不用于旋转四元数或相机姿态。

export const TERRAIN_MESH_NAME = 'team_fbx_terrain_129'

export const UNITY_WORLD_TO_GLB: number[][] = [
  [-1.0, -0.0, -0.0, 22278.353515625],
  [0.0, 1.0, 0.0, 0.0],
  [0.0, 0.0, 1.0, -8561.326171875],
  [0.0, 0.0, 0.0, 1.0],
]

export interface RegistrationControlPoint {
  id: 'P5' | 'P6'
  /** Unity 世界坐标（取证 JSON 的 unity_world_xyz_raw_units）。 */
  unity_world_xyz: [number, number, number]
  /** Unity 网格局部坐标（用于 X 轴反向判别）。 */
  unity_mesh_local_xyz: [number, number, number]
  /** JSON 声明的 GLB 局部坐标真值（glb_local_xyz_m）。 */
  expected_glb_xyz: [number, number, number]
}

export const CONTROL_POINTS: RegistrationControlPoint[] = [
  {
    id: 'P5',
    unity_world_xyz: [22278.353515625, 34.89508819580078, 8561.326171875],
    unity_mesh_local_xyz: [0.0, 34.89508819580078, 0.0],
    expected_glb_xyz: [0.0, 34.89508819580078, 0.0],
  },
  {
    id: 'P6',
    unity_world_xyz: [19778.353515625, 644.41162109375, 11061.326171875],
    unity_mesh_local_xyz: [-2500.0, 644.41162109375, 2500.0],
    expected_glb_xyz: [2500.0, 644.41162109375, 2500.0],
  },
]

export interface LocalRegistrationPointResult {
  id: string
  unity_world_xyz: [number, number, number]
  /** 按 unity_world_to_glb 计算的 GLB 局部坐标。 */
  converted_glb_xyz: [number, number, number]
  /** JSON 声明的 GLB 真值（glb_local_xyz_m）。 */
  expected_glb_xyz: [number, number, number]
  /** 转换结果与 JSON 真值的三维差（应≈0）。 */
  matrix_residual_m: number
  /** 只对地形网格垂直射线命中的点；未命中为 null。 */
  hit_glb_xyz: [number, number, number] | null
  /** 转换点与射线命中点的三维差（应≈0）。 */
  raycast_residual_m: number | null
  /** 仅 P6 判别 X 轴反向（glb_x = -mesh_local_x = +2500）；P5 中心 X=0 不可判别，为 null。 */
  x_axis_reversed: boolean | null
}
