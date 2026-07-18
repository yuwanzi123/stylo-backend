# Session Summary — 2026-07-18

## 目标

实现首页 AI 对话推荐穿搭功能：用户在聊天框描述需求，AI 从衣橱里选一套搭配并拼图展示；支持基于上一套搭配做局部微调。

---

## 数据模型改动（stylo-backend/models.py）

- `ClosetItem` 新增 `category`（top/bottom/outerwear/shoes/other）、`attributes`（JSON字符串：color/style/season/pattern）
- 新增 `Outfit` 表：id(uuid4hex)、user_id、item_ids(JSON数组)、composite_image_path、caption、parent_outfit_id
- 新增 `ChatMessage` 表：id(uuid4hex)、user_id、role、message_type("text"|"outfit_card")、content、outfit_id

`stylo.db` 用 `ALTER TABLE` 手动迁移了 `closet_items` 表加两列，`init_db()` 建了两张新表。

---

## 新增服务（stylo-backend/app/services/）

- `llm_client.py` — 封装 OpenAI chat completions 调用（沿用 visual_pipeline.py 的 tenacity 重试逻辑），支持 json_mode
- `item_classifier.py` — GPT-4o 看图分类 + 打属性标签，`POST /closet/items` 建单品时自动调用
- `outfit_composer.py` — Pillow 网格拼图：上衣一行、下装一行、外套+鞋并排第三行，浅灰背景，已用真实衣橱图测过
- `outfit_recommender.py` — 核心推荐逻辑：
  - `classify_intent()` 判断 new/adjust
  - `recommend_new_outfit()` 按类别筛全量候选，LLM 选 top+bottom（必选）、outerwear+shoes（可选）
  - `recommend_adjustment()` 只在目标类别里重选，其余保留父 outfit 原样，写 parent_outfit_id
  - `recommend()` 统一入口，路由到上述两者

---

## API（stylo-backend/main.py）

- `POST /chat/message` {user_id, text} → {message_id, type, caption, outfit_id, composite_image_url, items}
- `GET /chat/history?user_id=` 按时间顺序返回历史消息，outfit_card 类型消息带完整搭配详情
- `/closet/items` 建单品时接入自动分类
- 新增 `/outfit-images` 静态挂载点

---

## 一次性脚本

`backfill_categories.py` — 给现有 13 件衣服回填 category/attributes（结果：3 top / 3 bottom / 7 outerwear / **0 shoes**）

---

## Android 端（stylo-android）

发现首页 `HomeScreen.kt` 本来就有聊天 UI，但是纯本地 mock（固定回复列表，OutfitCard 从未被真正触发）。今天接上了真实后端：

- `StyloApi.kt` 新增 `sendChatMessage`、`fetchChatHistory`、`getOrCreateUserId`（设备级 UUID，存 SharedPreferences，因为 app 还没有登录态）
- `HomeScreen.kt` 的 `OutfitCard` 改成用 Coil 加载真实拼图，`sendMessage()` 接上真实 API
- 编译通过，装到真机（Samsung SM-A346E）验证：新搭配、微调（只换目标类别）、历史持久化，三条都测过，且用户本人在手机上也实测了两轮真实对话

---

## 已知限制

1. **鞋类未验证** — 衣橱没有鞋子数据，shoes 分类的选款/微调逻辑还没法用真实数据测
2. **ClosetItem 无 user_id** — 衣橱目前全局共享，不分用户（有意延后的决策，等做多用户时再改）
3. Android app 无真正登录态，user_id 是设备本地随机 UUID，卸载重装会丢失历史

---

## 下一步

1. 补充鞋类衣橱数据，验证 shoes 分支
2. 如果要做多用户，需要给 ClosetItem 也加 user_id 并接入真实鉴权
3. 可以考虑给 ChatMessage 加分页（GET /chat/history 现在是全量返回）
