import json

from models import SessionLocal, ClosetItem
from app.services.llm_client import chat_completion, get_embedding

TRANSLATE_PROMPT = """Translate the following clothing item description and attributes into English.
Keep the meaning exact, do not add or drop details. IMPORTANT: the output must be entirely in
English -- do not leave any Chinese text in either field.

description: {description}
attributes: {attributes}

Return JSON only, in this exact format:
{{"description": "...", "attributes": {{"color": "...", "style": "...", "season": "...", "pattern": "..."}}}}
"""


def translate_to_english(description: str, attributes: dict) -> dict:
    content = chat_completion(
        messages=[{
            "role": "user",
            "content": TRANSLATE_PROMPT.format(
                description=description,
                attributes=json.dumps(attributes, ensure_ascii=False),
            ),
        }],
        json_mode=True,
        max_tokens=300,
    )
    return json.loads(content)


db = SessionLocal()
try:
    items = db.query(ClosetItem).filter(ClosetItem.description.isnot(None)).all()
    print(f"Found {len(items)} closet items to translate.")

    succeeded = 0
    failed = 0
    for i, item in enumerate(items, start=1):
        print(f"[{i}/{len(items)}] item id={item.id} ...", end=" ")
        try:
            attributes = json.loads(item.attributes) if item.attributes else {}
            translated = translate_to_english(item.description, attributes)

            item.description = translated["description"]
            item.attributes = json.dumps(translated.get("attributes", {}), ensure_ascii=False)
            item.embedding = json.dumps(get_embedding(item.description))
            db.commit()
            print(f"OK -> {item.description}")
            succeeded += 1
        except Exception as e:
            db.rollback()
            print(f"FAILED ({e})")
            failed += 1

    print(f"\n=== done: {succeeded} succeeded, {failed} failed, {len(items)} total ===")
finally:
    db.close()
