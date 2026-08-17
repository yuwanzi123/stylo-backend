import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from models import ChatMessage, ClosetItem, DailyConstraint, Outfit, StandingPreference
from app.services.llm_client import chat_completion
from app.services.outfit_composer import compose_outfit_image

CATEGORIES = ("top", "bottom", "outerwear", "shoes")
CLOSET_IMAGE_ROOT = "visual_output"
HISTORY_LIMIT = 10

LANGUAGE_DIRECTIVE = (
    'IMPORTANT: write "caption" in the exact same language as this user message: "{message}". '
    "Do not translate it into Chinese or any other language — match the user's language exactly."
)


def _image_path(item: ClosetItem) -> str:
    prefix = "/images/"
    relative = item.image_url[len(prefix):] if item.image_url.startswith(prefix) else item.image_url.lstrip("/")
    return os.path.join(CLOSET_IMAGE_ROOT, relative)


def _format_candidates(items: List[ClosetItem]) -> str:
    if not items:
        return "(无)"
    return "\n".join(
        f"id={it.id} category={it.category} description={it.description or ''} attributes={it.attributes or '{}'}"
        for it in items
    )


def _format_history(history: List[dict]) -> str:
    if not history:
        return "(无)"
    return "\n".join(f"{m['role']}: {m['content']}" for m in history)


def _closet_summary(db: Session) -> str:
    """Per-category rundown of what's actually in the closet, so intent
    classification can tell whether a category can plausibly satisfy a
    request (e.g. "warmer") instead of guessing blind."""
    items = db.query(ClosetItem).filter(ClosetItem.category.in_(CATEGORIES)).all()
    by_category: Dict[str, List[ClosetItem]] = {c: [] for c in CATEGORIES}
    for it in items:
        by_category.setdefault(it.category, []).append(it)

    lines = []
    for c in CATEGORIES:
        items_c = by_category.get(c, [])
        if not items_c:
            lines.append(f"{c}: 无")
        else:
            descs = "；".join(it.description or "" for it in items_c)
            lines.append(f"{c}（{len(items_c)}件）：{descs}")
    return "\n".join(lines)


NEW_OUTFIT_PROMPT = """你是一个专业穿搭顾问。请根据用户需求，从候选衣物中选出一套搭配。

候选衣物（id/类别/描述/属性）：
{candidates}

对话历史：
{history}

用户最新消息：{message}

最近一次推荐的单品 id：{previous_item_ids}

{constraints}

规则：
- 必须选 1 件 top 和 1 件 bottom
- outerwear 和 shoes 如果候选中有合适的就选一件，没有合适的可以留空（null）
- 只能选候选列表中出现过的 id，不能编造
- 若用户消息表示想要不同的搭配（比如"换一身""不喜欢这套""再换一套"等），且候选中存在其他合适的选项，就不要选出和"最近一次推荐的单品 id"完全相同的 top+bottom 组合
- 上面"用户的长期偏好"和"用户今天说的场景要求"必须遵守，选品时优先排除违反这些要求的候选；如果候选里确实没有满足要求的选项，就选最接近的，并在 caption 里如实说明这个取舍
- caption 绝对不能和"用户最新消息"的原文一字不差，必须是你自己组织的完整句子，说明为什么选了这几件单品（可以提到具体的颜色/材质/风格，如果是因为长期偏好或今天的场景要求而选的，也可以提一句）

只返回 JSON：
{{"top": <id或null>, "bottom": <id或null>, "outerwear": <id或null>, "shoes": <id或null>, "caption": "一句话说明这套搭配为什么合适"}}

{language_directive}
"""


def select_new_outfit(
    candidates: List[ClosetItem],
    user_message: str,
    history: List[dict],
    previous_item_ids: List[int],
    constraints_text: str = "(无)",
) -> Dict:
    prompt = NEW_OUTFIT_PROMPT.format(
        candidates=_format_candidates(candidates),
        history=_format_history(history),
        message=user_message,
        previous_item_ids=previous_item_ids or "(无)",
        constraints=constraints_text,
        language_directive=LANGUAGE_DIRECTIVE.format(message=user_message),
    )
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=300,
    )
    return json.loads(content)


def _get_recent_history(db: Session, user_id: str) -> List[dict]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


