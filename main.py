import os
import shutil
import base64
import uuid
from enum import Enum
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from visual_pipeline import run_pipeline, run_pipeline_image

app = FastAPI()


class TaskStatus(str, Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    media_type: Optional[str] = None   # "video" or "image"
    item_count: Optional[int] = None
    images: Optional[list] = None
    error: Optional[str] = None


tasks: dict[str, TaskResult] = {}

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "visual_output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/images", StaticFiles(directory=OUTPUT_DIR), name="images")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def process_media_task(task_id: str, media_path: str, media_type: str, output_dir: str):
    try:
        if media_type == "video":
            output_paths = run_pipeline(media_path, output_dir=output_dir)
        else:
            output_paths = run_pipeline_image(media_path, output_dir=output_dir)

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


@app.get("/")
def root():
    return {"status": "Stylo backend running"}
