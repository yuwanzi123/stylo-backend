# Stylo Backend

AI 穿搭助手后端。上传衣物照片/视频 → 自动抠图分类入衣橱 → 首页 AI 对话推荐搭配（拼图/融合展示）。

## 环境

- Python 3.11（conda 环境 `stylo`，路径 `/home/zzz/miniconda3/envs/stylo`）
- 关键依赖：FastAPI、uvicorn、SQLAlchemy（SQLite）、ultralytics（YOLOv8-seg 服装检测）、rembg（抠图去背景）、torch（GPU）、openai（GPT-4o / gpt-image-1）
- `OPENAI_API_KEY` 已在 `~/.bashrc` 里 export，新开的 shell 会自动带上，不用额外配置

## 启动 / 停止

```bash
cd /home/zzz/stylo/stylo-backend
./start.sh   # 激活 conda stylo 环境 + 后台启动 uvicorn，已在跑会自动跳过
./stop.sh    # 停止
```

- 服务监听 `0.0.0.0:8000`
- 日志：`uvicorn.log`；PID 文件：`uvicorn.pid`
- 本机联网装了 Tailscale，`start.sh` 启动成功会打印 Tailscale 地址，手机不在同一 WiFi 下也能通过它连后端（详见 Android 端 `StyloApi.kt` 的 `BASE_URL`）

健康检查：
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/docs   # 200 说明正常
```

## 目录结构

```
main.py                      FastAPI 入口，所有路由
models.py                    SQLAlchemy 模型（ClosetItem / Outfit / ChatMessage），SQLite: stylo.db
visual_pipeline.py            视频/图片 → 抽帧/裁剪/YOLO 分类/抠图 流水线
app/services/
  item_classifier.py          单件衣物分类（调用 GPT-4o 打标签）
  llm_client.py                OpenAI API 封装（chat_completion 等）
  outfit_recommender.py       AI 对话推荐搭配逻辑（意图分类、选品、生成 caption）
  outfit_composer.py          把选中的多件衣物合成一张搭配展示图（分层叠放）
deepfashion2_yolov8s-seg.pt   YOLO 服装分割权重
uploads/                      用户上传的原始视频/图片
outfit_output/                合成的搭配展示图
start.sh / stop.sh            启停脚本
```

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/upload` | 上传图片，异步处理返回 task_id |
| POST | `/upload-video` | 上传视频，异步处理返回 task_id |
| GET | `/task/{task_id}` | 轮询处理进度/结果 |
| POST | `/closet/items` | 新增衣橱单品 |
| GET | `/closet/items` | 查询衣橱 |
| DELETE | `/closet/items/{item_id}` | 删除单品 |
| POST | `/closet/items/{item_id}/edit/start` | 编辑单品（重新处理） |
| POST | `/chat/message` | 发送对话消息，触发穿搭推荐 |
| GET | `/chat/history` | 拉取对话历史 |

完整参数见 `main.py` 或启动后访问 `/docs`（FastAPI 自带的 Swagger UI）。

## 已知限制

- workstation 断电/断网/睡眠时，手机端（依赖本地 GPU + Tailscale 转发）完全用不了，睡眠策略还没排查
- `TrendingFashionCard`（Android 首页）目前是 mock 数据，未接入真实数据源
