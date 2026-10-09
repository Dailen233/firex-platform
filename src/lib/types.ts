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
  [key: string]: unknown;
}
export interface Plant { type: 'Feature'; properties: PlantProperties; geometry: {type:'Point';coordinates:[number,number]} }
export interface BoundaryFeature {type:'Feature';properties:{name:string;code?:string;gb?:string};geometry:{type:string;coordinates: unknown}}
export interface Boundaries {type:'FeatureCollection';features:BoundaryFeature[]}
export interface SceneLink {plant_id:string;scene_id:string;asset_version:string;manifest_uri:string}
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
