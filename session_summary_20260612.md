# Session Summary — 2026-06-12

## 目标

在上一版流水线基础上，解决两个核心问题：
1. 多件衣服同框（选帧错误导致三件叠在一起进入输出）
2. GPT-4o 颜色识别偏深（深蓝被识别为黑色）

---

## 探索路径

### 方案A — alpha 连通块分析（否决）
rembg 输出的 alpha 通道做连通块分析，多块判定为多件。
**否决原因**：衣服叠在一起时 alpha 不断开，看到的仍是一整块，检测不到。

### 方案B — YOLO 多框检测（尝试后放弃）
对候选帧检测 YOLO 框数，2 个以上高置信框且 IoU 低 → 丢弃该帧。
**失效原因**：三件叠在一起时 YOLO 只返回 1 个框（只检测到最突出的那件），多框条件永远不触发。

### 谷值检测改用 YOLO mask 直方图（尝试后回退）
把全帧直方图改为 YOLO seg 掩码内像素的直方图，目的是让帧差曲线对深色系更敏感。
**结果**：输出无明显改善，耗时从 1.4s 涨到 5.1s，已回退。

### 最终方案 — GPT prompt 改造（有效）
不在上游解决多件问题，而是在 GPT-4o 描述阶段明确指示"只描述最前景的那件"。
gpt-image-1 拿到单件描述，自然只生成一件。核心思路：问题在输出端，就在输出端解决。

---

## 今天的代码改动

### 1. 计时功能（visual_pipeline.py）
`run_pipeline` 每步加 `time.time()` 计时，最后打印 `--- Timing ---` 表格。

基准耗时（改动前）：
```
extract_frames         1.5s
filter_blurry          1.2s
find_stable_frames     1.4s
crop_and_rembg         6.6s
total                  10.8s
```

### 2. 接入 GPT flatten（visual_pipeline.py）
`run_pipeline` 末尾新增 GPT 步骤：
- 对每个 representative 再跑一次 `get_crop_and_class` 取 crop
- 调用 `flatten_with_gpt(src, flat_dst)` 生成 `item_XX_flat.png`
- `output_paths` 返回 flat 图路径

GPT 步骤耗时约 85~110s（4件串行，每件约 20~25s）。

### 3. GPT-4o prompt 改造（visual_pipeline.py:193）

**改动1 — 多件过滤**：
> "There may be multiple clothing items visible in this image. Focus ONLY on the single most prominent foreground item — ignore anything partially visible behind or beside it."

**改动2 — 结构特征提示**：
> "Pay special attention to structural features: hood presence, collar type, pocket style and position, zipper placement and color, sleeve style, cuff design, waistband and hem."

**改动3 — 颜色精度提示**：
> "be precise — distinguish navy blue from black, teal from blue, etc."

### 4. Gamma 校正（visual_pipeline.py:flatten_with_gpt）
白底合成之后、base64 编码之前，对发送给 GPT 的图做 gamma=0.75 校正：
```python
lut = np.array([((i / 255.0) ** 0.75) * 255 for i in range(256)], dtype=np.uint8)
img_cv = cv2.LUT(img_cv, lut)
```
**原因**：衣橱拍摄环境偏暗，相机欠曝，GPT-4o 把深蓝读成黑色。gamma 校正拉亮暗部，不影响高光。只作用于发给 GPT 的图，rembg PNG 输出不受影响。

---

## 输出对比（同一视频，4件）

| 件 | 改前问题 | 改后效果 |
|----|---------|---------|
| item_01 | 衣架残留，颜色基本准 | 颜色准，结构基本对 |
| item_02 | 深蓝识别为黑色，无帽子 | 颜色改为深蓝，帽子出现 ✓ |
| item_03 | 三件同框，无帽子 | 正确隔离前景件，帽子出现 ✓ |
| item_04 | 蓝绿识别为深蓝 | 颜色改为 teal，黄色拉链保留 ✓ |

---

## 已知剩余问题

- **GPT 步骤慢**：4件串行约 85~110s，瓶颈在 gpt-image-1 生成。可改并发（asyncio / ThreadPoolExecutor），理论压到 ~25s。
- **选帧错误未根治**：item_03 原始抠图仍是三件叠在一起，只是 GPT 描述阶段绕过了问题。
- **衣架残留**：rembg 不区分衣架和衣服，部分图仍有衣架。

---

## 下一步

1. GPT 请求并发化（提速）
2. 验证 gamma=0.75 是否最优，或可尝试 0.7/0.8 对比
