"""Auto-headline overlay: a white rounded box with bold black text shown for the
first seconds of a clip (the look popularised by OpusClip)."""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
DEFAULT_FONT = FONT_DIR / "Poppins-Bold.ttf"


def _wrap(draw, text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def render_headline_png(text: str, video_w: int, out: str | Path,
                        font_path: str | Path | None = None) -> Path | None:
    """Draw the headline box as a transparent PNG. Returns None if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    text = " ".join(text.split())
    if not text:
        return None
    size = max(18, int(video_w * 0.048))
    try:
        font = ImageFont.truetype(str(font_path or DEFAULT_FONT), size)
    except OSError:
        font = ImageFont.load_default(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_text_w = int(video_w * 0.66)
    lines = _wrap(probe, text, font, max_text_w)
    line_h = int(size * 1.22)
    widths = [probe.textlength(line, font=font) for line in lines]
    pad_x, pad_y = int(size * 0.55), int(size * 0.38)
    box_w = int(max(widths) + 2 * pad_x)
    box_h = int(line_h * len(lines) + 2 * pad_y)
    shadow = int(size * 0.12)
    img = Image.new("RGBA", (box_w + shadow, box_h + shadow), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.35)
    d.rounded_rectangle((shadow, shadow, box_w + shadow - 1, box_h + shadow - 1), radius, fill=(0, 0, 0, 70))
    d.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius, fill=(255, 255, 255, 255))
    for i, (line, w) in enumerate(zip(lines, widths, strict=True)):
        x = (box_w - w) / 2
        y = pad_y + i * line_h + (line_h - size) / 2 - size * 0.08
        d.text((x, y), line, font=font, fill=(10, 10, 10, 255))
    out = Path(out)
    img.save(out)
    return out
