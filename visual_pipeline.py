import cv2
import os
import numpy as np
import shutil
import time
from scipy.signal import find_peaks
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ultralytics import YOLO
from rembg import remove
import requests
import base64
import io
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

FPS_SAMPLE = 5
MIN_PEAK_DISTANCE = 5
YOLO_MODEL_PATH = os.path.expanduser("~/stylo-backend/deepfashion2_yolov8s-seg.pt")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


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


def color_histogram(image_path, bins=32, mask=None):
    img = cv2.imread(image_path)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_hist = cv2.calcHist([img_hsv], [0], mask, [bins], [0, 180])
    s_hist = cv2.calcHist([img_hsv], [1], mask, [bins], [0, 256])
    v_hist = cv2.calcHist([img_hsv], [2], mask, [bins], [0, 256])
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
    removed = len(frame_paths) - len(sharp_frames)
    print(f"Sharpness filter: {len(frame_paths)} → {len(sharp_frames)} frames ({removed} removed)")
    return sharp_frames


def get_crop_and_class(path, yolo):
    results = yolo(path, verbose=False)
    boxes = results[0].boxes
    if len(boxes) == 0:
        return None, None, None
    best_idx = max(range(len(boxes)), key=lambda i: float(boxes[i].conf[0]))
    best = boxes[best_idx]
    cls = yolo.names[int(best.cls[0])]
    x1, y1, x2, y2 = map(int, best.xyxy[0])
    img = cv2.imread(path)
    crop = img[y1:y2, x1:x2]
    crop_path = path.replace(".jpg", "_crop.jpg")
    cv2.imwrite(crop_path, crop)

    seg_mask = None
    seg_masks = results[0].masks
    if seg_masks is not None and best_idx < len(seg_masks):
        raw = seg_masks[best_idx].data[0].cpu().numpy()
        full_mask = cv2.resize(raw, (img.shape[1], img.shape[0]))
        seg_mask = (full_mask[y1:y2, x1:x2] > 0.5).astype(np.uint8) * 255

    return cls, crop_path, seg_mask


def find_stable_frames(frame_paths, output_dir, min_distance=10):
    print("Computing color histograms...")
    histograms = [color_histogram(p) for p in frame_paths]

    diffs = []
    for i in range(len(histograms) - 1):
        diffs.append(histogram_diff(histograms[i], histograms[i + 1]))

    smooth_window = 5
    smoothed_diffs = []
    for i in range(len(diffs)):
        start = max(0, i - smooth_window // 2)
        end = min(len(diffs), i + smooth_window // 2 + 1)
        smoothed_diffs.append(np.mean(diffs[start:end]))

    inverted = [-d for d in smoothed_diffs]
    valleys, _ = find_peaks(inverted, distance=min_distance)

    plt.figure(figsize=(16, 4))
    plt.plot(smoothed_diffs, label='smoothed diff')
    plt.scatter(valleys, [smoothed_diffs[v] for v in valleys],
                color='green', zorder=5, label='stable moments')
    plt.xlabel('Frame index')
    plt.ylabel('Color difference')
    plt.title('Stable moments (valley detection)')
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'diff_curve.png'))
    plt.close()

    yolo = YOLO(YOLO_MODEL_PATH)
    mean_diff = np.mean(smoothed_diffs)
    valleys = [v for v in valleys if smoothed_diffs[v] < mean_diff]
    print(f"After mean filter: {len(valleys)} stable moments remaining")
    candidates = [frame_paths[v] for v in valleys]

    filtered = [candidates[0]] if candidates else []
    for curr in candidates[1:]:
        last = filtered[-1]
        last_cls, last_crop, last_mask = get_crop_and_class(last, yolo)
        curr_cls, curr_crop, curr_mask = get_crop_and_class(curr, yolo)

        if last_crop and curr_crop:
            color_diff = histogram_diff(
                color_histogram(last_crop, mask=last_mask),
                color_histogram(curr_crop, mask=curr_mask),
            )
        else:
            color_diff = 1.0

        if color_diff < 0.10:
            print(f"  Merge: {os.path.basename(curr)}")
        else:
            filtered.append(curr)

    early_frames = frame_paths[:10]
    best_early = max(early_frames, key=sharpness)
    if best_early not in filtered:
        filtered.insert(0, best_early)

    kept = set(filtered)
    frames_dir = os.path.dirname(frame_paths[0])
    for fname in os.listdir(frames_dir):
        fpath = os.path.join(frames_dir, fname)
        if os.path.isfile(fpath) and fpath not in kept:
            os.remove(fpath)

    return filtered


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        requests.exceptions.SSLError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    )),
    reraise=True,
)
def _post_with_retry(url, headers, json_payload):
    response = requests.post(url, headers=headers, json=json_payload, timeout=60)
    response.raise_for_status()
    return response


