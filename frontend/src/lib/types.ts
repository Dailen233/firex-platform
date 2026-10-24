export interface ResearchAreaMarker {
  id: string;
  label: string;
  lon: number;
  lat: number;
  verification_status: string;
  source: string;
  source_url: string;
  note: string;
}
export interface PlantProperties {
  plant_id: string; name: string; aliases: string; source_province: string;
  display_province: string; province_code: string; related_province_codes: string[];
  technology: string; operating_status: string; capacity_mw: number | null;
  capacity_scope: string; coordinate_crs: string; coordinate_accuracy: string;
  source_id: string; source_version: string; source_url: string;
  official_case_source?: string; capacity_source_url?: string; community_map_url?: string;
  official_case_source_scope?: string; scene_id: string | null; scene_ready: boolean;
  fire_monitoring_status: string; current_alert_level: string | null;
  capacity_source_conflict?: { gem_value_mw: number; official_value_mw: number; status: string; note: string };
  research_area_scope_note?: string;
  research_area_markers?: ResearchAreaMarker[];
  [key: string]: unknown;
}
export interface Plant { type: 'Feature'; properties: PlantProperties; geometry: {type:'Point';coordinates:[number,number]} }
export interface BoundaryFeature {type:'Feature';properties:{name:string;code?:string;gb?:string};geometry:{type:string;coordinates: unknown}}
export interface Boundaries {type:'FeatureCollection';features:BoundaryFeature[]}
export type SceneAssetRole = 'formal_model' | 'public_reference_terrain'
export interface SceneLink {plant_id:string;scene_id:string;asset_version:string;asset_role:SceneAssetRole;formal_model_ready:boolean;display_name:string;profile_uri:string}
export interface CameraPreset {position_local_xyz_m: [number,number,number];target_local_xyz_m:[number,number,number];vertical_fov_degrees:number;near_m:number;far_m:number}
export interface SceneManifest {
  scene_id:string;asset_version:string;display_name:string;model_uri:string;object_registry_uri:string;
  preview_uri:string;asset:{bytes:number;sha256:string;object_meshes:number;triangles:number;textures_present:boolean};
  camera_presets:{whole_terrain:CameraPreset;plant:CameraPreset};
  sources_and_attribution: {name:string;url:string;licence?:string;attribution?:string;notice?:string}[];
  limitations:string[];
}
export interface SceneObject {
  object_id:string;glb_node_name:string;display_name:string;identity_status:string;height_status?:string;
  display_height_m?:number;original_GBA_height_prediction_m?:number;category:string;position_status:string;
  focus_local_xyz_m:[number,number,number];bounds_local_xyz_m:[[number,number,number],[number,number,number]];
  base_status?:string;shape_status?:string;fire_risk_level:string|null;
}

// ---- Unified frontend scene profile (config decoupling) ----
export interface SceneProfileCamera { position: [number, number, number]; target: [number, number, number] }
export interface SceneProfile {
  scene_id: string;
  plant_id: string;
  asset_version: string;
  asset_role: SceneAssetRole;
  formal_model_ready: boolean;
  display_name: string;
  scene_badge: string;
  coordinate_frame_id: string | null;
  model_uri: string;
  object_registry_uri: string | null;
  object_registry_required: boolean;
  overlay_markers_uri: string | null;
  terrain_mesh_name: string | null;
  terrain_grid: { nx: number; nz: number } | null;
  asset: {
    bytes: number;
    sha256: string;
    object_meshes: number | null;
    triangles: number | null;
    vertex_count: number | null;
    mesh_count: number | null;
    textures_present: boolean;
  };
  bounds_local_m: { min: [number, number, number]; max: [number, number, number] } | null;
  cameras: {
    vertical_fov_degrees: number;
    default: SceneProfileCamera;
    plant: SceneProfileCamera | null;
    whole_terrain: SceneProfileCamera | null;
    panorama: { strategy: 'fit_world_bounding_box'; padding_factor: number };
  };
  camera_limits: { near: number; far: number; min_distance: number; max_distance: number };
  capabilities: {
    object_selection: boolean;
    reference_markers: boolean;
    fire_patch_overlay: boolean;
  };
  ui_notice: string | null;
  study_area_note: string | null;
  study_area_stat: string | null;
  coordinate_note: string | null;
  sources_and_attribution: { name: string; url?: string; licence?: string; attribution?: string; notice?: string }[];
  limitations: string[];
}
export interface ReferenceMarker {
  marker_id: string;
  label: string;
  scene_id: string;
  asset_version: string;
  coordinate_frame_id: string;
  lon_lat_wgs84: [number, number];
  local_xyz_m: [number, number, number];
  surface_y_m: number;
  display_offset_m: number;
  height_source: string;
  source_url: string;
  usage: string;
  is_mock: boolean;
  mock_scope: string;
}

// ---- Fire demo (R2) contract — synthetic demo only, not real/algo fire prediction ----
export type FireLevel = 'watch' | 'warning' | 'critical'
export interface FireRing {
  /** 局部 XZ 闭合环（X 东、Z 南，米），首版无孔洞、无自交；Y 由 viewer 贴地采样 */
  ring_xz: [number, number][];
  /** 地面之上显示偏移（米），取值 [0,1]，缺省 0.5；仅用于避免覆盖层与地形显示重叠，不代表火焰高度，不改变数据高度 */
  ground_offset_m?: number;
}
export interface FireKeyframe {
  /** 关键帧时刻（秒），0..duration_s，升序且不重复；关键帧间保持上一关键帧取值（无插值） */
  t_s: number;
  active: boolean;
  intensity?: number; // 0..1，仅视觉；缺省沿用上一关键帧
  level?: FireLevel;  // 演示告警等级；缺省沿用上一关键帧
}
export interface FirePatch {
  patch_id: string; // 稳定、唯一，不按面积/排序重建
  plant_id: string;
  scene_id: string;
  rings: FireRing[];
  keyframes: FireKeyframe[]; // 空数组 => 永不显示（合法）
  is_mock: true;
}
export interface FireStateDemo {
  schema: 'Fire-X fire_state demo';
  schema_version: '1.0';
  is_mock: true;
  demo_origin: 'synthetic_demo_rule';
  plant_id: string;
  scene_id: string;
  duration_s: number; // >0，非循环
  patches: FirePatch[];
  rules: { spread_note: string; disclaimer: string };
}
export type DemoStatus = 'off' | 'playing' | 'paused' | 'ended'
export interface DemoRuntimeState { status: DemoStatus; t_s: number }
export interface FireViewState extends DemoRuntimeState { activePatchIds: string[] }
export interface ResolvedPatchState { patch_id: string; active: boolean; intensity: number; level: FireLevel }
export interface ActiveFirePatch { patch_id: string; level: FireLevel; intensity: number; rings: FireRing[] }
