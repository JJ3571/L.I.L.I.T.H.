import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class TierListRenderConfig:
    width: int = 1200
    padding: int = 16
    tier_label_width: int = 90
    tile_size: int = 140
    tile_padding: int = 10
    text_height: int = 22


TIER_ORDER: Tuple[str, ...] = ("S", "A", "B", "C", "D", "F")
TIER_COLORS: Dict[str, Tuple[int, int, int]] = {
    "S": (255, 127, 127),
    "A": (255, 178, 127),
    "B": (255, 223, 127),
    "C": (191, 255, 127),
    "D": (127, 255, 127),
    "F": (127, 191, 255),
}


def _safe_font(size: int = 16) -> ImageFont.ImageFont:
    # Keep it portable: use default font if no TTF available.
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)] + "…"


def generate_tierlist_image(
    *,
    output_path: str,
    tier_to_items: Dict[str, List[Dict]],
    title: Optional[str] = None,
    config: TierListRenderConfig = TierListRenderConfig(),
) -> str:
    """
    Generates a composite tier list image.

    `tier_to_items` expects tier letter -> list of items, each item:
      - {"text": str, "image_path": Optional[str]}
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    font = _safe_font()
    title_font = _safe_font()
    bg = (30, 30, 35)
    fg = (245, 245, 245)

    content_width = config.width - (config.padding * 2)
    tile_block_w = config.tile_size
    tiles_per_row = max(1, (content_width - config.tier_label_width) // (tile_block_w + config.tile_padding))

    # Precompute heights per tier based on item count.
    tier_heights: Dict[str, int] = {}
    for tier in TIER_ORDER:
        items = tier_to_items.get(tier, []) or []
        rows = max(1, (len(items) + tiles_per_row - 1) // tiles_per_row) if items else 1
        tier_heights[tier] = max(
            config.tile_size + config.text_height + (config.padding // 2),
            rows * (config.tile_size + config.text_height + config.tile_padding) + (config.padding // 2),
        )

    title_h = 0
    if title:
        title_h = 48

    total_h = config.padding * 2 + title_h + sum(tier_heights.values())
    img = Image.new("RGB", (config.width, total_h), color=bg)
    draw = ImageDraw.Draw(img)

    y = config.padding
    if title:
        draw.text((config.padding, y), title, font=title_font, fill=fg)
        y += title_h

    for tier in TIER_ORDER:
        row_h = tier_heights[tier]
        tier_color = TIER_COLORS.get(tier, (120, 120, 120))

        # Tier label panel
        x0 = config.padding
        y0 = y
        x1 = x0 + config.tier_label_width
        y1 = y0 + row_h - config.tile_padding
        draw.rectangle([x0, y0, x1, y1], fill=tier_color)
        draw.text((x0 + 10, y0 + 10), tier, font=font, fill=(0, 0, 0))

        # Tiles area
        items = tier_to_items.get(tier, []) or []
        tiles_x_start = x1 + config.tile_padding
        tx = tiles_x_start
        ty = y0
        col = 0

        for item in items:
            label = _truncate(str(item.get("text", "")), 18)
            image_path = item.get("image_path")

            # Tile background
            tile_bg = (55, 55, 65)
            draw.rectangle(
                [tx, ty, tx + config.tile_size, ty + config.tile_size + config.text_height],
                fill=tile_bg,
            )

            # Paste image if exists
            if image_path and os.path.exists(image_path):
                try:
                    tile_img = Image.open(image_path).convert("RGB")
                    tile_img.thumbnail((config.tile_size, config.tile_size))
                    px = tx + (config.tile_size - tile_img.width) // 2
                    py = ty + (config.tile_size - tile_img.height) // 2
                    img.paste(tile_img, (px, py))
                except Exception:
                    # keep placeholder box
                    pass

            # Label
            draw.text((tx + 6, ty + config.tile_size + 2), label, font=font, fill=fg)

            col += 1
            if col >= tiles_per_row:
                col = 0
                tx = tiles_x_start
                ty += config.tile_size + config.text_height + config.tile_padding
            else:
                tx += config.tile_size + config.tile_padding

        y += row_h

    img.save(output_path, format="PNG", optimize=True)
    return output_path



