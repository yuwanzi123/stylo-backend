import torch
from diffusers import StableDiffusionControlNetPipeline, ControlNetModel, UniPCMultistepScheduler
from controlnet_aux import OpenposeDetector
from PIL import Image
import os
import numpy as np
import cv2

INPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/controlnet_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

print("Loading ControlNet model...")
controlnet = ControlNetModel.from_pretrained(
    "lllyasviel/sd-controlnet-canny",
    torch_dtype=torch.float16
).to(device)

pipe = StableDiffusionControlNetPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    controlnet=controlnet,
    torch_dtype=torch.float16,
).to(device)
pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)

prompt = "a flat lay clothing item on white background, product photo, no wrinkles, studio lighting"
negative_prompt = "wrinkles, creases, shadow, dark background, hanger, mannequin, person"

items = sorted([f for f in os.listdir(INPUT_DIR) if f.startswith("item_") and f.endswith(".png")])

for item in items[:3]:
    input_path = os.path.join(INPUT_DIR, item)
    output_path = os.path.join(OUTPUT_DIR, item)
    print(f"Processing {item}...")

    # 白色背景
    img_rgba = Image.open(input_path).convert("RGBA")
    white_bg = Image.new("RGBA", img_rgba.size, (255, 255, 255, 255))
    white_bg.paste(img_rgba, mask=img_rgba.split()[3])
    img_rgb = white_bg.convert("RGB").resize((512, 512))

    # Canny 边缘检测作为 ControlNet 输入
    img_np = np.array(img_rgb)
    canny = cv2.Canny(img_np, 100, 200)
    canny_img = Image.fromarray(canny).convert("RGB")

    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        image=canny_img,
        num_inference_steps=30,
        guidance_scale=7.5,
    ).images[0]

    result.save(output_path)
    print(f"  Saved.")

print("\nDone! Check ~/stylo-backend/controlnet_output/")
