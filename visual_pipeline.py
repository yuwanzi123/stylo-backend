import cv2
import os
import numpy as np
import shutil
from scipy.signal import find_peaks
import matplotlib.pyplot as plt

# 配置
VIDEO_PATH = os.path.expanduser("~/stylo-backend/uploads/20260526_234138.mp4")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
FPS_SAMPLE = 5
MIN_PEAK_DISTANCE = 10  # 两个低谷之间至少间隔几帧

# 清空输出目录
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR)


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


def color_histogram(image_path, bins=32):
    img = cv2.imread(image_path)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_hist = cv2.calcHist([img_hsv], [0], None, [bins], [0, 180])
    s_hist = cv2.calcHist([img_hsv], [1], None, [bins], [0, 256])
    v_hist = cv2.calcHist([img_hsv], [2], None, [bins], [0, 256])
    hist = np.concatenate([h_hist, s_hist, v_hist]).flatten()
    hist = hist / (hist.sum() + 1e-7)
    return hist


def histogram_diff(hist1, hist2):
    return cv2.compareHist(
        hist1.astype(np.float32),
        hist2.astype(np.float32),
        cv2.HISTCMP_BHATTACHARYYA
    )


def sharpness(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    return cv2.Laplacian(img, cv2.CV_64F).var()

def filter_blurry_frames(frame_paths, percentile=25):
    scores = [sharpness(p) for p in frame_paths]
    threshold = np.percentile(scores, percentile)
    sharp_frames = [p for p, s in zip(frame_paths, scores) if s >= threshold]
    print(f"Sharpness threshold (p{percentile}): {threshold:.1f}")
    print(f"Sharpness filter: {len(frame_paths)} → {len(sharp_frames)} frames")
    return sharp_frames

def find_stable_frames(frame_paths, min_distance=10):
    print("Computing color histograms...")
    histograms = [color_histogram(p) for p in frame_paths]

    # 计算相邻帧颜色差异
    diffs = []
    for i in range(len(histograms) - 1):
        diff = histogram_diff(histograms[i], histograms[i + 1])
        diffs.append(diff)

    # 平滑（3帧滑动平均）
    smooth_window = 5
    smoothed_diffs = []
    for i in range(len(diffs)):
        start = max(0, i - smooth_window // 2)
        end = min(len(diffs), i + smooth_window // 2 + 1)
        smoothed_diffs.append(np.mean(diffs[start:end]))


    print(f"\n颜色差异统计：")
    print(f"  最小：{min(smoothed_diffs):.4f}")
    print(f"  最大：{max(smoothed_diffs):.4f}")
    print(f"  平均：{np.mean(smoothed_diffs):.4f}")

    # 找局部最低点（反转曲线找峰值）
    inverted = [-d for d in smoothed_diffs]
    valleys, _ = find_peaks(inverted, distance=min_distance)

    print(f"\n找到 {len(valleys)} 个稳定时刻：")
    for v in valleys:
        print(f"  帧{v} ({os.path.basename(frame_paths[v])}) 差异={smoothed_diffs[v]:.4f}")

    # 画曲线
    plt.figure(figsize=(16, 4))
    plt.plot(smoothed_diffs, label='smoothed diff')
    plt.scatter(valleys, [smoothed_diffs[v] for v in valleys],
                color='green', zorder=5, label='stable moments')
    plt.xlabel('Frame index')
    plt.ylabel('Color difference')
    plt.title('Stable moments (valley detection)')
    plt.legend()
    plt.savefig(os.path.join(OUTPUT_DIR, 'diff_curve.png'))
    plt.close()
    print("Diff curve saved.")

    return [frame_paths[v] for v in valleys]


# 主流程
frames_dir = os.path.join(OUTPUT_DIR, "frames")
os.makedirs(frames_dir, exist_ok=True)

print("Extracting frames...")
frame_paths = extract_frames(VIDEO_PATH, frames_dir, FPS_SAMPLE)

print("Filtering blurry frames...")

frame_paths = filter_blurry_frames(frame_paths, percentile=25)

print("Finding stable frames...")
representatives = find_stable_frames(frame_paths, min_distance=MIN_PEAK_DISTANCE)

print(f"\nResult: {len(representatives)} unique items")
for i, rep in enumerate(representatives):
    dst = os.path.join(OUTPUT_DIR, f"item_{i+1:02d}_{os.path.basename(rep)}")
    shutil.copy(rep, dst)

shutil.rmtree(frames_dir)
print("\nDone! Check ~/stylo-backend/visual_output/")
