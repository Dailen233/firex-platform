# C1：小样本离线二维火焰检测

用已有环境（`/home/dailen/vggt/vggt-env`）与自训练权重（`best.pt`，单类 `fire`）对小样本做离线二维检测，验证「已有权重的离线二维检测基线」及实际检测表现。

## 范围与约束

- 仅加载本地明确指定的权重；不联网、不下载、不安装/升级依赖；不调用旧 `inference.load_model`。
- 不做三角化、火区轮廓、双江口配准、后端算法提供者接入；不写 run/state；不用 fixture 轮廓代替检测。
- 不读取真值选框/调参；`samples.json` 的 `expected_label` 仅用于结果复核，不参与推理。
- 小样本基线，不宣称 mAP / 泛化误报率 / 山火适用性 / 动态重建；未检出 ≠ 火灾熄灭。

## 运行（仓库根）

```bash
# 真实检测（CPU / imgsz=640 / conf=0.25 / iou=0.45）
/home/dailen/vggt/vggt-env/bin/python experiments/c1-detection/run_detection.py

# 针对性回归（受控替身 + monkeypatch，不跑真实模型推理）
/home/dailen/vggt/vggt-env/bin/python experiments/c1-detection/test_run_detection.py
```

固定参数：`device=cpu, imgsz=640, conf=0.25, iou=0.45`。

## 严格校验（校验失败 = 真实失败）

- 首次 `predict` 前强制核对本地权重 SHA256 与清单一致，并核对 task、规范化类别映射。**权重哈希不符 → 不加载模型、不调用 predict；task/names 不符 → 已加载模型（用于读取 task/names）但不调用 predict**。两种情况均非零退出，不下载或切换模型。
- 每图必须通过：输入哈希、`orig_shape` 与原图尺寸一致、框及置信度有限、置信度 ∈ [0,1]、框正面积且在界、类别 ID 可解析、叠加图写回后尺寸与原图一致。
- 任一失败 → 该图 `status=error`，整体退出码非零；合法零检测仍为 `ok`（空列表，不算失败）。
- JSON 以 `allow_nan=False` 写出，不写 NaN/Infinity；校验错误不转成「未检出」。

## 样本清单（`samples.json`）

- 正样本：case01 frame_0021 / frame_0022（C0 已核验火焰清晰可见，SHA256 与 C0 配对索引一致）。
- 不确定样本：case05 frame_0001 / frame_0012（case05 notes 标注无火但有烟/高亮背景；因当前会话模型不支持图像查看，**未逐帧目视核验，标「不确定」**，不当作无火真值）。

## 结果判定口径（不称「已确认误报」）

- case05 frame_0001 → **未检出**。
- case05 frame_0012 → **检出 fire，真值待核**（原图含烟与橙黄亮点/条状粒子，缺乏确认无火的依据，不当作已确认误报）。

## 输出（`runtime-data/c1-final/`，已 gitignore）

- `summary.json` / `run_meta.json` / `samples.json`（复制）
- 每图 `<id>.json`（路径/哈希/宽高、模型哈希、类别映射、参数与版本、原始框、火焰框、锚点、耗时、状态）
- 每图 `<id>.overlay.png`（原图尺寸框叠加）
