"""Package unchanged v4 asset with explicit coordinates, object IDs and evidence."""
from pathlib import Path
import json, shutil, hashlib, struct, csv
import numpy as np
import trimesh
from shapely.geometry import shape, mapping, box
from shapely.ops import transform
from shapely.geometry.polygon import orient
from pyproj import Transformer

ROOT=Path(__file__).resolve().parent; PARENT=ROOT.parent
(ROOT/'assets').mkdir(exist_ok=True);(ROOT/'reference').mkdir(exist_ok=True)
def write(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
source=PARENT/'coal_roof_draft/FireX_织金拱顶候选_v4.glb'
model=ROOT/'assets/zhijin_scene_v4.glb';shutil.copyfile(source,model)
shutil.copyfile(PARENT/'coal_roof_draft/v4_厂区预览.png',ROOT/'assets/scene_preview.png')
for name,path in {
    'coordinate_metadata.json':PARENT/'pilot/metadata.json',
    'landmark_parameters.json':PARENT/'landmark_draft/landmark_parameters.json',
    'roof_parameters.json':PARENT/'coal_roof_draft/roof_parameters.json',
    'platform_parameters.json':PARENT/'platform_draft/platform_parameters.json',
}.items():shutil.copyfile(path,ROOT/'reference'/name)
meta=json.loads((ROOT/'reference/coordinate_metadata.json').read_text())
anchor=np.array(meta['anchor_utm_easting_northing_m']);vertical_origin=meta['vertical_origin_m']
to_ll=Transformer.from_crs(32648,4326,always_xy=True)
to_utm=Transformer.from_crs(4326,32648,always_xy=True)
scene=trimesh.load(model,force='scene')
binary=model.read_bytes();header=struct.unpack_from('<III',binary)
assert header==(0x46546C67,2,len(binary))
chunk_length,kind=struct.unpack_from('<II',binary,12);assert kind==0x4E4F534A
gltf=json.loads(binary[20:20+chunk_length])
nodes={n['name']:(i,n['mesh']) for i,n in enumerate(gltf['nodes']) if 'mesh' in n}
assert len(nodes)==38 and len(nodes)==len([n for n in gltf['nodes'] if 'mesh' in n])
assert all(not b.get('uri') for b in gltf.get('buffers',[]))
assert all(not i.get('uri') for i in gltf.get('images',[]))
sources=json.loads((PARENT/'identity_check/facility_identity_candidates_utm48n.geojson').read_text())
building_features={f['properties']['draft_id']:f for f in sources['features']}
ground=json.loads((PARENT/'platform_draft/platform_checks.json').read_text())
grounding={a['facility_id']:a for a in ground['facilities']}
refs=json.loads((PARENT/'footprint_check/zhijin_osm_reference_wgs84.geojson').read_text())
boundary=next(f for f in refs['features'] if f['properties']['role']=='plant_boundary')
plant_poly=shape(boundary['geometry']);marker=plant_poly.representative_point()
marker_e,marker_n=to_utm.transform(marker.x,marker.y)
scene_id='zhijin_pilot'; plant_key='fx_chnenergy_zhijin_babu_pilot'

objects=[]
for name,(node_index,mesh_index) in nodes.items():
    mesh=scene.geometry[name];bounds=mesh.bounds;centre=bounds.mean(axis=0)
    object_id='terrain' if name=='geometry_0' else name
    record={'object_id':object_id,'scene_id':scene_id,'glb_node_name':name,
            'glb_node_index_in_v4':node_index,'glb_mesh_index_in_v4':mesh_index,
            'display_name':object_id,'category':'unknown_facility_candidate',
            'bounds_local_xyz_m':bounds.tolist(),'focus_local_xyz_m':centre.tolist(),
            'triangle_count':len(mesh.faces),'identity_status':'unassigned',
            'position_status':'source-reference coordinates; not independently registered to current imagery',
            'fire_risk_level':None}
    if name=='geometry_0':
        record.update(category='terrain',display_name='周边基础地形与估计厂区平台',
            identity_status='terrain_display_layer',position_status='camera anchor CRS assumed; pending registration',
            height_status='historical mixed-source elevation with synthetic platform edits',
            colour_status='高程和估计平台显示色；不代表真实植被、卫星影像或风险',
            max_synthetic_height_edit_m=ground['max_height_edit_m'])
    else:
        record.update(platform_id=grounding[name]['platform_id'],
            base_elevation_estimate_m=float(bounds[0,1]+vertical_origin),
            base_status='estimated support-platform elevation, not measured',
            display_height_m=float(bounds[1,1]-bounds[0,1]))
        if name in building_features:
            p=building_features[name]['properties']
            record.update(source={'dataset':'GBA Part II','source':p['source'],'id':p['id'],'region':p['region']},
                original_GBA_height_prediction_m=p['height'],
                height_status='dataset prediction; not measured',
                footprint_status='GBA candidate outline, not verified site boundary',
                identity_status=p['identity_evidence_status'],identity_hypothesis=p['identity_hypothesis'])
            if p['identity_hypothesis']!='未分配':record['display_name']=name+' '+p['identity_hypothesis']
            if name=='B01':record.update(category='arched_shed_candidate',
                height_status='30m apex display assumption; original7.30m prediction retained separately',
                shape_status='parabolic proxy clipped to unverified irregular footprint; interior not modelled')
        elif name=='CH01':
            record.update(category='chimney',display_name='烟囱参考模型',identity_status='OSM landmark reference',
                height_status='240m documented in plant report, not newly surveyed',
                height_source_url='https://sthj.guizhou.gov.cn/zwgk/zdlyxx/fsjg/fslxmspqgs/202406/P020241015404863681069.pdf',
                height_source_pdf_page=30,shape_status='outer radii and taper display assumptions',
                source={'dataset':'OSM','osm_type':'node','osm_id':12160650736})
        else:
            record.update(category='cooling_tower',display_name=name+' 冷却塔参考模型',
                identity_status='OSM landmark reference',height_status='150m display assumption, not verified',
                shape_status='shell profile, wall thickness and supports display assumptions',
                source={'dataset':'OSM','osm_type':'way','osm_id':588594543 if name=='CT-A' else 588594544})
        lon,lat=to_ll.transform(anchor[0]+centre[0],anchor[1]-centre[2])
        record['horizontal_bbox_centre_lon_lat_reference']=[lon,lat]
        record['horizontal_centre_status']='geometric bounding-box centre, not an official facility marker'
    objects.append(record)
objects.sort(key=lambda r:r['object_id'])
write('object_registry.json',{'scene_id':scene_id,'asset_version':'v4','objects':objects,
    'id_policy':'IDs refer to this snapshot; preserve them on updates, do not regenerate by area sorting',
    'node_index_policy':'indices bind only to this asset hash; exported node names verified unique for this file',
    'selection_note':'a rendered hit node name maps to object_id; selecting a candidate does not confirm its facility identity'})

point={'type':'Feature','id':plant_key,'geometry':{'type':'Point','coordinates':[marker.x,marker.y]},
    'properties':{'project_plant_key':plant_key,'external_plant_id':None,
        'name':'国能织金发电有限公司','province_code':'520000','province_name':'贵州省',
        'locality_hint':'织金县八步街道；与金元织金项目区分',
        'scene_id':scene_id,'scene_manifest':'scene_manifest.json','scene_ready':True,
        'scene_status':'draft','browser_loading_verified':False,
        'point_method':'representative interior point of OSM plant boundary, not official surveyed plant centre',
        'coordinate_accuracy':'derived_reference_unverified','source_url':boundary['properties']['source_url'],
        'source_osm_id':560730385,'source_notice':'OSM社区轮廓，未与当前影像独立核验',
        'fire_monitoring_status':'not_connected','current_alert_level':None,'is_fire_alert_mock':False}}
write('map_scene_link.geojson',{'type':'FeatureCollection','features':[point],
    'coordinate_reference':'RFC7946 longitude, latitude in WGS84; 2D only',
    'notice':'one provisional linkage example, not a validated national plant dataset; source actor ID match pending'})

roi=box(anchor[0]-2000,anchor[1]-2000,anchor[0]+2000,anchor[1]+2000)
# Densify projected edges before reprojecting the boundary.
roi=roi.segmentize(250)
roi_ll=orient(transform(to_ll.transform,roi),sign=1)
write('scene_extent.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','id':'zhijin_pilot_roi',
    'properties':{'scene_id':scene_id,'area_km2':16,'extent_status':'4x4km pilot mesh, not plant boundary or final study area'},
    'geometry':mapping(roi_ll)}]})
