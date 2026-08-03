import json

from models import SessionLocal, ClosetItem
from app.services.llm_client import get_embedding

db = SessionLocal()
try:
    items = db.query(ClosetItem).filter(
        (ClosetItem.embedding.is_(None)) | (ClosetItem.embedding == "")
    ).all()

    print(f"Found {len(items)} closet items missing embedding.")

    succeeded = 0
    failed = 0
    for i, item in enumerate(items, start=1):
        print(f"[{i}/{len(items)}] item id={item.id} ...", end=" ")

        if not item.description:
            print("SKIP (no description)")
            failed += 1
            continue

        try:
            vector = get_embedding(item.description)
            item.embedding = json.dumps(vector)
            db.commit()
            print(f"OK ({len(vector)} dims)")
            succeeded += 1
        except Exception as e:
            db.rollback()
            print(f"FAILED ({e})")
            failed += 1

    print(f"\n=== done: {succeeded} succeeded, {failed} failed/skipped, {len(items)} total ===")
finally:
    db.close()
