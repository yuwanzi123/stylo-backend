# Session Summary — 2026-07-18（下午/晚间）

承接今天凌晨的 commit `6ed9d8a`（首页 AI 对话推荐穿搭功能）。这次是当天下午到晚上做的一系列 bug fix + 一个小 feature，**目前全部改动都还没有提交**（见文末"未提交改动"）。

---

## 1. 远程访问修复（Tailscale）

**问题**：手机离开家里 WiFi 就连不上后端。

**根因**：`stylo-android/app/src/main/java/com/stylo/app/StyloApi.kt:100` 的 `BASE_URL` 写死了局域网 IP `http://10.0.0.109:8000`。

**排查过程**：workstation 上的 Tailscale 其实是之前为了 NoMachine 远程桌面装的，一直忘了能顺手拿来用。确认手机（`galaxy-a34-5g`）和 workstation（`zstation`，tailscale IP `100.97.248.72`）已经在同一个 tailnet 里。

**改动**：
- `StyloApi.kt:100` → `BASE_URL = "http://100.97.248.72:8000"`
- `MainActivity.kt:269` 原来单独写死了一份 `10.0.0.109` 的 URL（上传视频用），改成引用 `StyloApi.BASE_URL`

后端启动命令本来就是 `--host 0.0.0.0`，不用改。已编译 + adb 装机验证过。

**用户下午出门后用手机（不在家里 WiFi）实测过，确认能连上。**

---

## 2. 拼图融合（衣物合成一张图）

**问题**：用户反馈 outfit 卡片里衣物是"网格拼图"，看着像两张照片拼接，不像一整套穿搭。

**方案**：讨论了生成式重绘 vs 保留真实照片两种思路，用户选了后者。重写了 `app/services/outfit_composer.py`：

- `_load_cropped`：如果图片没有透明通道（比如 ClosetItem 实际用的 `*_flat.png`，是 gpt-image-1 生成的近白背景产品图），现调 `rembg.remove()` 去背景，再按 alpha bbox 裁剪
- 主体按 top → bottom → shoes 顺序垂直叠放，用固定像素的 overlap（不是按各自图片高度的比例——之前用比例导致有一次两件图高度差异大时几乎完全遮住了上衣，后来改成固定像素）
- outerwear：如果有 top，outerwear 作为背景层贴在 top 后面、更宽，露出"敞开穿"的效果；如果没有 top（比如只选了外套+裤子），outerwear 直接顶替 top 的位置，不再和裤子重叠在一起（这是之前一个真实 bug，见下）

**期间修的一个 bug**：`深蓝色连帽拉链卫衣` 分类是 outerwear，某次推荐没选 top，结果 outerwear 和 bottom 都从 y=0 起画，裤子几乎完全盖住了外套。改成"没有 top 时 outerwear 顶替 top 位置"后修复。

**已用真实衣橱数据（`stylo.db` 里的 13 件已分类衣物）端到端测试过，效果自然。**

---

## 3. AI 回复语言跟随用户输入

**需求**：用户用中文提问就中文回复，用英文就英文回复。

**改动**：`app/services/outfit_recommender.py` 里 `NEW_OUTFIT_PROMPT` / `ADJUST_PROMPT` 加了 `LANGUAGE_DIRECTIVE`，把用户原始消息原文引用进指令里强调"必须用同一种语言，不能翻译成中文"。

**踩过的坑**：第一版指令写得比较委婉（"caption 必须使用用户消息所用的语言"），GPT-4o 经常不理会，还是习惯性回中文——因为整个 prompt 90% 都是中文指令。后来把指令改成明确引用用户原句的英文祈使句才稳定生效。中文、英文的 new/adjust 场景都测过。

---

## 4. "换一身"/"来回来去就这两身" —— 重复推荐同一套

**问题**：衣橱只有 3 件上衣 3 件下装，用户说"换一身"，模型经常选出和上一次一模一样的 top+bottom；有一次甚至把 caption 直接写成了用户输入的原文"换一身"（复读机 bug）。

**改动**：
- `recommend_new_outfit` 现在会查最近一次的 `Outfit` 记录，把它的单品 id 传给 `select_new_outfit` 的 prompt，明确要求"如果用户想要不同的搭配，别选出和上次完全一样的组合"
- 加了更强的反复读指令（见下一条的踩坑经验，对 NEW_OUTFIT_PROMPT 和 ADJUST_PROMPT 都生效）

---

## 5. "我想穿厚一点"却还是推短袖短裤

