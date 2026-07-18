import os
import shutil
import base64
import json
import uuid
import threading
from enum import Enum
from datetime import datetime
from typing import Optional, Dict
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from visual_pipeline import run_pipeline, run_pipeline_image
from models import SessionLocal, ClosetItem, ChatMessage, Outfit, init_db
from app.services.item_classifier import classify_item
from app.services.outfit_recommender import recommend

app = FastAPI()

@app.on_event("startup")
def startup():
    init_db()


class TaskStatus(str, Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    media_type: Optional[str] = None   # "video" or "image"
    current_step: Optional[str] = None  # "processing_media" | "detecting_items" | "generating_images"
    item_count: Optional[int] = None
    images: Optional[list] = None
    error: Optional[str] = None


tasks: dict[str, TaskResult] = {}


class EditSession:
    def __init__(self, item_id: int, original_image_path: str, original_description: str):
        self.item_id = item_id
        self.original_image_path = original_image_path
        self.original_description = original_description
        self.candidate_versions: list[str] = []  # file paths, max 2


edit_sessions: Dict[str, EditSession] = {}
edit_sessions_lock = threading.Lock()

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "visual_output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/images", StaticFiles(directory=OUTPUT_DIR), name="images")

OUTFIT_OUTPUT_DIR = "outfit_output"
os.makedirs(OUTFIT_OUTPUT_DIR, exist_ok=True)
app.mount("/outfit-images", StaticFiles(directory=OUTFIT_OUTPUT_DIR), name="outfit_images")


def image_url_to_path(image_url: str) -> str:
    # image_url is like "/images/<task_id>/<filename>", map to actual path on disk.
    # StaticFiles serves OUTPUT_DIR as /images.
    prefix = "/images/"
    relative = image_url[len(prefix):] if image_url.startswith(prefix) else image_url.lstrip("/")
    return os.path.join(OUTPUT_DIR, relative)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def process_media_task(task_id: str, media_path: str, media_type: str, output_dir: str):
    def step_callback(step: str):
        tasks[task_id] = TaskResult(
            task_id=task_id,
            status=TaskStatus.processing,
            media_type=media_type,
            current_step=step,
        )

    step_callback("processing_media")
    try:
        if media_type == "video":
            output_paths = run_pipeline(media_path, output_dir=output_dir, on_step_change=step_callback)
        else:
            output_paths = run_pipeline_image(media_path, output_dir=output_dir, on_step_change=step_callback)

        images = []
        for path in output_paths:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            filename = os.path.basename(path)
            images.append({
                "filename": filename,
                "b64": b64,
                "url": f"/images/{task_id}/{filename}",
            })

        tasks[task_id] = TaskResult(
            task_id=task_id,
            status=TaskStatus.completed,
            media_type=media_type,
            item_count=len(images),
            images=images,
        )
    except Exception as e:
        tasks[task_id] = TaskResult(
            task_id=task_id,
            status=TaskStatus.failed,
            media_type=media_type,
            error=str(e),
        )


