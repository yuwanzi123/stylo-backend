import cv2
import os
import numpy as np
from PIL import Image
import clip
import torch
import shutil

# 配置
VIDEO_PATH = os.path.expanduser("~/stylo-backend/uploads/20260526_234138.mp4")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/test_output")
FPS_SAMPLE = 5
CHANGE_THRESHOLD = 0.08
MIN_SEGMENT_FRAMES = 3

# 清空输出目录
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR)

# 加载 CLIP
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading CLIP on {device}...")
model, preprocess = clip.load("ViT-B/32", device=device)


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
            frame_name = f"frame_{frame_count:04d}.jpg"
            frame_path = os.path.join(output_dir, frame_name)
            cv2.imwrite(frame_path, frame)
            saved_frames.append(frame_path)
        frame_count += 1
    cap.release()
    print(f"Extracted {len(saved_frames)} frames")
    return saved_frames


def get_embeddings(frame_paths):
    embeddings = []
    for i, path in enumerate(frame_paths):
        image = preprocess(Image.open(path)).unsqueeze(0).to(device)
        with torch.no_grad():
            embedding = model.encode_image(image)
            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
        embeddings.append(embedding.cpu().numpy()[0])
        if (i + 1) % 20 == 0:
            print(f"  Embedding {i+1}/{len(frame_paths)}...")
    return np.array(embeddings)


def split_by_timeline(frame_paths, embeddings, threshold=0.10):
    n = len(embeddings)

    # 计算相邻帧之间的差异
    diffs = []
    for i in range(n - 1):
        sim = np.dot(embeddings[i], embeddings[i + 1])
        diff = 1 - sim
        diffs.append(diff)

    # 平滑差异曲线（3帧滑动平均）
    smoothed_diffs = []
    for i in range(len(diffs)):
        start = max(0, i - 1)
        end = min(len(diffs), i + 2)
        smoothed_diffs.append(np.mean(diffs[start:end]))

    print(f"\n相邻帧差异统计：")
    print(f"  最小：{min(smoothed_diffs):.4f}")
    print(f"  最大：{max(smoothed_diffs):.4f}")
    print(f"  平均：{np.mean(smoothed_diffs):.4f}")
    print(f"  阈值：{threshold}")

    # 找切换点
    cut_points = [0]
    for i, diff in enumerate(smoothed_diffs):
        if diff > threshold:
            cut_points.append(i + 1)
    cut_points.append(n)

    print(f"\n找到 {len(cut_points) - 1} 个片段")

    # 每段取中间帧，过滤太短的片段
    representatives = []
    for i in range(len(cut_points) - 1):
        start = cut_points[i]
        end = cut_points[i + 1]
        segment_length = end - start

        if segment_length < MIN_SEGMENT_FRAMES:
            print(f"  片段{i+1}: 帧{start}-{end-1} ({segment_length}帧) → 跳过（过渡帧）")
            continue

        segment = list(range(start, end))
        mid = segment[len(segment) // 2]
        representatives.append(frame_paths[mid])
        print(f"  片段{i+1}: 帧{start}-{end-1} ({segment_length}帧) → {os.path.basename(frame_paths[mid])}")

    return representatives


# 主流程
frames_dir = os.path.join(OUTPUT_DIR, "frames")
os.makedirs(frames_dir, exist_ok=True)

print("Extracting frames...")
frame_paths = extract_frames(VIDEO_PATH, frames_dir, FPS_SAMPLE)

print("Generating embeddings...")
embeddings = get_embeddings(frame_paths)

print("\nSplitting by timeline...")
representatives = split_by_timeline(frame_paths, embeddings, threshold=CHANGE_THRESHOLD)

# 复制代表帧到输出目录
print(f"\nResult: {len(representatives)} unique items")
for i, rep in enumerate(representatives):
    dst = os.path.join(OUTPUT_DIR, f"item_{i+1:02d}_{os.path.basename(rep)}")
    shutil.copy(rep, dst)

# 删除 frames 文件夹
shutil.rmtree(frames_dir)

print("\nDone! Check ~/stylo-backend/test_output/")
