from dataclasses import dataclass
from io import BytesIO
from typing import Tuple

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

# Bold fonts to try for the on-screen overlay; falls back to Pillow's built-in.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
]


def _load_font(size: int):
    size = max(int(size), 6)
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1, scalable
    except TypeError:
        return ImageFont.load_default()


@dataclass
class PageImage:
    image: Image.Image
    scale: float  # pixels per PDF point (image_px = pdf_point * scale)
    page_width: float  # PDF points
    page_height: float  # PDF points


def render_page_image(
    pdf_bytes: bytes, page_index: int = 0, display_width: int = 900
) -> PageImage:
    """Rasterize one PDF page to a PIL image sized to display_width pixels.

    The returned scale maps PDF points (pdfplumber's top-origin user space) to
    image pixels, so canvas pixel coords / scale == PDF points.
    """
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[page_index]
        page_width, page_height = page.get_size()  # PDF points
        scale = display_width / page_width if page_width else 1.0
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()

    return PageImage(
        image=image,
        scale=scale,
        page_width=float(page_width),
        page_height=float(page_height),
    )


def overlay_text_on_image(
    image: Image.Image,
    pixel_rect: Tuple[float, float, float, float],
    text: str,
    color: Tuple[int, int, int] = (255, 0, 0),
) -> Image.Image:
    """Return a copy of `image` with `text` drawn (red) inside `pixel_rect`.

    `pixel_rect` is (x0, top, x1, bottom) in IMAGE pixel coordinates (top-origin),
    i.e. PDF points multiplied by PageImage.scale. The font is sized to fit the
    rectangle width, mirroring the burned-in PDF overlay.
    """
    if not text:
        return image

    img = image.copy()
    draw = ImageDraw.Draw(img)

    x0, top, x1, bottom = pixel_rect
    rect_w = max(x1 - x0, 1.0)
    rect_h = max(bottom - top, 1.0)

    size = max(rect_h * 0.8, 6.0)
    font = _load_font(size)
    text_w = draw.textlength(text, font=font)
    if text_w > rect_w and text_w > 0:
        size = max(size * rect_w / text_w, 6.0)
        font = _load_font(size)

    # Vertically center the glyphs within the rectangle.
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    y = top + (rect_h - text_h) / 2 - bbox[1]
    draw.text((x0, y), text, fill=color, font=font)
    return img