@app.post("/upload")
async def upload(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext in VIDEO_EXTENSIONS:
        media_type = "video"
    elif ext in IMAGE_EXTENSIONS:
        media_type = "image"
    else:
        return JSONResponse({"error": f"Unsupported file type: {ext}"}, status_code=400)

    task_id = uuid.uuid4().hex
    suffix = ext if media_type == "video" else ext
    media_path = os.path.join(UPLOAD_DIR, f"{task_id}{suffix}")

    with open(media_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    output_dir = os.path.join(OUTPUT_DIR, task_id)
    tasks[task_id] = TaskResult(
        task_id=task_id,
        status=TaskStatus.processing,
        media_type=media_type,
    )

    background_tasks.add_task(process_media_task, task_id, media_path, media_type, output_dir)

    return JSONResponse({"task_id": task_id, "status": "processing"}, status_code=202)


@app.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    video_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = os.path.join(UPLOAD_DIR, f"{video_id}.mp4")

    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    output_dir = os.path.join(OUTPUT_DIR, video_id)
    output_paths = run_pipeline(video_path, output_dir=output_dir)

    images = []
    for path in output_paths:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        filename = os.path.basename(path)
        images.append({
            "filename": filename,
            "b64": b64,
            "url": f"/images/{video_id}/{filename}"
        })

    return JSONResponse({
        "video_id": video_id,
        "item_count": len(images),
        "images": images
    })


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    task = tasks.get(task_id)
    if task is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(task.model_dump())


class ClosetItemIn(BaseModel):
    filename: str
    image_url: str
    description: Optional[str] = None
    source_task_id: Optional[str] = None

class ClosetItemsRequest(BaseModel):
    items: list[ClosetItemIn]


@app.post("/closet/items")
def create_closet_items(body: ClosetItemsRequest):
    db = SessionLocal()
    try:
        created = []
        for item in body.items:
            row = ClosetItem(
                filename=item.filename,
                image_url=item.image_url,
                description=item.description,
                source_task_id=item.source_task_id,
            )

            try:
                image_path = image_url_to_path(item.image_url)
                classification = classify_item(image_path)
                row.category = classification.get("category")
                row.attributes = json.dumps(classification.get("attributes", {}), ensure_ascii=False)
                if not row.description:
                    row.description = classification.get("description")
            except Exception as e:
                print(f"classify_item failed for {item.image_url}: {e}")

            db.add(row)
            db.flush()  # 让数据库分配 id，但还没 commit
            created.append({
                "id": row.id,
                "filename": row.filename,
                "image_url": row.image_url,
                "description": row.description,
                "category": row.category,
                "attributes": row.attributes,
                "source_task_id": row.source_task_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        db.commit()
        return JSONResponse({"items": created}, status_code=201)
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/closet/items")
def list_closet_items():
    db = SessionLocal()
    try:
        rows = db.query(ClosetItem).order_by(ClosetItem.created_at.desc()).all()
        return JSONResponse({
            "items": [
                {
                    "id": r.id,
                    "filename": r.filename,
                    "image_url": r.image_url,
                    "description": r.description,
                    "category": r.category,
                    "attributes": r.attributes,
                    "source_task_id": r.source_task_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        })
    finally:
        db.close()


@app.delete("/closet/items/{item_id}")
def delete_closet_item(item_id: int):
    db = SessionLocal()
    try:
        row = db.query(ClosetItem).filter(ClosetItem.id == item_id).first()
        if row is None:
            return JSONResponse({"error": "Item not found"}, status_code=404)
        db.delete(row)
        db.commit()
        return JSONResponse({"deleted_id": item_id})
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.post("/closet/items/{item_id}/edit/start")
def edit_start(item_id: int):
    db = SessionLocal()
    try:
        row = db.query(ClosetItem).filter(ClosetItem.id == item_id).first()
        if row is None:
            return JSONResponse({"error": "Item not found"}, status_code=404)

        original_image_path = image_url_to_path(row.image_url)

        session_id = uuid.uuid4().hex
        session = EditSession(
            item_id=item_id,
            original_image_path=original_image_path,
            original_description=row.description or "",
        )
        with edit_sessions_lock:
            edit_sessions[session_id] = session

        return JSONResponse({"session_id": session_id, "item_id": item_id})
    finally:
        db.close()


def _outfit_to_response(db, outfit: Outfit) -> dict:
    item_ids = json.loads(outfit.item_ids)
    items = db.query(ClosetItem).filter(ClosetItem.id.in_(item_ids)).all()
    items_by_id = {it.id: it for it in items}
    ordered_items = [items_by_id[iid] for iid in item_ids if iid in items_by_id]
    return {
        "outfit_id": outfit.id,
        "caption": outfit.caption,
        "composite_image_url": f"/outfit-images/{os.path.basename(outfit.composite_image_path)}",
        "items": [
            {
                "id": it.id,
                "image_url": it.image_url,
                "category": it.category,
                "description": it.description,
            }
            for it in ordered_items
        ],
    }


class ChatMessageIn(BaseModel):
    user_id: str
    text: str


@app.post("/chat/message")
def post_chat_message(body: ChatMessageIn):
    db = SessionLocal()
    try:
        user_msg = ChatMessage(
            user_id=body.user_id,
            role="user",
            message_type="text",
            content=body.text,
        )
        db.add(user_msg)
        db.commit()

        try:
            outfit = recommend(db, body.user_id, body.text)
        except Exception as e:
            error_msg = ChatMessage(
                user_id=body.user_id,
                role="assistant",
                message_type="text",
                content=f"抱歉，生成搭配失败：{e}",
            )
            db.add(error_msg)
            db.commit()
            return JSONResponse({"error": str(e)}, status_code=500)

        outfit_data = _outfit_to_response(db, outfit)

        assistant_msg = ChatMessage(
            user_id=body.user_id,
            role="assistant",
            message_type="outfit_card",
            content=outfit.caption,
            outfit_id=outfit.id,
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(assistant_msg)

        return JSONResponse({
            "message_id": assistant_msg.id,
            "type": assistant_msg.message_type,
            **outfit_data,
        })
    finally:
        db.close()


@app.get("/chat/history")
def get_chat_history(user_id: str):
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        messages = []
        for m in rows:
            entry = {
                "message_id": m.id,
                "role": m.role,
                "type": m.message_type,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            if m.message_type == "outfit_card" and m.outfit_id:
                outfit = db.query(Outfit).filter(Outfit.id == m.outfit_id).first()
                if outfit:
                    entry.update(_outfit_to_response(db, outfit))
            messages.append(entry)
        return JSONResponse({"messages": messages})
    finally:
        db.close()


@app.get("/")
def root():
    return {"status": "Stylo backend running"}