platforms=json.loads((PARENT/'platform_draft/estimated_support_platforms_utm48n.geojson').read_text())
platforms.pop('crs',None)
platforms.pop('bbox',None)
platforms['coordinate_reference']='RFC7946 WGS84 longitude,latitude, 2D; transformed from EPSG:32648'
for f in platforms['features']:
    g=shape(f['geometry']);f['geometry']=mapping(orient(transform(to_ll.transform,g),sign=1))
    f['properties']['scene_id']=scene_id
write('estimated_platforms_wgs84.geojson',platforms)

facility_bounds=np.vstack([m.bounds for name,m in scene.geometry.items() if name!='geometry_0'])
focus=facility_bounds.mean(axis=0);focus[1]=390
manifest={
    'schema_version':'1.0','scene_id':scene_id,'asset_version':'v4','project_plant_key':plant_key,
    'display_name':'国能织金电厂与周边山地（试建场景）','status':'draft_with_unverified_geometry',
    'model_uri':'assets/zhijin_scene_v4.glb','preview_uri':'assets/scene_preview.png',
    'object_registry_uri':'object_registry.json','map_link_uri':'map_scene_link.geojson',
    'extent_uri':'scene_extent.geojson','estimated_platforms_uri':'estimated_platforms_wgs84.geojson',
    'asset':{'format':'GLB2','bytes':len(binary),'sha256':sha(model),'embedded_resources':True,
             'object_meshes':len(scene.geometry),'triangles':sum(len(m.faces) for m in scene.geometry.values()),
             'textures_present':bool(gltf.get('images'))},
    'coordinates':{'unit':'metre','handedness':'right','x_positive':'east','y_positive':'up','z_positive':'south',
        'projected_reference':'EPSG:32648, WGS84 UTM zone48N',
        'anchor_projected_easting_northing_m':anchor.tolist(),
        'anchor_lon_lat_assumed_WGS84':meta['anchor_camera_lon_lat'],
        'anchor_status':'camera-photo coordinate, not plant centre; source CRS assumed pending verification',
        'vertical_origin_m':vertical_origin,'source_vertical_datum':'not verified for the mixed terrain source',
        'conversion_forward':['x=E-anchor_E','y=h-1000','z=anchor_N-N'],
        'conversion_inverse':['E=anchor_E+x','N=anchor_N-z','h=1000+y'],
        'height_warning':'h is the model/source elevation estimate, not verified ellipsoidal height or AGL',
        'root_transform_policy':'keep asset translation[0,0,0],rotation identity,scale[1,1,1] in the local viewer; adjust camera for framing',
        'earth_globe_status':'not ECEF/georeferenced glTF; an explicit adapter is required for globe placement'},
    'camera_presets':{
        'whole_terrain':{'position_local_xyz_m':[4700,3400,4700],'target_local_xyz_m':[0,360,0],
            'vertical_fov_degrees':45,'near_m':1,'far_m':20000},
        'plant':{'position_local_xyz_m':(focus+[1300,1000,1300]).tolist(),
            'target_local_xyz_m':focus.tolist(),'vertical_fov_degrees':45,'near_m':1,'far_m':20000},
        'status':'initial settings for later viewer testing; fit bounds to actual viewport aspect ratio'},
    'ui_labels':{'scene_badge':'试建场景','unassigned_object_label':'设施候选，身份未核实',
        'unconnected_fire_status':'尚未接入火情','terrain_colour_legend':'高程示意色，非植被或火险'},
    'readiness':{'render_asset_available':True,'asset_byte_copy_verified':True,
        'browser_loading_verified':False,'device_performance_verified':False,
        'external_map_plant_id_bound':False,'real_world_accuracy_verified':False,
        'fire_simulation_connected':False,'collision_geometry_verified':False},
    'limitations':['34个建筑候选不是34栋已验证建筑，可能拆分、合并或遗漏',
        'B01拱顶最高30m与冷却塔150m是展示假设；烟囱240m为报告记载',
        '平台和基础高程是粗地形派生估计，最大人工地形改动约37.27m',
        '地形颜色不是卫星贴图、植被类别或火灾风险',
        '开放钢架为独立未定位组件，未包含在这个厂区GLB',
        'anchor camera CRS, terrain lineage/epoch/vertical datum and current registration not validated'],
    'sources_and_attribution':[
        {'name':'GBA PartII','url':'https://github.com/zhu-xlab/GlobalBuildingAtlas',
         'paper':'https://essd.copernicus.org/articles/17/6647/2025/','licence':'CC BY-NC4.0 for corresponding dataset'},
        {'name':'OSM reference','url':'https://www.openstreetmap.org/way/560730385',
         'attribution':'© OpenStreetMap contributors','licence':'ODbL'},
        {'name':'Mapzen Terrain Tiles','url':meta['source_url'],'sha256':meta['source_sha256'],
         'notice':meta['attribution'],'lineage':'specific cell lineage and datum unverified'},
        {'name':'plant report','url':'https://sthj.guizhou.gov.cn/zwgk/zdlyxx/fsjg/fslxmspqgs/202406/P020241015404863681069.pdf','date':'2024-06'},
        {'name':'official photo','url':'https://www.chnenergy.com.cn/gjnyjtww/chnjtyw/202106/44a7beb5674b486987d17440d6eadbb9.shtml','publication':'2021-06-28'},
    ]}
