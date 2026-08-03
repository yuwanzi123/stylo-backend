import json

from app.services.llm_client import chat_completion, image_to_data_url

VALID_CATEGORIES = {"top", "bottom", "outerwear", "shoes", "other"}

CLASSIFY_PROMPT = """You are a closet management assistant. Look at this clothing item photo and identify its category and attributes.

category must be one of:
- "top": T-shirts, shirts, hoodies, sweaters, and other upper-body pieces that are not outerwear
- "bottom": pants, skirts, shorts, etc.
- "outerwear": jackets, coats, trench coats, down jackets, etc.
- "shoes": footwear
- "other": none of the above

IMPORTANT: "description" and every value inside "attributes" must be written in English, regardless of
what language this instruction is in. Do not output Chinese or any other language.

Return JSON only, in this exact format:
{
  "category": "top",
  "attributes": {"color": "color name", "style": "e.g. casual/formal/athletic", "season": "season it suits", "pattern": "e.g. solid/striped/plaid"},
  "description": "one sentence describing the item, including color, fit, and material details"
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
