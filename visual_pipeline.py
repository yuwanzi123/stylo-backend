import cv2
import os
import numpy as np
import shutil

# 配置
VIDEO_PATH = os.path.expanduser("~/stylo-backend/uploads/20260526_234138.mp4")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
FPS_SAMPLE = 5
CHANGE_THRESHOLD = 0.05  # 颜色差异阈值
MIN_SEGMENT_FRAMES = 5   # 最短片段帧数

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
    """计算图片的颜色直方图，返回归一化向量"""
    img = cv2.imread(image_path)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # 分别计算 H、S、V 三个通道的直方图
    h_hist = cv2.calcHist([img_hsv], [0], None, [bins], [0, 180])
    s_hist = cv2.calcHist([img_hsv], [1], None, [bins], [0, 256])
    v_hist = cv2.calcHist([img_hsv], [2], None, [bins], [0, 256])
    
    # 拼接并归一化
    hist = np.concatenate([h_hist, s_hist, v_hist]).flatten()
    hist = hist / (hist.sum() + 1e-7)
    return hist


def histogram_diff(hist1, hist2):
    """计算两个直方图的差异，0=完全相同，1=完全不同"""
    return cv2.compareHist(
        hist1.astype(np.float32),
        hist2.astype(np.float32),
        cv2.HISTCMP_BHATTACHARYYA  # Bhattacharyya距离，对颜色分布比较效果好
    )


def sharpness(image_path):
    """计算图片清晰度"""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    return cv2.Laplacian(img, cv2.CV_64F).var()


def split_by_color_timeline(frame_paths, threshold=0.15):
    print("Computing color histograms...")
    histograms = [color_histogram(p) for p in frame_paths]

    # 计算相邻帧颜色差异
    diffs = []
    for i in range(len(histograms) - 1):
        diff = histogram_diff(histograms[i], histograms[i + 1])
        diffs.append(diff)

    # 平滑（3帧滑动平均）
    smoothed_diffs = []
    for i in range(len(diffs)):
        start = max(0, i - 1)
        end = min(len(diffs), i + 2)
        smoothed_diffs.append(np.mean(diffs[start:end]))

    print(f"\n颜色差异统计：")
    print(f"  最小：{min(smoothed_diffs):.4f}")
    print(f"  最大：{max(smoothed_diffs):.4f}")
    print(f"  平均：{np.mean(smoothed_diffs):.4f}")
    print(f"  阈值：{threshold}")

    # 找切换点
    cut_points = [0]
    for i, diff in enumerate(smoothed_diffs):
        if diff > threshold:
            cut_points.append(i + 1)
    cut_points.append(len(frame_paths))

    print(f"\n找到 {len(cut_points) - 1} 个片段")

    # 每段过滤短片段，选清晰度最高的帧
    representatives = []
    for i in range(len(cut_points) - 1):
        start = cut_points[i]
        end = cut_points[i + 1]
        segment_length = end - start

        if segment_length < MIN_SEGMENT_FRAMES:
            print(f"  片段{i+1}: 帧{start}-{end-1} ({segment_length}帧) → 跳过")
            continue

        segment = list(range(start, end))
        best = max(segment, key=lambda idx: sharpness(frame_paths[idx]))
        representatives.append(frame_paths[best])
        print(f"  片段{i+1}: 帧{start}-{end-1} ({segment_length}帧) → {os.path.basename(frame_paths[best])}")

    # 画差异曲线
    import matplotlib.pyplot as plt
    plt.figure(figsize=(16, 4))
    plt.plot(smoothed_diffs, label='smoothed diff')
    plt.axhline(y=threshold, color='r', linestyle='--', label=f'threshold={threshold}')
    plt.xlabel('Frame index')
    plt.ylabel('Color difference')
    plt.title('Color difference over time')
    plt.legend()
    plt.savefig(os.path.join(OUTPUT_DIR, 'diff_curve.png'))
    plt.close()
    print("Diff curve saved to diff_curve.png")

    return representatives


# 主流程
frames_dir = os.path.join(OUTPUT_DIR, "frames")
os.makedirs(frames_dir, exist_ok=True)

print("Extracting frames...")
frame_paths = extract_frames(VIDEO_PATH, frames_dir, FPS_SAMPLE)

print("Splitting by color timeline...")
representatives = split_by_color_timeline(frame_paths, threshold=CHANGE_THRESHOLD)

print(f"\nResult: {len(representatives)} unique items")
for i, rep in enumerate(representatives):
    dst = os.path.join(OUTPUT_DIR, f"item_{i+1:02d}_{os.path.basename(rep)}")
    shutil.copy(rep, dst)

shutil.rmtree(frames_dir)
print("\nDone! Check ~/stylo-backend/visual_output/")