write('scene_manifest.json',manifest)

# Coordinate examples are synthetic arithmetic checks, not surveyed scene points.
examples=[]
for xyz in [[0,313,0],[100,350,-200],[-2000,400,2000],[2000,500,-2000]]:
    x,y,z=xyz;E=anchor[0]+x;N=anchor[1]-z;h=vertical_origin+y
    lon,lat=to_ll.transform(E,N);E2,N2=to_utm.transform(lon,lat)
    roundtrip=np.array([E2-anchor[0],h-vertical_origin,anchor[1]-N2])
    examples.append({'kind':'synthetic_coordinate_example','local_xyz_m':xyz,
        'projected_E_N_h_m':[E,N,h],'lon_lat_reference':[lon,lat],
        'roundtrip_arithmetic_error_m':float(np.max(np.abs(roundtrip-xyz)))})
write('coordinate_examples.json',examples)
assert sha(source)==sha(model)
assert {r['glb_node_name'] for r in objects}==set(nodes)
assert len({r['object_id'] for r in objects})==38
assert len(platforms['features'])==14
assert 'crs' not in platforms
for f in platforms['features']:
    bounds=shape(f['geometry']).bounds
    assert 105<bounds[0]<bounds[2]<107 and 25<bounds[1]<bounds[3]<28
