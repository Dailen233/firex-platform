# 前端适配说明

原始队友ZIP和模型完整保留；这是项目整合副本，不覆盖原始交付。

- related_province_codes：分号字符串转换为数组。
- 无场景的scene_id：空字符串转换为null；不生成额外模型。
- 织金：地图GEM_COAL_ZHIJIN映射到已有zhijin_pilot/v4；原ZHIJIN_16KM2_TRIAL保留source_scene_id。
- 项目自定义ID与GEM原生ID明确区分，后续全量数据需要映射。
- 未接入火情：current_alert_level=null、fire_monitoring_status=not_connected；原模拟告警独立保存。
- 织金OpenInfraMap首页移入community_map_url，官方照片链接仅作为厂区参考。
- 向家坝采用官方报道总装机6400 MW，保留GEM7750 MW差异，原因待核查。
- 模型根变换、GLB字节和原manifest未修改；适配映射以scene_index.json为准，原manifest中的external_map_plant_id_bound=false仍是原交接时状态。
- 底图尚无几何，省份代码与CRS处理规范写入province_boundary_requirements.json。

URI说明：scene_index中的manifest_uri和电厂数据scene_manifest相对于交接包部署根目录；scene_manifest.json内部资源路径相对于manifest地址。

本次没有构建前端、浏览器运行、模拟火区或巡检识别；这些属于新工作对话的首轮开发和后续专题。
