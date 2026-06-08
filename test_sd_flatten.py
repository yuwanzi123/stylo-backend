import torch
from diffusers import StableDiffusionImg2ImgPipeline
from PIL import Image
import os

INPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/sd_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

print("Loading SD model...")
pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
).to(device)

prompt = "flat lay clothing product photo, white background, no wrinkles, studio lighting, clean"
negative_prompt = "wrinkles, shadow, dark, messy, hanger, background"

items = sorted([f for f in os.listdir(INPUT_DIR) if f.startswith("item_") and f.endswith(".png")])

for item in items[:3]:  # 先测试前3张
    input_path = os.path.join(INPUT_DIR, item)
    output_path = os.path.join(OUTPUT_DIR, item)
    
    print(f"Processing {item}...")
    img = Image.open(input_path).convert("RGB").resize((512, 512))
    
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        image=img,
        strength=0.3,
        guidance_scale=7.5,
    ).images[0]
    
    result.save(output_path)
    print(f"  Saved to {output_path}")

print("\nDone! Check ~/stylo-backend/sd_output/")
