import cv2
import os
from ultralytics import YOLO

model = YOLO("deepfashion2_yolov8s-seg.pt")

output_dir = os.path.expanduser("~/stylo-backend/visual_output")
items = sorted([f for f in os.listdir(output_dir) if f.startswith("item_")])

for item in items:
    path = os.path.join(output_dir, item)
    results = model(path, verbose=False)
    boxes = results[0].boxes
    print(f"{item}: {len(boxes)} detections")
    for box in boxes:
        cls = int(box.cls[0])
        conf = float(box.conf[0])
        name = model.names[cls]
        print(f"  → {name} ({conf:.2f})")

