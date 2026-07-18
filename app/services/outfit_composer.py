import os
import uuid
from typing import List, Optional

from PIL import Image

OUTPUT_DIR = "outfit_output"
CELL_SIZE = (300, 300)
PADDING = 20
BG_COLOR = (245, 245, 245)  # light gray

os.makedirs(OUTPUT_DIR, exist_ok=True)


def _load_thumb(path: str, size) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.paste(img, (x, y), img)
    return canvas


def compose_outfit_image(
    tops: Optional[List[str]] = None,
    bottoms: Optional[List[str]] = None,
    outerwear: Optional[List[str]] = None,
    shoes: Optional[List[str]] = None,
    output_dir: str = OUTPUT_DIR,
) -> str:
    """Lay out item image paths into a grid: tops row, bottoms row, outerwear+shoes row."""
    tops = tops or []
    bottoms = bottoms or []
    outerwear = outerwear or []
    shoes = shoes or []

    rows = [row for row in (tops, bottoms, outerwear + shoes) if row]
    if not rows:
        raise ValueError("No items to compose")

    max_cols = max(len(row) for row in rows)
    width = max_cols * CELL_SIZE[0] + (max_cols + 1) * PADDING
    height = len(rows) * CELL_SIZE[1] + (len(rows) + 1) * PADDING

    canvas = Image.new("RGB", (width, height), BG_COLOR)

    for row_idx, row_paths in enumerate(rows):
        row_width = len(row_paths) * CELL_SIZE[0] + (len(row_paths) - 1) * PADDING
        start_x = (width - row_width) // 2
        y = PADDING + row_idx * (CELL_SIZE[1] + PADDING)
        for col_idx, path in enumerate(row_paths):
            thumb = _load_thumb(path, CELL_SIZE)
            x = start_x + col_idx * (CELL_SIZE[0] + PADDING)
            canvas.paste(thumb, (x, y), thumb)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{uuid.uuid4().hex}.png")
    canvas.save(out_path)
    return out_path
