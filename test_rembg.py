import os
from rembg import remove
from PIL import Image

INPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/rembg_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

items = sorted([f for f in os.listdir(INPUT_DIR) if f.startswith("item_")])

for item in items:
    input_path = os.path.join(INPUT_DIR, item)
    output_path = os.path.join(OUTPUT_DIR, item.replace(".jpg", ".png"))
    
    print(f"Processing {item}...")
    with open(input_path, "rb") as f:
        result = remove(f.read())
    
    with open(output_path, "wb") as f:
        f.write(result)

print(f"\nDone! Check ~/stylo-backend/rembg_output/")
