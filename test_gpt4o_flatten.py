import os
import base64
import requests
from PIL import Image
import io

API_KEY = "OPENAI_API_KEY"

INPUT_DIR = os.path.expanduser("~/stylo-backend/visual_output")
OUTPUT_DIR = os.path.expanduser("~/stylo-backend/gpt4o_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def image_to_base64(image_path):
    img_rgba = Image.open(image_path).convert("RGBA")
    white_bg = Image.new("RGBA", img_rgba.size, (255, 255, 255, 255))
    white_bg.paste(img_rgba, mask=img_rgba.split()[3])
    img_rgb = white_bg.convert("RGB")
    buffer = io.BytesIO()
    img_rgb.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def flatten_clothing(image_path, output_path):
    img_b64 = image_to_base64(image_path)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 第一步：GPT-4o 描述衣服
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    },
                    {
                        "type": "text",
                        "text": "Describe this clothing item in detail for a product photo recreation: exact colors, patterns, fabric texture, style, and type. Be very specific."
                    }
                ]
            }
        ],
        "max_tokens": 300
    }
    
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload
    )
    description = response.json()["choices"][0]["message"]["content"]
    print(f"  Description: {description[:150]}...")
    
    # 第二步：DALL-E 3 生成平铺图
    dalle_prompt = f"A flat lay product photo of: {description}. White background, no wrinkles, perfectly flat, studio lighting, e-commerce style."
    
    dalle_payload = {
        "model": "gpt-image-1",
        "prompt": dalle_prompt,
        "n": 1,
        "size": "1024x1024",
        "quality": "medium"
    }
    
    dalle_response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=headers,
        json=dalle_payload
    )
    #print(dalle_response.json())
    result_data = dalle_response.json()["data"][0]["b64_json"]
    img_bytes = base64.b64decode(result_data)
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    print(f"  Saved to {output_path}")

items = sorted([f for f in os.listdir(INPUT_DIR) if f.startswith("item_") and f.endswith(".png")])

for item in items:
    input_path = os.path.join(INPUT_DIR, item)
    output_path = os.path.join(OUTPUT_DIR, item.replace(".png", "_flat.png"))
    print(f"\nProcessing {item}...")
    flatten_clothing(input_path, output_path)

print("\nDone! Check ~/stylo-backend/gpt4o_output/")