assert plant_poly.covers(marker)
assert max(r['roundtrip_arithmetic_error_m'] for r in examples)<1e-6
assert all((ROOT/manifest[k]).is_file() for k in ['model_uri','preview_uri','object_registry_uri','map_link_uri','extent_uri','estimated_platforms_uri'])
write('handoff_checks.json',{'model_bytes_unchanged':True,'unique_object_ids':38,
    'node_links_resolved':38,'estimated_platform_features':14,'map_point_inside_source_OSM_boundary':True,
    'all_relative_manifest_uris_exist':True,'embedded_resources':True,
    'coordinate_arithmetic_roundtrip_max_error_m':max(r['roundtrip_arithmetic_error_m'] for r in examples),
    'status':'file and metadata checks passed; no browser/engine or real-world accuracy verification'})
rows=[{'object_id':r['object_id'],'display_name':r['display_name'],'glb_node_name':r['glb_node_name'],
       'category':r['category'],'display_height_m':r.get('display_height_m'),
       'height_status':r['height_status'],'base_estimate_m':r.get('base_elevation_estimate_m'),
       'identity_status':r['identity_status']} for r in objects]
with (ROOT/'对象清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print(json.dumps({'model_bytes':len(binary),'objects':len(objects),'triangles':manifest['asset']['triangles'],
    'map_reference_point_lon_lat':point['geometry']['coordinates'],
    'scene_id':scene_id,'model_unchanged':True},ensure_ascii=False))