CONSTRAINT_EXTRACTION_PROMPT = """你是一个约束提取模块，负责从用户的一句话里判断是否包含穿搭相关的"约束"或"偏好"，并给每条判断归属（scope）。

用户消息：{message}

什么算约束：
- 用户明确表达了"某类衣服不要穿/不想穿"、"必须穿某类衣服"、"某种场合/天气/身体感受相关的穿衣要求"
- 单纯的提问（比如"这样会不会太晒"）、闲聊、或者对已推荐搭配本身的评价（比如"好看"、"不喜欢这套"、"换一套"）不算约束，不要提取——那是搭配调整意图，不是约束

两种 scope，必须严格区分，不允许模糊：
- "daily"：只在当天/这次/这个场合有效的临时性约束，通常带时间或场合限定词，比如"今天""这次""待会儿要去...""明天要..."。
  例：「今天只想穿短袖」→ daily；「这次是打高尔夫场合，穿正式一点」→ daily；「待会儿要去爬山」→ daily
- "standing"：跟身体感受、审美、长期习惯有关的陈述性偏好，没有时间限定，说了之后应该一直有效直到用户明确取消。
  例：「我不穿高跟鞋」→ standing；「我很怕热」→ standing；「我讨厌荧光色」→ standing；「我从不穿裙子」→ standing

严格规则：
- 一句话可能包含 0 条、1 条或多条约束，各自独立判断 scope，不要遗漏，也不要编造消息里没有的内容
- 如果一句话里同时包含"场合/场景"信息（比如"打高尔夫""去爬山""公司年会"）和"具体着装要求"信息（比如"只想穿短袖""要穿舒服的鞋""不要裙子"），必须拆成两条独立的约束分别提取，不要合并成一条、也不要让其中一条把另一条吸收掉。
  例：「今天要打高尔夫，只想穿短袖」→ 两条：「今天场合是打高尔夫」(daily) 和「今天只想穿短袖」(daily)
  如果一句话只包含其中一种信息（比如只提到场合、没提具体要求），就只提取那一条，不要强行编造消息里没说过的额外约束
- 如果用户是在解除/取消之前说过的某条长期偏好（比如"我现在可以穿高跟鞋了""不用忌口这个了"），这**不算**新约束，不要提取——这类表达由另一个模块处理
- 如果这句话没有任何约束，constraints 必须是空数组 []，不允许强行凑一条
- text 字段写成一句独立完整、不依赖上下文就能理解的话（把"这个/这样"之类替换成具体内容），不要照抄原话里的口语碎片

只返回 JSON：
{{"constraints": [{{"text": "...", "scope": "daily或standing"}}, ...]}}
"""


def extract_constraints(user_message: str) -> List[Dict]:
    prompt = CONSTRAINT_EXTRACTION_PROMPT.format(message=user_message)
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=300,
    )
    result = json.loads(content)
    constraints = result.get("constraints", [])
    return [
        c for c in constraints
        if isinstance(c, dict) and c.get("text") and c.get("scope") in ("daily", "standing")
    ]


def _persist_constraints(db: Session, user_id: str, constraints: List[Dict]) -> None:
    if not constraints:
        return
    for c in constraints:
        if c["scope"] == "daily":
            db.add(DailyConstraint(user_id=user_id, constraint_text=c["text"]))
        else:
            db.add(StandingPreference(user_id=user_id, preference_text=c["text"]))
    db.commit()


def extract_and_persist_constraints(db: Session, user_id: str, user_message: str) -> List[Dict]:
    constraints = extract_constraints(user_message)
    _persist_constraints(db, user_id, constraints)
    return constraints


def _today_utc_bounds() -> Tuple[datetime, datetime]:
    """"Today" per the server's local system time zone, converted to naive UTC
    bounds — DailyConstraint.created_at is stored as datetime.utcnow(), so the
    query range has to match that, not local time."""
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


def _get_standing_preferences(db: Session, user_id: str) -> List[str]:
    rows = (
        db.query(StandingPreference)
        .filter(StandingPreference.user_id == user_id)
        .order_by(StandingPreference.created_at.asc())
        .all()
    )
    return [r.preference_text for r in rows]


def _get_today_daily_constraints(db: Session, user_id: str) -> List[str]:
    start_utc, end_utc = _today_utc_bounds()
    rows = (
        db.query(DailyConstraint)
        .filter(DailyConstraint.user_id == user_id)
        .filter(DailyConstraint.created_at >= start_utc)
        .filter(DailyConstraint.created_at < end_utc)
        .order_by(DailyConstraint.created_at.asc())
        .all()
    )
    return [r.constraint_text for r in rows]


def _format_constraints(standing: List[str], daily: List[str]) -> str:
    if not standing and not daily:
        return "(无)"
    lines = []
    if standing:
        lines.append("用户的长期偏好（一直有效）：" + "；".join(standing))
    if daily:
        lines.append("用户今天说的场景要求（只对今天有效）：" + "；".join(daily))
    return "\n".join(lines)


def get_active_constraints_text(db: Session, user_id: str) -> str:
    standing = _get_standing_preferences(db, user_id)
    daily = _get_today_daily_constraints(db, user_id)
    return _format_constraints(standing, daily)