**用户怀疑**：是不是有些衣服没打 tag？

**排查结论：不是。** 检查过 `stylo.db`，14 件衣物全部都有 category + attributes（color/style/season/pattern）。真正的原因有两个：

1. **`classify_intent` 完全看不到衣橱内容**，只凭一句话猜要调整哪个类别（top/bottom/outerwear/shoes）。衣橱里 3 件上衣全是短袖，根本不存在"更厚的上衣"，但外套里有 7 件秋冬夹克——模型却经常猜成调整 top，白猜。
   → 改动：新增 `_closet_summary(db)`，把每个类别现有衣物的简要描述喂给 `classify_intent`，并加规则"要选真的有对应选项的类别"。
2. **LLM 调用没设 `temperature`**，默认值很随机，同样的输入换几次跑结果都不一样（一会儿猜对 outerwear，一会儿猜 top）。
   → 改动：`app/services/llm_client.py` 的 `chat_completion` 加了 `temperature=0.2` 默认值。

**caption 复读 bug 的最终修法**：一开始加的反复读指令是"不能只是重复或照抄用户消息原文"，测试发现 GPT-4o 根本不理会，稳定复现复读。换成更直白强硬的说法："caption 绝对不能和'用户最新消息'的原文一字不差，必须是你自己组织的完整句子，说明为什么选了这几件单品（可以提到具体的颜色/材质/风格）"之后，连续测 3 次都生成了正常、不同的句子。**这是本次 session 最重要的经验：给 GPT-4o 的行为约束指令，措辞委婉/模糊基本没用，必须写得非常具体、甚至带点"强制感"。**

修完后完整链路测过：见客户 → 换一身（选出不同组合）→ 穿厚一点（正确加上外套，caption 正常）。

---

## 6. "退出聊天"入口（小 feature）

**需求**：用户想要能退出当前聊天，回到"首页"，探讨了几种首页内容方案（真实流行趋势 vs 复用衣橱数据 vs 4-tab 导航重构），最后决定先做最小版本。

**改动**（`stylo-android/app/src/main/java/com/stylo/app/HomeScreen.kt`）：
- 新增 `chatVisible` 状态
- 有聊天记录时，顶部栏出现一个 × 图标，点击后隐藏对话、显示原本就存在但只在"空历史"时才会显示的 `TrendingFashionCard`（目前还是纯 mock 数据，代码里有 `TODO: 接入真实流行趋势图片数据`）
- 发送新消息会自动把 `chatVisible` 设回 true，对话重新出现

**没有做**：4-tab 导航重构、真实"流行趋势"数据源——这些是更大的架构/产品决策，当时判断对单用户验证阶段来说还早，用户也认可先不做。

---

## 当前运行状态

- 后端进程 **目前在跑**（PID 见 `ps aux | grep uvicorn`），命令是：
  ```
  cd /home/zzz/stylo-backend && /home/zzz/miniconda3/envs/stylo/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
  ```
- 编译 Android 需要 `export JAVA_HOME=/snap/android-studio/232/jbr`（这台机器没有单独装 JDK，只有 Android Studio 自带的 JBR，`gradlew` 默认找不到）
- 手机通过 Tailscale 连接，`adb` 已授权过（USB 连接，`SM_A346E`）

## 未提交改动（明天先看这个）

```
stylo-backend:
  M app/services/llm_client.py
  M app/services/outfit_composer.py
  M app/services/outfit_recommender.py

stylo-android:
  M app/src/main/java/com/stylo/app/HomeScreen.kt
  M app/src/main/java/com/stylo/app/MainActivity.kt
  M app/src/main/java/com/stylo/app/StyloApi.kt
```

都还没有 commit，也没有决定怎么拆分 commit——明天可以先看 diff 决定是拆成"远程访问修复"/"拼图融合"/"推荐逻辑修复"/"退出聊天"几个 commit，还是合成一个。

## 下一步（还没做的）

1. 开机脚本（conda activate + 启动 uvicorn）——从上次会话就说要做，一直被别的问题打断，还没写
2. 查 workstation 电源/睡眠设置，确认长时间不操作会不会自动待机断网（关系到手机远程能不能一直连上）
3. `TrendingFashionCard` 还是纯 mock 数据，要不要接真实数据或者干脆换成衣橱缩略图墙，没定
4. 衣橱目前完全没有鞋子数据（0 双鞋），shoes 分支的选款/微调逻辑还没法用真实数据验证——这是更早期就记录的已知限制
