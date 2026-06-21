from dataclasses import dataclass
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image


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
