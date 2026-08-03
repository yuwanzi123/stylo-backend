import json
import os
from typing import Dict, List

from sqlalchemy.orm import Session

from models import ChatMessage, ClosetItem, Outfit
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

规则：
- 必须选 1 件 top 和 1 件 bottom
- outerwear 和 shoes 如果候选中有合适的就选一件，没有合适的可以留空（null）
- 只能选候选列表中出现过的 id，不能编造
- 若用户消息表示想要不同的搭配（比如"换一身""不喜欢这套""再换一套"等），且候选中存在其他合适的选项，就不要选出和"最近一次推荐的单品 id"完全相同的 top+bottom 组合
- caption 绝对不能和"用户最新消息"的原文一字不差，必须是你自己组织的完整句子，说明为什么选了这几件单品（可以提到具体的颜色/材质/风格）

只返回 JSON：
{{"top": <id或null>, "bottom": <id或null>, "outerwear": <id或null>, "shoes": <id或null>, "caption": "一句话说明这套搭配为什么合适"}}

{language_directive}
"""


def select_new_outfit(
    candidates: List[ClosetItem], user_message: str, history: List[dict], previous_item_ids: List[int]
) -> Dict:
    prompt = NEW_OUTFIT_PROMPT.format(
        candidates=_format_candidates(candidates),
        history=_format_history(history),
        message=user_message,
        previous_item_ids=previous_item_ids or "(无)",
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

caption 绝对不能和"用户最新消息"的原文一字不差，必须是你自己组织的完整句子，说明为什么做了这次调整（可以提到具体的颜色/材质/风格）。

只返回 JSON：{{"item_id": <id或null>, "caption": "一句话说明这次调整"}}
若没有合适的候选，item_id 返回 null。

{language_directive}
"""


def select_adjustment(candidates: List[ClosetItem], target_category: str, user_message: str, history: List[dict]) -> Dict:
    prompt = ADJUST_PROMPT.format(
        target_category=target_category,
        candidates=_format_candidates(candidates),
        history=_format_history(history),
        message=user_message,
        language_directive=LANGUAGE_DIRECTIVE.format(message=user_message),
    )
    content = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
        max_tokens=200,
    )
    return json.loads(content)


def recommend_adjustment(db: Session, user_id: str, user_message: str, parent: Outfit, target_category: str) -> Outfit:
    history = _get_recent_history(db, user_id)
    candidates = db.query(ClosetItem).filter(ClosetItem.category == target_category).all()
    result = select_adjustment(candidates, target_category, user_message, history)

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
    history = _get_recent_history(db, user_id)
    candidates = db.query(ClosetItem).filter(ClosetItem.category.in_(CATEGORIES)).all()

    previous_outfit = (
        db.query(Outfit)
        .filter(Outfit.user_id == user_id)
        .order_by(Outfit.created_at.desc())
        .first()
    )
    previous_item_ids = json.loads(previous_outfit.item_ids) if previous_outfit else []

    result = select_new_outfit(candidates, user_message, history, previous_item_ids)

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
