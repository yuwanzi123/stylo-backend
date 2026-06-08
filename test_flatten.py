import cv2
import numpy as np
import os
from PIL import Image

INPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/flatten_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def straighten_clothing(image_path):
    # 读取 PNG（带透明通道）
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img.shape[2] == 4:
        alpha = img[:, :, 3]
    else:
        return img
    
    # 找衣服轮廓
    contours, _ = cv2.findContours(alpha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img
    
    largest = max(contours, key=cv2.contourArea)
    
    # 最小外接矩形
    rect = cv2.minAreaRect(largest)
    angle = rect[2]
    
    # 旋转矫正
    if angle < -45:
        angle += 90
    
    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return rotated

items = sorted([f for f in os.listdir(INPUT_DIR) if f.startswith("item_") and f.endswith(".png")])

for item in items:
    input_path = os.path.join(INPUT_DIR, item)
    output_path = os.path.join(OUTPUT_DIR, item)
    print(f"Processing {item}...")
    result = straighten_clothing(input_path)
    cv2.imwrite(output_path, result)

print(f"\nDone! Check ~/stylo-backend/flatten_output/")
