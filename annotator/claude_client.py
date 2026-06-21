import json
import os
import re
from dataclasses import dataclass
from typing import List

import anthropic

from .extract import TextSpan

MODEL = "claude-opus-4-8"


@dataclass
class Annotation:
    span_id: int
    span: TextSpan
    overlay_text: str


def _is_select_all(target: str) -> bool:
    t = (target or "").strip()
    if not t:
        return True
    return t in {"全部", "すべて", "全て", "all", "All", "ALL"}


def _build_prompt(
    spans: List[TextSpan], instruction: str, target: str = ""
) -> tuple[str, str]:
    payload = []
    for s in spans:
        # Coordinate system: origin at TOP-LEFT, x grows right, y grows DOWN.
        # rel_x / rel_y are fractional positions of the line's top-left corner.
        rel_x = round(s.x0 / s.page_width, 3) if s.page_width else 0.0
        rel_y = round(s.top / s.page_height, 3) if s.page_height else 0.0
        payload.append(
            {
                "id": s.id,
                "text": s.text,
                "page": s.page,
                "bbox": [round(s.x0, 1), round(s.top, 1), round(s.x1, 1), round(s.bottom, 1)],
                "page_size": [round(s.page_width, 1), round(s.page_height, 1)],
                "rel_pos": [rel_x, rel_y],
            }
        )
    system = (
        "You convert Japanese text fragments extracted from a PDF into the overlay text "
        "the user wants drawn on top of the original. Output strict JSON only.\n\n"
        "Each fragment includes its position. Coordinate system: origin is TOP-LEFT of "
        "the page, x grows to the RIGHT, y grows DOWNWARD. bbox=[x0,y0,x1,y1] in PDF "
        "points, page_size=[width,height], rel_pos=[x_fraction,y_fraction] of the "
        "top-left corner (0,0=top-left, 1,1=bottom-right). Use BOTH the text content "
        "and the position to decide which fragments match."
    )

    if _is_select_all(target):
        selection = "Process EVERY fragment below.\n"
    else:
        selection = (
            f'Extraction target: "{target}"\n'
            "Select ONLY the fragment(s) that best match this target, using BOTH the text "
            "content AND the position. Omit everything else — do not include "
            "non-matching fragments in the output.\n"
            "Domain hint: in engineering/architectural drawings, the drawing title "
            "(図面名称/図面名) lives in the TITLE BLOCK, which is normally at the "
            "BOTTOM-RIGHT or along the BOTTOM of the page (rel_pos y close to 1.0, and "
            "often x toward the right). Generic component/spec labels scattered across "
            "the drawing body (e.g. ケーブル配線支持 and similar part/spec annotations) "
            "are NOT the drawing title even if they contain plausible words. "
            "Prefer the fragment whose BOTH content and title-block position fit best; "
            "if several plausibly match, pick the one closest to the bottom-right.\n"
        )

    user_message = (
        f"User instruction: {instruction}\n\n"
        f"{selection}"
        "For each selected Japanese fragment, produce the overlay text to draw on the PDF.\n"
        "Return ONLY a JSON array (no prose, no code fences) with this shape:\n"
        '[{"id": <int>, "overlay": "<text to draw>"}, ...]\n\n'
        f"Fragments:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return system, user_message


def _extract_json(text: str) -> list:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def generate_annotations(
    spans: List[TextSpan], instruction: str, target: str = ""
) -> List[Annotation]:
    if not spans:
        return []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic()
    system, user_msg = _build_prompt(spans, instruction, target)

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    text_block = next((b.text for b in response.content if b.type == "text"), "")
    items = _extract_json(text_block)

    by_id = {s.id: s for s in spans}
    out: List[Annotation] = []
    for item in items:
        sid = item.get("id")
        overlay = (item.get("overlay") or "").strip()
        if sid in by_id and overlay:
            out.append(Annotation(span_id=sid, span=by_id[sid], overlay_text=overlay))
    return out


def translate_text(text: str, instruction: str = "Translate to natural English.") -> str:
    """Translate a single Japanese fragment to the overlay text to draw."""
    text = (text or "").strip()
    if not text:
        return ""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic()
    system = (
        "You translate Japanese text extracted from a PDF drawing into the overlay text "
        "to draw on top of the original. Reply with ONLY the translated text — no quotes, "
        "no labels, no explanation."
    )
    user_message = (
        f"Instruction: {instruction}\n\n"
        f"Japanese text:\n{text}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return next((b.text for b in response.content if b.type == "text"), "").strip()
