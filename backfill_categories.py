import json

from main import image_url_to_path
from models import SessionLocal, ClosetItem
from app.services.item_classifier import classify_item


def main():
    db = SessionLocal()
    try:
        rows = db.query(ClosetItem).filter(ClosetItem.category.is_(None)).all()
        print(f"{len(rows)} items missing category")
        for row in rows:
            image_path = image_url_to_path(row.image_url)
            try:
                result = classify_item(image_path)
            except Exception as e:
                print(f"  [{row.id}] FAILED: {e}")
                continue

            row.category = result.get("category")
            row.attributes = json.dumps(result.get("attributes", {}), ensure_ascii=False)
            if not row.description:
                row.description = result.get("description")
            db.commit()
            print(f"  [{row.id}] {row.category} — {result.get('description')}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
