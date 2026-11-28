import * as THREE from 'three'

// 厂区近景预览层：在现有仿真台地上叠加一套「参考公开资料的仿真布局」，
// 用程序化几何表现 GIS 开关楼、地面副厂房、两栋低矮辅助用房，以及场坪、
// 挡墙和道路。坐标沿用原 GLB 局部米制（X 东 / Y 上 / Z 南），不修改原模型。
//
// 台面标高（来自 scene_objects.json 的台地 bounds 顶面）：
//   plant_terrace（发电厂房台地）y ≈ 59.8
//   grid_terrace （升压区台地）  y ≈ 74.8
const PLANT_Y = 59.8
const GRID_Y = 74.8

type XYZ = [number, number, number]

export function makePlantPreviewLayer() {
  const group = new THREE.Group()
  group.name = 'sjk-plant-preview-layout'

  const mat = (color: number, opts: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
    new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.05, ...opts })

  const yardMat = mat(0x9aa4ab, { roughness: 0.95 })
  const roadMat = mat(0x6e7a82, { roughness: 0.95 })
  const wallMat = mat(0xb8c4cc, { roughness: 0.9 })
  const buildingMat = mat(0x7f96a3)
  const roofMat = mat(0x5d7382)
  const auxMat = mat(0xc9b98a)
  const gisMat = mat(0xa8b6c0, { metalness: 0.65, roughness: 0.35 })
  const bushingMat = mat(0xd8e0e6, { metalness: 0.2, roughness: 0.5 })
  const windowMat = mat(0x416275, { roughness: 0.45, metalness: 0.15 })

  const box = (w: number, h: number, d: number, m: THREE.Material, x: number, y: number, z: number) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m)
    mesh.position.set(x, y, z)
    group.add(mesh)
    return mesh
  }

  // 场坪：铺在发电厂房台地上（略高于台面，避免与地形 z-fighting）。
  box(240, 0.4, 172, yardMat, 245, PLANT_Y + 0.2, 141)

  // 南北主路：贯穿台地中部，连接辅助用房与副厂房（北端停在挡墙内侧，避免穿插）。
  box(16, 0.3, 172, roadMat, 248, PLANT_Y + 0.35, 142)

  // 地面副厂房（道路东侧，贴地，带屋顶与天窗，有辨识度）。
  box(80, 17.6, 42, buildingMat, 296, PLANT_Y + 8.8, 152)
  box(80, 1.6, 42, roofMat, 296, PLANT_Y + 18.4, 152)
  for (let i = -1; i <= 1; i++) box(10, 2.4, 6, roofMat, 296 + i * 26, PLANT_Y + 20.4, 152)

  // 两栋低矮辅助用房（道路西侧，一北一南）。
  box(22, 8, 18, auxMat, 222, PLANT_Y + 4, 95)
  box(22, 8, 18, auxMat, 222, PLANT_Y + 4, 132)

  // 挡墙：台地北缘（z 较小一侧）的矮墙。
  box(180, 4.4, 2, wallMat, 245, PLANT_Y + 2.2, 52.5)

  // 候选厂房模型：仅用于表达厂区密度与厂房群体效果，不代表真实设计或已核设施。
  const factory = (x: number, z: number, w: number, d: number, h: number) => {
    box(w, h, d, buildingMat, x, PLANT_Y + h / 2, z)
    box(w + 3, 1.8, d + 3, roofMat, x, PLANT_Y + h + 0.9, z)
    for (let i = -1; i <= 1; i++) {
      box(Math.min(12, w * 0.16), 2.2, 0.5, windowMat, x + i * w * 0.28, PLANT_Y + h * 0.58, z + d / 2 + 0.26)
    }
  }
  factory(352, 205, 62, 36, 16)
  factory(418, 188, 48, 30, 13)
  factory(388, 238, 52, 34, 15)
  factory(454, 230, 56, 38, 17)
  box(96, 0.35, 18, roadMat, 406, PLANT_Y + 0.45, 218)

  // GIS 开关楼：放在升压区台地西半（原主变被隐藏后空出的位置）。
  box(72, 21.2, 56, gisMat, -93, GRID_Y + 10.6, 27)
  for (let i = 0; i < 6; i++) {
    const x = -120 + i * 12
    const z = i % 2 === 0 ? 10 : 44
    const c = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 8, 8), bushingMat)
    c.position.set(x, GRID_Y + 25.2, z)
    group.add(c)
  }

  const bounds = new THREE.Box3()
  const boundsPoints: XYZ[] = [
    [125, PLANT_Y, 52], [475, PLANT_Y, 238],
    [-129, GRID_Y, -1], [-57, GRID_Y, 55],
    [125, PLANT_Y + 21, 52], [475, PLANT_Y + 21, 238],
    [-129, GRID_Y + 30, -1], [-57, GRID_Y + 30, 55],
  ]
  for (const b of boundsPoints) bounds.expandByPoint(new THREE.Vector3(...b))

  return {
    group,
    bounds,
    dispose() {
      for (const child of group.children) {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose()
          const m = child.material
          if (Array.isArray(m)) m.forEach((x) => x.dispose())
          else m.dispose()
        }
      }
    },
  }
}
