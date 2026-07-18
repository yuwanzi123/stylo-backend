import json

from app.services.llm_client import chat_completion, image_to_data_url

VALID_CATEGORIES = {"top", "bottom", "outerwear", "shoes", "other"}

CLASSIFY_PROMPT = """你是一个衣橱管理助手。请看这张单品服装图片，判断它的类别和特点。

category 必须是以下之一：
- "top"：上衣（T恤、衬衫、卫衣、毛衣等不含外套的上身单品）
- "bottom"：下装（裤子、裙子、短裤等）
- "outerwear"：外套（夹克、大衣、风衣、羽绒服等）
- "shoes"：鞋
- "other"：以上都不是

只返回 JSON，格式：
{
  "category": "top",
  "attributes": {"color": "颜色", "style": "风格，如休闲/正式/运动", "season": "适合季节", "pattern": "图案，如纯色/条纹/格纹"},
  "description": "一句话描述这件单品，包含颜色、版型、材质等细节"
}
"""


def classify_item(image_path: str) -> dict:
    content = chat_completion(
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                {"type": "text", "text": CLASSIFY_PROMPT},
            ],
        }],
        json_mode=True,
        max_tokens=300,
    )
    result = json.loads(content)
    if result.get("category") not in VALID_CATEGORIES:
        result["category"] = "other"
    return result