PREFERENCE_REMOVAL_PROMPT = """你是一个偏好解除判断模块。用户可能想解除之前存过的某条长期偏好。

已存储的长期偏好（id/内容）：
{preferences}

用户最新消息：{message}

判断依据：
- 如果用户消息明确表示某条已存储偏好不再成立了（比如"我现在可以穿高跟鞋了""不用忌口这个了""以前说的不算了"），把对应偏好的 id 列出来
- 只能选上面列表里真实存在的 id，绝对不能编造不存在的 id
- 如果消息没有解除意图，或者对应不上任何一条已存储偏好，remove_ids 返回空数组，不要瞎猜、不要因为话题沾边就乱删
- 一条消息可能同时解除多条偏好，也可能一条都不解除

只返回 JSON：
{{"remove_ids": [<id>, ...]}}
"""


def _get_standing_preference_rows(db: Session, user_id: str) -> List[StandingPreference]:
    return (
        db.query(StandingPreference)
        .filter(StandingPreference.user_id == user_id)
        .order_by(StandingPreference.created_at.asc())
        .all()
    )


def _format_preferences_for_removal(rows: List[StandingPreference]) -> str:
    if not rows:
        return "(无)"
    return "\n".join(f"id={r.id} content={r.preference_text}" for r in rows)


def detect_preference_removals(user_message: str, rows: List[StandingPreference]) -> List[int]:
    if not rows:
        return []
    prompt = PREFERENCE_REMOVAL_PROMPT.format(
        preferences=_format_preferences_for_removal(rows),
        message=user_message,
    )
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=200,
    )
    result = json.loads(content)
    valid_ids = {r.id for r in rows}
    return [i for i in result.get("remove_ids", []) if i in valid_ids]


def remove_standing_preferences(db: Session, user_id: str, ids: List[int]) -> int:
    if not ids:
        return 0
    deleted = (
        db.query(StandingPreference)
        .filter(StandingPreference.user_id == user_id, StandingPreference.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def detect_and_remove_preferences(db: Session, user_id: str, user_message: str) -> List[int]:
    rows = _get_standing_preference_rows(db, user_id)
    ids = detect_preference_removals(user_message, rows)
    remove_standing_preferences(db, user_id, ids)
    return ids


def process_constraint_updates(db: Session, user_id: str, user_message: str) -> None:
    """Handle both directions of standing-preference lifecycle for one user
    message: lifting an old one first, then extracting/persisting any new
    constraints — order matters so a message that both cancels an old
    preference and states a new one doesn't race against itself."""
    detect_and_remove_preferences(db, user_id, user_message)
    extract_and_persist_constraints(db, user_id, user_message)


INTENT_PROMPT = """你是一个穿搭助手的意图识别模块。根据对话历史和用户最新消息，判断用户是想要：
- "new"：想要一套全新的搭配推荐
- "adjust"：想在最近一次推荐的搭配基础上做局部微调（比如换一件外套、换个下装、换双鞋）

衣橱现状（每个类别实际有哪些衣服）：
{closet_summary}

对话历史：
{history}

用户最新消息：{message}

如果用户的要求和衣物本身的特性有关（比如"想穿厚点/薄点/暖和点/凉快点"），target_category 必须选衣橱里真的有对应选项的类别——参考上面的衣橱现状，不要选一个里面所有衣服都不符合需求的类别（比如所有上衣都是短袖，但外套里有很多秋冬夹克，这时要选 outerwear 而不是 top）。

只返回 JSON：
- 新搭配请求：{{"intent": "new"}}
- 微调请求：{{"intent": "adjust", "target_category": "top"}}，target_category 必须是 top/bottom/outerwear/shoes 之一，表示要替换哪个类别
"""


def classify_intent(user_message: str, history: List[dict], closet_summary: str) -> Dict:
    prompt = INTENT_PROMPT.format(
        history=_format_history(history), message=user_message, closet_summary=closet_summary
    )
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=100,
    )
    result = json.loads(content)
    if result.get("intent") not in ("new", "adjust"):
        result["intent"] = "new"
    if result.get("intent") == "adjust" and result.get("target_category") not in CATEGORIES:
        result["intent"] = "new"
    return result


ADJUST_PROMPT = """你是一个专业穿搭顾问。用户想微调当前搭配中的 {target_category} 单品，请从候选中选出最合适的一件替换。

候选 {target_category}（id/描述/属性）：
{candidates}

对话历史：
{history}

用户最新消息：{message}

{constraints}

caption 绝对不能和"用户最新消息"的原文一字不差，必须是你自己组织的完整句子，说明为什么做了这次调整（可以提到具体的颜色/材质/风格）。
上面"用户的长期偏好"和"用户今天说的场景要求"必须遵守，选品时优先排除违反这些要求的候选；如果候选里确实没有满足要求的选项，就选最接近的，并在 caption 里如实说明这个取舍。

只返回 JSON：{{"item_id": <id或null>, "caption": "一句话说明这次调整"}}
若没有合适的候选，item_id 返回 null。

{language_directive}
"""


def select_adjustment(
    candidates: List[ClosetItem],
    target_category: str,
    user_message: str,
    history: List[dict],
    constraints_text: str = "(无)",
) -> Dict:
    prompt = ADJUST_PROMPT.format(
        target_category=target_category,
        candidates=_format_candidates(candidates),
        history=_format_history(history),
        message=user_message,
        constraints=constraints_text,
        language_directive=LANGUAGE_DIRECTIVE.format(message=user_message),
    )
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=200,
    )
    return json.loads(content)


