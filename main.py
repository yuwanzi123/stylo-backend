import cv2
import os
import shutil
import numpy as np
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import Image
from datetime import datetime
import clip
import torch
from sklearn.metrics.pairwise import cosine_similarity

app = FastAPI()

UPLOAD_DIR = "uploads"
FRAMES_DIR = "frames"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"
model, preprocess = clip.load("ViT-B/32", device=device)
print(f"CLIP loaded on {device}")


def extract_frames(video_path, output_dir, fps_sample=5):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = max(1, int(fps // fps_sample))
    frame_count = 0
    saved_frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count % frame_interval == 0:
            frame_name = f"frame_{frame_count}.jpg"
            frame_path = os.path.join(output_dir, frame_name)
            cv2.imwrite(frame_path, frame)
            saved_frames.append(frame_path)
        frame_count += 1
    cap.release()
    return saved_frames


def sharpness(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    return cv2.Laplacian(img, cv2.CV_64F).var()


def get_embeddings(frame_paths):
    embeddings = []
    for path in frame_paths:
        image = preprocess(Image.open(path)).unsqueeze(0).to(device)
        with torch.no_grad():
            embedding = model.encode_image(image)
            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
        embeddings.append(embedding.cpu().numpy()[0])
    return np.array(embeddings)


def deduplicate(frame_paths, embeddings, threshold=0.80):
    sim_matrix = cosine_similarity(embeddings)
    n = len(frame_paths)
    used = [False] * n
    groups = []

    for i in range(n):
        if used[i]:
            continue
        group = [i]
        for j in range(i + 1, n):
            if not used[j] and sim_matrix[i][j] > threshold:
                group.append(j)
                used[j] = True
        used[i] = True
        groups.append(group)

    representatives = []
    for group in groups:
        best = max(group, key=lambda i: sharpness(frame_paths[i]))
        representatives.append(frame_paths[best])

    # 删除非代表帧
    representative_set = set(representatives)
    for path in frame_paths:
        if path not in representative_set:
            try:
                os.remove(path)
            except:
                pass

    return representatives, groups


@app.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    video_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"{UPLOAD_DIR}/{video_id}.mp4"

    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    video_frames_dir = os.path.join(FRAMES_DIR, video_id)
    os.makedirs(video_frames_dir, exist_ok=True)

    frame_paths = extract_frames(video_path, video_frames_dir, fps_sample=5)
    print(f"Extracted {len(frame_paths)} frames")

    embeddings = get_embeddings(frame_paths)
    unique_frames, groups = deduplicate(frame_paths, embeddings, threshold=0.80)
    print(f"After dedup: {len(unique_frames)} unique items")

    return JSONResponse({
        "video_id": video_id,
        "frames_extracted": len(frame_paths),
        "unique_items": len(unique_frames),
        "unique_frames": [os.path.basename(f) for f in unique_frames],
        "groups": [[os.path.basename(frame_paths[i]) for i in g] for g in groups]
    })


@app.get("/")
def root():
    return {"status": "Stylo backend running"}
