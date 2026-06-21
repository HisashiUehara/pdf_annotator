from dataclasses import dataclass
from io import BytesIO
from typing import List, Tuple

import pdfplumber

JAPANESE_RANGES = [
    ("぀", "ゟ"),  # hiragana
    ("゠", "ヿ"),  # katakana
    ("一", "鿿"),  # CJK unified ideographs
    ("㐀", "䶿"),  # CJK extension A
    ("ｦ", "ﾟ"),  # halfwidth katakana
]


def has_japanese(s: str) -> bool:
    for c in s:
        for lo, hi in JAPANESE_RANGES:
            if lo <= c <= hi:
                return True
    return False


@dataclass
class TextSpan:
    id: int
    page: int  # 0-indexed
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    page_width: float
    page_height: float


def extract_japanese_spans(pdf_bytes: bytes) -> List[TextSpan]:
    spans: List[TextSpan] = []
    next_id = 0
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            try:
                words = page.extract_words()
            except Exception:
                words = []
            for word in words:
                text = (word.get("text") or "").strip()
                if not text or not has_japanese(text):
                    continue
                spans.append(
                    TextSpan(
                        id=next_id,
                        page=page_idx,
                        text=text,
                        x0=float(word["x0"]),
                        top=float(word["top"]),
                        x1=float(word["x1"]),
                        bottom=float(word["bottom"]),
                        page_width=float(page.width),
                        page_height=float(page.height),
                    )
                )
                next_id += 1
    return spans


def collect_text_in_rect(
    spans: List[TextSpan],
    page_index: int,
    rect: Tuple[float, float, float, float],
) -> str:
    """Join the text of words on `page_index` whose bbox overlaps `rect`.

    `rect` is (x0, top, x1, bottom) in PDF points (pdfplumber TOP-origin coords).
    Words are returned in reading order (top-to-bottom, then left-to-right).
    """
    rx0, rtop, rx1, rbottom = rect
    hits = [
        s
        for s in spans
        if s.page == page_index
        and s.x0 < rx1
        and s.x1 > rx0
        and s.top < rbottom
        and s.bottom > rtop
    ]
    # Group words on roughly the same line, then order left-to-right within a line.
    hits.sort(key=lambda s: (round(s.top / 3.0), s.x0))
    return "".join(s.text for s in hits)