def recommend_adjustment(db: Session, user_id: str, user_message: str, parent: Outfit, target_category: str) -> Outfit:
    process_constraint_updates(db, user_id, user_message)
    history = _get_recent_history(db, user_id)
    constraints_text = get_active_constraints_text(db, user_id)
    candidates = db.query(ClosetItem).filter(ClosetItem.category == target_category).all()
    result = select_adjustment(candidates, target_category, user_message, history, constraints_text)

    items_by_id = {it.id: it for it in candidates}
    new_item = items_by_id.get(result.get("item_id"))

    parent_item_ids = json.loads(parent.item_ids)
    parent_items = db.query(ClosetItem).filter(ClosetItem.id.in_(parent_item_ids)).all()
    parent_items_by_id = {it.id: it for it in parent_items}

    final_items = []
    replaced_slot = False
    for iid in parent_item_ids:
        old_item = parent_items_by_id.get(iid)
        if old_item is None:
            continue
        if old_item.category == target_category:
            final_items.append(new_item if new_item else old_item)
            replaced_slot = True
        else:
            final_items.append(old_item)

    if new_item and not replaced_slot:
        final_items.append(new_item)

    if not final_items:
        raise ValueError("Adjustment produced no items")

    tops = [_image_path(i) for i in final_items if i.category == "top"]
    bottoms = [_image_path(i) for i in final_items if i.category == "bottom"]
    outerwear = [_image_path(i) for i in final_items if i.category == "outerwear"]
    shoes = [_image_path(i) for i in final_items if i.category == "shoes"]

    composite_path = compose_outfit_image(tops=tops, bottoms=bottoms, outerwear=outerwear, shoes=shoes)

    outfit = Outfit(
        user_id=user_id,
        item_ids=json.dumps([i.id for i in final_items]),
        composite_image_path=composite_path,
        caption=result.get("caption", ""),
        parent_outfit_id=parent.id,
    )
    db.add(outfit)
    db.commit()
    db.refresh(outfit)
    return outfit


def recommend(db: Session, user_id: str, user_message: str) -> Outfit:
    history = _get_recent_history(db, user_id)
    intent = classify_intent(user_message, history, _closet_summary(db))

    if intent["intent"] == "adjust":
        parent = (
            db.query(Outfit)
            .filter(Outfit.user_id == user_id)
            .order_by(Outfit.created_at.desc())
            .first()
        )
        if parent is not None:
            return recommend_adjustment(db, user_id, user_message, parent, intent["target_category"])

    return recommend_new_outfit(db, user_id, user_message)


def recommend_new_outfit(db: Session, user_id: str, user_message: str) -> Outfit:
    process_constraint_updates(db, user_id, user_message)
    history = _get_recent_history(db, user_id)
    constraints_text = get_active_constraints_text(db, user_id)
    candidates = db.query(ClosetItem).filter(ClosetItem.category.in_(CATEGORIES)).all()

    previous_outfit = (
        db.query(Outfit)
        .filter(Outfit.user_id == user_id)
        .order_by(Outfit.created_at.desc())
        .first()
    )
    previous_item_ids = json.loads(previous_outfit.item_ids) if previous_outfit else []

    result = select_new_outfit(candidates, user_message, history, previous_item_ids, constraints_text)

    raw_ids = [result[c] for c in CATEGORIES if result.get(c)]
    items_by_id = {it.id: it for it in candidates}
    selected = [items_by_id[iid] for iid in raw_ids if iid in items_by_id]
    if not selected:
        raise ValueError(f"LLM did not select any valid items, got: {result}")

    tops = [_image_path(i) for i in selected if i.category == "top"]
    bottoms = [_image_path(i) for i in selected if i.category == "bottom"]
    outerwear = [_image_path(i) for i in selected if i.category == "outerwear"]
    shoes = [_image_path(i) for i in selected if i.category == "shoes"]

    composite_path = compose_outfit_image(tops=tops, bottoms=bottoms, outerwear=outerwear, shoes=shoes)

    outfit = Outfit(
        user_id=user_id,
        item_ids=json.dumps([i.id for i in selected]),
        composite_image_path=composite_path,
        caption=result.get("caption", ""),
        parent_outfit_id=None,
    )
    db.add(outfit)
    db.commit()
    db.refresh(outfit)
    return outfit
