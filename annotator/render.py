from io import BytesIO
from typing import List, Tuple

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import red
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from .claude_client import Annotation


def render_annotated_pdf(
    original_pdf_bytes: bytes,
    annotations: List[Annotation],
) -> bytes:
    reader = PdfReader(BytesIO(original_pdf_bytes))

    by_page: dict[int, list[Annotation]] = {}
    for ann in annotations:
        by_page.setdefault(ann.span.page, []).append(ann)

    overlay_buf = BytesIO()
    c = canvas.Canvas(overlay_buf)

    for page_idx, page in enumerate(reader.pages):
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)
        c.setPageSize((page_w, page_h))

        for ann in by_page.get(page_idx, []):
            span = ann.span
            line_h = max(span.bottom - span.top, 8.0)
            font_size = max(line_h * 0.85, 6.0)
            # pdfplumber: top-origin coords. reportlab/PDF native: bottom-origin.
            y_pdf = page_h - span.bottom + (line_h - font_size) / 2
            c.setFillColor(red)
            c.setFont("Helvetica-Bold", font_size)
            c.drawString(span.x0, y_pdf, ann.overlay_text)

        c.showPage()

    c.save()
    overlay_buf.seek(0)

    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        page.merge_page(overlay_reader.pages[i])
        writer.add_page(page)

    out_buf = BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()


def _fit_font_size(
    text: str, rect_width: float, rect_height: float, font: str
) -> float:
    """Largest font size whose text fits within rect_width, capped by rect_height."""
    size = max(rect_height * 0.8, 6.0)
    if not text:
        return size
    width = stringWidth(text, font, size)
    if width > rect_width and width > 0:
        size = size * (rect_width / width)
    return max(size, 4.0)


def render_texts_in_rects(
    original_pdf_bytes: bytes,
    page_index: int,
    items: List[Tuple[Tuple[float, float, float, float], str]],
    font: str = "Helvetica-Bold",
) -> bytes:
    """Draw several texts (red), each inside its own rect, on the given page.

    `items` is a list of (rect, text) where rect is (x0, top, x1, bottom) in PDF
    points using pdfplumber's TOP-origin convention (y measured from the top).
    """
    reader = PdfReader(BytesIO(original_pdf_bytes))

    overlay_buf = BytesIO()
    c = canvas.Canvas(overlay_buf)

    for idx, page in enumerate(reader.pages):
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)
        c.setPageSize((page_w, page_h))

        if idx == page_index:
            for rect, text in items:
                if not text:
                    continue
                x0, top, x1, bottom = rect
                rect_width = max(x1 - x0, 1.0)
                rect_height = max(bottom - top, 1.0)
                font_size = _fit_font_size(text, rect_width, rect_height, font)
                # Convert top-origin rect to bottom-origin baseline, vertically centered.
                y_pdf = page_h - bottom + (rect_height - font_size) / 2
                c.setFillColor(red)
                c.setFont(font, font_size)
                c.drawString(x0, y_pdf, text)

        c.showPage()

    c.save()
    overlay_buf.seek(0)

    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        page.merge_page(overlay_reader.pages[i])
        writer.add_page(page)

    out_buf = BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()


def render_text_in_rect(
    original_pdf_bytes: bytes,
    page_index: int,
    rect: Tuple[float, float, float, float],
    text: str,
    font: str = "Helvetica-Bold",
) -> bytes:
    """Draw `text` (red) inside `rect` on the given page. Single-item convenience."""
    return render_texts_in_rects(original_pdf_bytes, page_index, [(rect, text)], font)