def flatten_with_gpt(image_path, output_path):
    with open(image_path, "rb") as f:
        rembg_result = remove(f.read())

    img_rgba = Image.open(io.BytesIO(rembg_result)).convert("RGBA")
    white_bg = Image.new("RGBA", img_rgba.size, (255, 255, 255, 255))
    white_bg.paste(img_rgba, mask=img_rgba.split()[3])
    img_rgb = white_bg.convert("RGB")

    # gamma correction to compensate for dark wardrobe lighting
    img_cv = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)
    lut = np.array([((i / 255.0) ** 0.75) * 255 for i in range(256)], dtype=np.uint8)
    img_cv = cv2.LUT(img_cv, lut)
    img_rgb = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))

    buffer = io.BytesIO()
    img_rgb.save(buffer, format="JPEG")
    img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": "There may be multiple clothing items visible in this image. Focus ONLY on the single most prominent foreground item — ignore anything partially visible behind or beside it. Describe it in extreme detail for exact product photo recreation. Include: exact colors (be precise — distinguish navy blue from black, teal from blue, etc.), fabric texture, garment type. Pay special attention to structural features: hood presence, collar type, pocket style and position, zipper placement and color, sleeve style, cuff design, waistband and hem. Ignore hangers, tags, and background."}
            ]
        }],
        "max_tokens": 300
    }

    response = _post_with_retry("https://api.openai.com/v1/chat/completions", headers=headers, json_payload=payload)
    description = response.json()["choices"][0]["message"]["content"]
    print(f"  Description: {description[:100]}...")

    dalle_prompt = f"A flat lay product photo of: {description}. White background, no wrinkles, perfectly flat, studio lighting, e-commerce style."
    dalle_payload = {
        "model": "gpt-image-1",
        "prompt": dalle_prompt,
        "n": 1,
        "size": "1024x1024",
        "quality": "medium"
    }

    dalle_response = _post_with_retry("https://api.openai.com/v1/images/generations", headers=headers, json_payload=dalle_payload)
    result_data = dalle_response.json()["data"][0]["b64_json"]
    img_bytes = base64.b64decode(result_data)

    with open(output_path, "wb") as f:
        f.write(img_bytes)


def run_pipeline(video_path: str, output_dir: str = None) -> list[str]:
    if output_dir is None:
        output_dir = os.path.expanduser("~/stylo-backend/visual_output")

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    pipeline_start = time.time()
    timings = {}

    print("Extracting frames...")
    t = time.time()
    frame_paths = extract_frames(video_path, frames_dir, FPS_SAMPLE)
    timings["extract_frames"] = time.time() - t

    print("Filtering blurry frames...")
    t = time.time()
    frame_paths = filter_blurry_frames(frame_paths, percentile=25)
    timings["filter_blurry"] = time.time() - t

    print("Finding stable frames...")
    t = time.time()
    representatives = find_stable_frames(frame_paths, output_dir, min_distance=MIN_PEAK_DISTANCE)
    timings["find_stable_frames"] = time.time() - t

    print(f"\nResult: {len(representatives)} unique items")
    yolo = YOLO(YOLO_MODEL_PATH)
    output_paths = []
    t = time.time()
    for i, rep in enumerate(representatives):
        _, crop_path, _ = get_crop_and_class(rep, yolo)
        src = crop_path if crop_path and os.path.exists(crop_path) else rep
        dst = os.path.join(output_dir, f"item_{i+1:02d}.png")
        with open(src, "rb") as f:
            removed = remove(f.read())
        Image.open(io.BytesIO(removed)).save(dst)
        print(f"  Saved: {os.path.basename(dst)}")
    timings["crop_and_rembg"] = time.time() - t

    print("\nFlattening with GPT...")
    t = time.time()
    for i, rep in enumerate(representatives):
        _, crop_path, _ = get_crop_and_class(rep, yolo)
        src = crop_path if crop_path and os.path.exists(crop_path) else rep
        flat_dst = os.path.join(output_dir, f"item_{i+1:02d}_flat.png")
        flatten_with_gpt(src, flat_dst)
        print(f"  Flattened: {os.path.basename(flat_dst)}")
        output_paths.append(flat_dst)
    timings["gpt_flatten"] = time.time() - t

    timings["total"] = time.time() - pipeline_start

    print("\n--- Timing ---")
    for step, secs in timings.items():
        print(f"  {step:<22} {secs:.1f}s")

    shutil.rmtree(frames_dir)
    print("Done!")
    return output_paths


def run_pipeline_image(image_path: str, output_dir: str = None) -> list[str]:
    if output_dir is None:
        output_dir = os.path.expanduser("~/stylo-backend/visual_output")

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    yolo = YOLO(YOLO_MODEL_PATH)
    _, crop_path, _ = get_crop_and_class(image_path, yolo)
    src = crop_path if crop_path and os.path.exists(crop_path) else image_path

    dst = os.path.join(output_dir, "item_01.png")
    with open(src, "rb") as f:
        removed = remove(f.read())
    Image.open(io.BytesIO(removed)).save(dst)

    flat_dst = os.path.join(output_dir, "item_01_flat.png")
    flatten_with_gpt(src, flat_dst)
    print(f"  Flattened: {os.path.basename(flat_dst)}")

    return [flat_dst]
