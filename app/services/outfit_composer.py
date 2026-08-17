import io
import os
import uuid
from typing import List, Optional

from PIL import Image
from rembg import remove

from app.services.llm_client import image_edit

OUTPUT_DIR = "outfit_output"
MANNEQUIN_SIZE = "1024x1536"
MANNEQUIN_PROMPT = (
    "Composite these garments onto a single department-store window mannequin, "
    "standing pose, plain simple background, soft even studio lighting. "
    "Layer the garments in natural wearing order: outerwear on the outside, "
    "the top layer underneath it, bottoms aligned at the waistline. "
    "The mannequin has no face and no facial features, no skin texture detail — "
    "commercial mannequin material quality, photorealistic product photography."
)
REF_WIDTH = 340  # every garment is scaled to (roughly) this width so proportions line up
SIDE_PADDING = 40
BG_COLOR = (245, 245, 245, 255)

TOP_BOTTOM_OVERLAP_PX = round(REF_WIDTH * 0.10)  # bottoms slide up under the top's hem
BOTTOM_SHOES_OVERLAP_PX = round(REF_WIDTH * 0.05)
OUTERWEAR_WIDTH_SCALE = 1.22  # drawn wider than the top so it "opens" around it
SHOE_GAP = 16

os.makedirs(OUTPUT_DIR, exist_ok=True)


def _load_cropped(path: str) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    if img.split()[3].getextrema() == (255, 255):
        # opaque product photo (e.g. gpt-image-1 flat lay) — cut the background out
        with open(path, "rb") as f:
            img = Image.open(io.BytesIO(remove(f.read()))).convert("RGBA")
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def _scale_to_width(img: Image.Image, width: int) -> Image.Image:
    ratio = width / img.width
    height = max(1, round(img.height * ratio))
    return img.resize((width, height), Image.LANCZOS)


def _merge_row(paths: List[str], item_width: int) -> Optional[Image.Image]:
    """Place same-slot items (e.g. a pair of shoes) side by side into a single image."""
    if not paths:
        return None
    imgs = [_scale_to_width(_load_cropped(p), item_width) for p in paths]
    width = sum(im.width for im in imgs) + SHOE_GAP * (len(imgs) - 1)
    height = max(im.height for im in imgs)
    row = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = 0
    for im in imgs:
        row.paste(im, (x, 0), im)
        x += im.width + SHOE_GAP
    return row


def compose_outfit_image(
    tops: Optional[List[str]] = None,
    bottoms: Optional[List[str]] = None,
    outerwear: Optional[List[str]] = None,
    shoes: Optional[List[str]] = None,
    output_dir: str = OUTPUT_DIR,
) -> str:
    """Composite the outfit onto a mannequin via gpt-image-1; fall back to the
    layered-cutout method (no external call) if the API call fails, so a
    transient outage doesn't block a recommendation."""
    try:
        return _compose_mannequin(tops, bottoms, outerwear, shoes, output_dir)
    except Exception as e:
        print(f"Mannequin compositing failed, falling back to layered cutout: {e}")
        return _compose_layered(tops, bottoms, outerwear, shoes, output_dir)


def _compose_mannequin(
    tops: Optional[List[str]],
    bottoms: Optional[List[str]],
    outerwear: Optional[List[str]],
    shoes: Optional[List[str]],
    output_dir: str,
) -> str:
    image_paths = []
    for group in (outerwear, tops, bottoms, shoes):
        image_paths.extend(group or [])
    if not image_paths:
        raise ValueError("No items to compose")

    image_bytes = image_edit(image_paths, MANNEQUIN_PROMPT, size=MANNEQUIN_SIZE)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{uuid.uuid4().hex}.png")
    with open(out_path, "wb") as f:
        f.write(image_bytes)
    return out_path


def _compose_layered(
    tops: Optional[List[str]] = None,
    bottoms: Optional[List[str]] = None,
    outerwear: Optional[List[str]] = None,
    shoes: Optional[List[str]] = None,
    output_dir: str = OUTPUT_DIR,
) -> str:
    """Layer real garment cutouts into one seamless outfit photo: the bottom's
    waist tucks under the top's hem, an open jacket sits wider behind the top,
    and shoes sit at the base — instead of a grid of separately padded cells."""
    top_img = _scale_to_width(_load_cropped(tops[0]), REF_WIDTH) if tops else None
    bottom_img = _scale_to_width(_load_cropped(bottoms[0]), REF_WIDTH) if bottoms else None
    shoes_img = _merge_row(shoes or [], REF_WIDTH // 2)

    decorative_outer = None
    if outerwear:
        if top_img is not None:
            # worn open behind the top: wider, so it peeks out past the shoulders/sides
            decorative_outer = _scale_to_width(
                _load_cropped(outerwear[0]), round(REF_WIDTH * OUTERWEAR_WIDTH_SCALE)
            )
        else:
            # no top selected — the jacket itself is the upper garment
            top_img = _scale_to_width(_load_cropped(outerwear[0]), REF_WIDTH)

    # main vertical chain: top -> bottom -> shoes, each overlapping the one above it
    chain = [
        (top_img, 0),
        (bottom_img, TOP_BOTTOM_OVERLAP_PX),
        (shoes_img, BOTTOM_SHOES_OVERLAP_PX),
    ]
    chain = [(img, overlap_px) for img, overlap_px in chain if img is not None]

    if not chain:
        raise ValueError("No items to compose")

    positions = []  # (img, y)
    cursor_y = 0
    prev_img = None
    for img, overlap_px in chain:
        if prev_img is not None:
            cursor_y += prev_img.height - overlap_px
        positions.append((img, cursor_y))
        prev_img = img

    max_width = max(
        [img.width for img, _ in positions] + ([decorative_outer.width] if decorative_outer else [0])
    )
    content_bottom = max(
        [y + img.height for img, y in positions]
        + ([decorative_outer.height] if decorative_outer else [0])
    )

    canvas_width = max_width + SIDE_PADDING * 2
    canvas_height = content_bottom + SIDE_PADDING * 2
    canvas = Image.new("RGBA", (canvas_width, canvas_height), BG_COLOR)

    def _paste_centered(img: Image.Image, y: int) -> None:
        x = SIDE_PADDING + (max_width - img.width) // 2
        canvas.paste(img, (x, y + SIDE_PADDING), img)

    if decorative_outer is not None:
        _paste_centered(decorative_outer, 0)  # aligned with the top, drawn behind it
    for img, y in positions:
        _paste_centered(img, y)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{uuid.uuid4().hex}.png")
    canvas.convert("RGB").save(out_path)
    return out_path
