# Session Summary — 2026-06-11

## 目标

从服装展示视频里自动提取每件衣服，抠图去背景，输出单件衣服的透明底 PNG，后续送给 GPT 做语义描述和生成产品图。

---

## 项目结构

```
stylo-backend/
├── visual_pipeline.py       # 核心流水线，所有图像处理逻辑
├── extract_clothing.py      # 今天新建的入口脚本，直接调用 run_pipeline
├── uploads/                 # 输入视频
└── visual_output/           # 输出目录，run_pipeline 每次运行前会清空重建
    ├── item_01.png
    ├── item_02.png
    ├── ...
    └── diff_curve.png       # 帧差曲线图，用于调试稳定帧检测
```

---

## 当前流水线（run_pipeline）

### 入口
```python
run_pipeline(video_path, output_dir=None) -> list[str]
```
返回每件衣服 crop 图的路径列表（PNG，透明底）。

### 流程步骤

#### 1. extract_frames
- 按 `FPS_SAMPLE=5` 从视频抽帧，保存为 JPEG 到 `frames/` 子目录

#### 2. filter_blurry_frames
- 用 Laplacian 方差计算每帧清晰度（`sharpness` 函数）
- 过滤掉最模糊的 25% 帧

#### 3. find_stable_frames
这是流水线最核心也最复杂的一步，分三个子阶段：

**子阶段 A — 谷值检测**
- 对所有帧计算 HSV 色彩直方图（全帧）
- 计算相邻帧的 Bhattacharyya 距离，得到帧差曲线
- 用滑动窗口平滑曲线，用 `find_peaks` 找差值最小的谷值点（"稳定时刻"）
- 过滤掉高于均值的谷值点，只保留真正稳定的帧
- 输出 `diff_curve.png` 供调试

**子阶段 B — YOLO 去重**
- 加载 `deepfashion2_yolov8s-seg.pt`（fashion 专用 YOLOv8 分割模型）
- 对候选帧两两比较：用 YOLO 裁出置信度最高的服装框（`get_crop_and_class`），拿到 seg 分割掩码，只对掩码内像素算色彩直方图
- 直方图差值 < 0.10 认为是同一件衣服，合并掉
- **关键改动**：今天把直方图比较从全图改为只用 YOLO seg 掩码内的像素，排除背景噪声，对深色系区分更准确

**子阶段 C — 插入最清晰早帧**
- 取前10帧中 Laplacian 方差最高的帧
- 如果它不在 representatives 里，强制插到结果列表开头
- 目的：保证视频开头的衣服不会被遗漏

**清理**
- 删除 frames 目录里所有不在 representatives 中的文件（包括 `_crop.jpg` 临时文件）

#### 4. get_crop_and_class（模块级函数）
- 对每个 representative 运行 YOLO
- 取置信度最高的检测框，裁出服装区域
- 同时提取 seg 分割掩码（供直方图比较用）
- 返回 `(cls, crop_path, seg_mask)`

#### 5. rembg 去背景
- 对 crop 图用 rembg 去背景
- 输出带透明通道的 PNG 到 `visual_output/item_XX.png`

#### 6. GPT flatten（已注释掉）
- `flatten_with_gpt` 函数存在但被注释，不调用任何 LLM API
- 原本的逻辑：rembg 去背景 → base64 编码 → GPT-4o 生成语义描述 → gpt-image-1 生成产品图

---

## 今天的代码改动清单

| 改动 | 位置 | 说明 |
|------|------|------|
| `get_crop_and_class` 提升为模块级函数 | visual_pipeline.py:76 | 原来是 `find_stable_frames` 的内部函数，现在可在 `run_pipeline` 里复用 |
| `get_crop_and_class` 返回 seg_mask | visual_pipeline.py:76 | 新增第三个返回值，YOLO seg 掩码裁到 box 区域的 uint8 numpy array |
| `color_histogram` 新增 mask 参数 | visual_pipeline.py:43 | 传入时只计算掩码内像素的直方图 |
| 去重比较改用 seg 掩码 | visual_pipeline.py:~145 | 直方图比较时传入 last_mask / curr_mask |
| 前10帧最清晰帧强制插入 | visual_pipeline.py:~155 | 用 `sharpness` 函数选最清晰帧，不重复时插到 filtered 开头 |
| frames 目录清理 | visual_pipeline.py:~160 | `os.listdir` 遍历目录，删除所有不在 kept 集合里的文件 |
| `run_pipeline` 用 rembg 输出 PNG | visual_pipeline.py:~244 | 原来 shutil.copy2，现在 rembg 去背景后保存透明 PNG |
| 新建 `extract_clothing.py` | extract_clothing.py | 调用 `run_pipeline('uploads/20260611_163958.mp4')` 的独立脚本 |

---

## 测试视频

`uploads/20260611_163958.mp4` — 多件服装连续展示的视频

### 当前输出结果评估

| 图片 | 评估 |
|------|------|
| item_01.png | 蓝色夹克，主体干净，衣架/挂钩残留 |
| item_02.png | 深色夹克，实际是两件叠加，色差小未被分离 |
| item_03.png | 多件同框，选帧错误，背景里混了其他衣服 |
| item_04.png | 蓝绿夹克，主体干净，衣架残留 |

---

## 已知问题

### 问题1：衣架残留
- **现象**：item_01、02、04 都带着衣架/挂钩
- **原因**：rembg 是通用背景去除，不区分衣架和衣服
- **潜在方案**：用 YOLO box 精确裁剪后再送 rembg，或在 rembg 后做连通区域分析去掉小块

### 问题2：多件同框（最主要问题）
- **现象**：item_02、03 包含多件叠加的衣服
- **根本原因**：谷值检测用全帧直方图，颜色相近的衣服（尤其深色系）帧差极小，检测不到它们之间的过渡。seg 掩码改进只影响了 dedup 步骤，上游谷值检测未改
- **已排除方案**：CLIP 语义嵌入（用户曾试过，效果不好，早期阶段不引入）

---

## 下一步计划

### 多件同框检测（优先）

在输出 PNG 之前加一步检测，过滤掉包含多件衣服的图：

**方案A — rembg alpha 连通块分析（最简单，推荐先试）**
- rembg 输出 PNG 的 alpha 通道
- `cv2.connectedComponentsWithStats` 找连通区域
- 如果有 2 个以上面积相近的大块 → 判定为多件同框，跳过或标记
- 不需要额外模型

**方案B — YOLO 多框检测（已有能力）**
- 现在只取最高置信度的框
- 如果第二高置信度框与第一框 IoU 低且 conf > 0.4 → 说明镜头里有独立的第二件衣服
- 可在 `get_crop_and_class` 里直接扩展

**方案C — 纹理边界检测（对同色叠加最有针对性）**
- 在 YOLO crop 内用 Canny 或 Gabor 找材质突变线
- 衣服中间有明显水平/竖直纹理分界线 → 两件叠加
- 实现最复杂，留作 A+B 不够用时的备选

**推荐顺序**：先实现 A+B，验证效果，不够再加 C。
