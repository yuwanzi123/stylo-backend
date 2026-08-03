"""POC: composite a mannequin outfit image from individual garment photos.

Standalone script, not wired into the main pipeline.

Usage:
    python poc_mannequin_outfit.py --images jacket.png tshirt.png jeans.png shoes.png
"""

import argparse
import base64
import mimetypes
import os
import sys
from contextlib import ExitStack
from datetime import datetime

import requests

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poc_output")
IMAGE_EDIT_URL = "https://api.openai.com/v1/images/edits"
IMAGE_SIZE = "1024x1536"

MANNEQUIN_PROMPT = (
    "Composite these garments onto a single department-store window mannequin, "
    "standing pose, plain simple background, soft even studio lighting. "
    "Layer the garments in natural wearing order: outerwear on the outside, "
    "the top layer underneath it, bottoms aligned at the waistline. "
    "The mannequin has no face and no facial features, no skin texture detail — "
    "commercial mannequin material quality, photorealistic product photography."
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Composite multiple garment images into a mannequin outfit shot (POC)"
    )
    parser.add_argument(
        "--images",
        nargs="+",
        required=True,
        help="Paths to garment images, space-separated, e.g.: jacket.png tshirt.png jeans.png shoes.png",
    )
    return parser.parse_args()


def validate_image_paths(paths):
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        print("Error: the following image paths do not exist:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


def call_mannequin_edit(image_paths, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "model": "gpt-image-1",
        "prompt": MANNEQUIN_PROMPT,
        "size": IMAGE_SIZE,
        "n": 1,
    }

    with ExitStack() as stack:
        files = []
        for path in image_paths:
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            fh = stack.enter_context(open(path, "rb"))
            files.append(("image[]", (os.path.basename(path), fh, mime)))

        response = requests.post(
            IMAGE_EDIT_URL, headers=headers, data=data, files=files, timeout=180
        )

    if not response.ok:
        print(f"Error: API call failed with status {response.status_code}", file=sys.stderr)
        print(f"Response body: {response.text}", file=sys.stderr)
        response.raise_for_status()

    return response.json()


def save_result(result, output_dir, timestamp):
    b64_data = result["data"][0]["b64_json"]
    image_bytes = base64.b64decode(b64_data)

    output_path = os.path.join(output_dir, f"mannequin_{timestamp}.png")
    with open(output_path, "wb") as f:
        f.write(image_bytes)

    return output_path


def main():
    args = parse_args()
    validate_image_paths(args.images)
    output_dir = ensure_output_dir()

    print(f"Input images ({len(args.images)}):")
    for p in args.images:
        print(f"  - {p}")
    print(f"Output directory: {output_dir}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Run timestamp: {timestamp}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: environment variable OPENAI_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    print("Calling gpt-image-1 images.edit API...")
    try:
        result = call_mannequin_edit(args.images, api_key)
    except requests.exceptions.RequestException as e:
        print(f"Error: API call failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("API call succeeded.")

    try:
        output_path = save_result(result, output_dir, timestamp)
    except (KeyError, IndexError) as e:
        print(f"Error: unexpected API response shape: {e}", file=sys.stderr)
        print(f"Raw response: {result}", file=sys.stderr)
        sys.exit(1)

    print(f"Saved result to: {output_path}")


if __name__ == "__main__":
    main()
