import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# (title, subtitle, tier letter, item label, item meta / avg)
TierListFonts = Tuple[
    ImageFont.ImageFont,
    ImageFont.ImageFont,
    ImageFont.ImageFont,
    ImageFont.ImageFont,
    ImageFont.ImageFont,
]


def _hex(color: str) -> Tuple[int, int, int]:
    """`#rrggbb` or `rrggbb` — paste from any color picker, design tool, or site."""
    s = color.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected 6 hex digits, got {color!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


@dataclass(frozen=True)
class TierListRenderConfig:
    """Layout + typography for tierlist PNGs. Tune `typography_scale` for global font scaling (e.g. 1.1).

    Use `option_column_width` to widen caption area (labels wrap to this width; thumbs stay `tile_size`).
    Use `item_label_max_chars` to truncate before wrapping (default: no cap except a 2000-char safety limit).
    """

    width: int = 1600
    padding: int = 16
    tier_label_width: int = 112
    tile_size: int = 140
    # Wider columns give more horizontal room for wrapped labels; thumbnail stays `tile_size` and centers.
    option_column_width: Optional[int] = 180
    tile_padding: int = 10
    # Min height for option name + stats under each tile; layout uses max(this, height from item fonts).
    label_height: int = 40
    # Optional hard cap before wrapping (None = only a generous safety limit inside the renderer).
    item_label_max_chars: Optional[int] = None
    # Inset for option thumbnail inside the top square (eases off top/left/right/bottom of image area).
    tile_image_inset: int = 5
    # Space below the avg / stats line (above bottom edge of the tile).
    tile_caption_pad_bottom: int = 8
    # Point sizes (before `typography_scale`). Bump `typography_scale` to scale all at once.
    font_size_title: int = 44
    font_size_subtitle: int = 24
    font_size_tier_letter: int = 40
    font_size_item_label: int = 26
    font_size_item_meta: int = 18
    typography_scale: float = 1.0
    # Slight corner radii (px). 0 disables that layer.
    corner_radius_canvas: int = 16
    corner_radius_tier: int = 10
    corner_radius_tile: int = 8
    # Vertical rhythm: title, status line, then tier rows.
    gap_title_subtitle: int = 20
    gap_after_header: int = 28


TIER_ORDER: Tuple[str, ...] = ("S", "A", "B", "C", "D", "F", "N/A")
# Tier band colors — set as hex; use any picker (browser devtools, Figma, coolors.co, etc.).
TIER_COLORS: Dict[str, Tuple[int, int, int]] = {
    "S": _hex("#ff7f7f"),
    "A": _hex("#ffb27f"),
    "B": _hex("#ffdf7f"),
    "C": _hex("#bfff7f"),
    "D": _hex("#7fff7f"),
    "F": _hex("#7fbfff"),
    "N/A": _hex("#787880"),
}

# Repo-root-relative search (same pattern as `main_bot.paths.PROJECT_ROOT` parents)
_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _truetype(priority: List[Path], size: int) -> ImageFont.ImageFont:
    for path in priority:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _font_candidates() -> List[Path]:
    return [
        _FONTS_DIR / "DejaVuSans.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]


def _font_candidates_tier_bold() -> List[Path]:
    """Bold faces for S/A/B… — regular list appended as last resort."""
    return [
        _FONTS_DIR / "DejaVuSans-Bold.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ] + _font_candidates()


def _pt(config: TierListRenderConfig, n: int) -> int:
    return max(6, int(round(n * config.typography_scale)))


def _load_tierlist_fonts(config: TierListRenderConfig) -> TierListFonts:
    c = _font_candidates()
    tier = _truetype(
        _font_candidates_tier_bold(), _pt(config, config.font_size_tier_letter)
    )
    return (
        _truetype(c, _pt(config, config.font_size_title)),
        _truetype(c, _pt(config, config.font_size_subtitle)),
        tier,
        _truetype(c, _pt(config, config.font_size_item_label)),
        _truetype(c, _pt(config, config.font_size_item_meta)),
    )


def _text_h(font: ImageFont.ImageFont, text: str) -> int:
    b = font.getbbox(text)
    return b[3] - b[1]


def _text_pixel_w(font: ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    b = font.getbbox(text)
    return b[2] - b[0]


def _column_width(config: TierListRenderConfig) -> int:
    w = config.option_column_width
    if w is None:
        return config.tile_size
    return max(int(w), config.tile_size)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)] + "…"


def _prepare_item_label(raw: str, config: TierListRenderConfig) -> str:
    s = str(raw or "").strip()
    if config.item_label_max_chars is not None:
        s = _truncate(s, int(config.item_label_max_chars))
    elif len(s) > 2000:
        s = _truncate(s, 2000)
    return s


def _wrap_lines(
    font: ImageFont.ImageFont,
    text: str,
    max_width: int,
) -> List[str]:
    """Word-wrap `text` to fit `max_width` px; breaks long tokens so nothing overflows horizontally."""
    if max_width < 8:
        return [text] if text else [""]
    t = text.strip()
    if not t:
        return [""]

    lines: List[str] = []
    for raw_para in t.split("\n"):
        para = raw_para.strip()
        if not para:
            lines.append("")
            continue
        words = para.split()
        cur: List[str] = []
        for word in words:
            if _text_pixel_w(font, word) > max_width:
                if cur:
                    lines.append(" ".join(cur))
                    cur = []
                chunk = ""
                for ch in word:
                    trial = chunk + ch
                    if _text_pixel_w(font, trial) <= max_width:
                        chunk = trial
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ""
                        if _text_pixel_w(font, ch) > max_width:
                            lines.append(ch)
                        else:
                            chunk = ch
                if chunk:
                    cur = [chunk]
                continue

            trial = word if not cur else " ".join(cur + [word])
            if _text_pixel_w(font, trial) <= max_width:
                cur.append(word)
            else:
                if cur:
                    lines.append(" ".join(cur))
                cur = [word]
        if cur:
            lines.append(" ".join(cur))
    return lines if lines else [""]


def _nonempty_label_lines(lines: List[str]) -> List[str]:
    return [ln for ln in lines if ln]


def _multiline_label_height(font: ImageFont.ImageFont, lines: List[str]) -> int:
    nonempty = _nonempty_label_lines(lines)
    if not nonempty:
        return 0
    gap = 2
    return sum(_text_h(font, ln) for ln in nonempty) + (len(nonempty) - 1) * gap


def _caption_stripe_height(
    *,
    label_lines: List[str],
    item_label_font: ImageFont.ImageFont,
    item_meta_font: ImageFont.ImageFont,
    config: TierListRenderConfig,
) -> int:
    label_h = _multiline_label_height(item_label_font, label_lines)
    meta_h = _text_h(item_meta_font, "avg 99.99")
    return 2 + label_h + 2 + meta_h + config.tile_caption_pad_bottom


def _apply_rounded_canvas(im: Image.Image, *, radius: int, fill: Tuple[int, int, int]) -> Image.Image:
    """Clip `im` to a rounded rect; areas outside the radius use `fill` (match page background)."""
    w, h = im.size
    if radius <= 0:
        return im
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    out = Image.new("RGB", (w, h), fill)
    out.paste(im, (0, 0), mask)
    return out


def generate_tierlist_image(
    *,
    output_path: str,
    tier_to_items: Dict[str, List[Dict[str, Any]]],
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    config: TierListRenderConfig = TierListRenderConfig(),
) -> str:
    """
    Generates a composite tier list image.

    `tier_to_items` expects tier letter -> list of items, each item:
      - {"text": str, "image_path": Optional[str], "avg": Optional[float], "vote_count": Optional[int]}

    Items in each list should be ordered **left to right** (e.g. descending average). Within-tier sort is the caller's job.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    title_font, subtitle_font, tier_font, item_label_font, item_meta_font = _load_tierlist_fonts(config)
    bg = _hex("#1e1e23")
    fg = _hex("#f5f5f5")
    muted = _hex("#b4b4be")
    tile_bg = _hex("#373741")
    tier_label = _hex("#ffffff")
    tier_label_stroke = _hex("#ffffff")

    inset = max(0, int(config.tile_image_inset))
    cap_x_margin = max(6, inset)
    col_w = _column_width(config)
    cap_max_w = max(12, col_w - 2 * cap_x_margin)

    # Minimum caption stripe; each grid row uses max of this and wrapped label height.
    label_stripe_min = max(
        config.label_height,
        2
        + _text_h(item_label_font, "Aygj")
        + 2
        + _text_h(item_meta_font, "avg 99.99")
        + config.tile_caption_pad_bottom,
    )

    content_width = config.width - (config.padding * 2)
    tiles_per_row = max(1, (content_width - config.tier_label_width) // (col_w + config.tile_padding))

    tier_heights: Dict[str, int] = {}
    tier_row_specs: Dict[str, List[Tuple[List[Dict[str, Any]], List[List[str]], int]]] = {}
    for tier in TIER_ORDER:
        items = tier_to_items.get(tier, []) or []
        if not items:
            tier_row_specs[tier] = []
            tier_heights[tier] = (config.tile_size + label_stripe_min) + config.tile_padding + (
                config.padding // 2
            )
            continue
        chunks = [items[i : i + tiles_per_row] for i in range(0, len(items), tiles_per_row)]
        rows_spec: List[Tuple[List[Dict[str, Any]], List[List[str]], int]] = []
        for chunk in chunks:
            lines_per_item = [
                _wrap_lines(
                    item_label_font,
                    _prepare_item_label(it.get("text", ""), config),
                    cap_max_w,
                )
                for it in chunk
            ]
            stripes = [
                _caption_stripe_height(
                    label_lines=ln,
                    item_label_font=item_label_font,
                    item_meta_font=item_meta_font,
                    config=config,
                )
                for ln in lines_per_item
            ]
            row_stripe = max(label_stripe_min, max(stripes))
            row_block_h = config.tile_size + row_stripe
            rows_spec.append((chunk, lines_per_item, row_block_h))
        tier_row_specs[tier] = rows_spec
        n_rows = len(rows_spec)
        tier_heights[tier] = sum(rb for (_, _, rb) in rows_spec) + n_rows * config.tile_padding + (
            config.padding // 2
        )

    t_str = str(title)[:200] if title else ""
    s_str = str(subtitle)[:240] if subtitle else ""
    title_block = 0
    if t_str:
        title_block += _text_h(title_font, t_str) + (config.gap_title_subtitle if s_str else 0)
    if s_str:
        title_block += _text_h(subtitle_font, s_str)
    if t_str or s_str:
        title_block += config.gap_after_header

    total_h = config.padding * 2 + title_block + sum(tier_heights.values())
    img = Image.new("RGB", (config.width, total_h), color=bg)
    draw = ImageDraw.Draw(img)

    y = config.padding
    if t_str:
        draw.text((config.padding, y), t_str, font=title_font, fill=fg)
        y += _text_h(title_font, t_str) + (config.gap_title_subtitle if s_str else 0)
    if s_str:
        draw.text((config.padding, y), s_str, font=subtitle_font, fill=muted)
        y += _text_h(subtitle_font, s_str) + config.gap_after_header

    for tier in TIER_ORDER:
        row_h = tier_heights[tier]
        tier_color = TIER_COLORS.get(tier, (120, 120, 120))

        x0 = config.padding
        y0 = y
        x1 = x0 + config.tier_label_width
        y1 = y0 + row_h - config.tile_padding
        r_t = max(0, int(config.corner_radius_tier))
        if r_t:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r_t, fill=tier_color)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=tier_color)
        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2
        draw.text(
            (cx, cy),
            tier,
            font=tier_font,
            fill=tier_label,
            anchor="mm",
            stroke_width=1,
            stroke_fill=tier_label_stroke,
        )

        tiles_x_start = x1 + config.tile_padding
        ty = y0
        r_o = max(0, int(config.corner_radius_tile))
        thumb_left_offset = (col_w - config.tile_size) // 2

        for chunk, lines_per_item, row_block_h in tier_row_specs[tier]:
            tx = tiles_x_start
            for item, label_lines in zip(chunk, lines_per_item):
                image_path = item.get("image_path")
                raw_avg = item.get("avg")
                vote_c = item.get("vote_count")

                if raw_avg is not None:
                    avg_s = f"avg {float(raw_avg):.2f}"
                elif vote_c is not None and int(vote_c) == 0:
                    avg_s = "no votes"
                else:
                    avg_s = "—"

                opt_rect = (tx, ty, tx + col_w, ty + row_block_h)
                if r_o:
                    draw.rounded_rectangle(opt_rect, radius=r_o, fill=tile_bg)
                else:
                    draw.rectangle(list(opt_rect), fill=tile_bg)

                if image_path and os.path.exists(str(image_path)):
                    try:
                        tile_img = Image.open(str(image_path)).convert("RGB")
                        max_side = max(1, config.tile_size - 2 * inset)
                        tile_img.thumbnail((max_side, max_side))
                        px = tx + thumb_left_offset + inset + (max_side - tile_img.width) // 2
                        py = ty + inset + (max_side - tile_img.height) // 2
                        img.paste(tile_img, (px, py))
                    except Exception:
                        pass

                cap_x = tx + cap_x_margin
                cap_y = ty + config.tile_size + 2
                nonempty = _nonempty_label_lines(label_lines)
                for i, ln in enumerate(nonempty):
                    draw.text((cap_x, cap_y), ln, font=item_label_font, fill=fg)
                    cap_y += _text_h(item_label_font, ln)
                    if i < len(nonempty) - 1:
                        cap_y += 2
                cap_y += 2
                draw.text((cap_x, cap_y), avg_s, font=item_meta_font, fill=muted)

                tx += col_w + config.tile_padding
            ty += row_block_h + config.tile_padding

        y += row_h

    r_canvas = max(0, int(config.corner_radius_canvas))
    if r_canvas:
        img = _apply_rounded_canvas(img, radius=r_canvas, fill=bg)
    img.save(output_path, format="PNG", optimize=True)
    return output_path
