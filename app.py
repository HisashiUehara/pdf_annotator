import os

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from annotator.claude_client import translate_text
from annotator.extract import collect_text_in_rect, extract_japanese_spans
from annotator.imaging import overlay_texts_on_image, render_page_image
from annotator.render import render_texts_in_rects

st.set_page_config(page_title="PDF Annotator", layout="wide")
st.title("PDF Annotator")

DISPLAY_WIDTH = 900
PAGE_INDEX = 0

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("ANTHROPIC_API_KEY が未設定です。環境変数に設定してから起動してください。")


WORK_KEYS = ("source_text", "translation", "annotations")


def _reset_state(pdf_bytes: bytes, file_sig: int) -> None:
    """Reset session state for a freshly uploaded file."""
    for k in WORK_KEYS + ("page_img", "spans"):
        st.session_state.pop(k, None)
    st.session_state["file_sig"] = file_sig
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["stage"] = "extract"
    st.session_state["annotations"] = []


def _composite_image(base_image, annotations, scale):
    """Draw all accumulated annotations onto the page image for canvas display."""
    if not annotations:
        return base_image
    items = [
        (tuple(v * scale for v in a["rect"]), a["translation"]) for a in annotations
    ]
    return overlay_texts_on_image(base_image, items)


def _last_rect_pdf(canvas_result, scale):
    """Return the last drawn rectangle as PDF-point coords (x0, top, x1, bottom)."""
    if canvas_result is None or canvas_result.json_data is None:
        return None
    rects = [o for o in canvas_result.json_data.get("objects", []) if o.get("type") == "rect"]
    if not rects:
        return None
    o = rects[-1]
    left = float(o["left"])
    top = float(o["top"])
    w = float(o["width"]) * float(o.get("scaleX", 1))
    h = float(o["height"]) * float(o.get("scaleY", 1))
    return (left / scale, top / scale, (left + w) / scale, (top + h) / scale)


uploaded = st.file_uploader("PDFをアップロード", type=["pdf"])

if uploaded is not None:
    pdf_bytes = uploaded.getvalue()
    file_sig = hash(pdf_bytes)
    if st.session_state.get("file_sig") != file_sig:
        _reset_state(pdf_bytes, file_sig)

    # Rasterize the page once per file (cached in session_state). Text extraction is
    # deferred until the user asks to translate (see "選択範囲を英訳" below).
    if "page_img" not in st.session_state:
        st.session_state["page_img"] = render_page_image(pdf_bytes, PAGE_INDEX, DISPLAY_WIDTH)

    page_img = st.session_state["page_img"]
    scale = page_img.scale
    img_w, img_h = page_img.image.size
    stage = st.session_state.get("stage", "extract")
    annotations = st.session_state.setdefault("annotations", [])

    # Cached composite of the page image + all placed annotations (canvas background).
    anno_sig = tuple((a["rect"], a["translation"]) for a in annotations)
    if st.session_state.get("composite_sig") != anno_sig:
        st.session_state["composite_img"] = _composite_image(
            page_img.image, annotations, scale
        )
        st.session_state["composite_sig"] = anno_sig
    composite_img = st.session_state["composite_img"]

    # ----- Stage 1: select the Japanese text to translate -----
    if stage == "extract":
        st.subheader("ステップ1: 英訳する日本語を矩形で囲む")
        st.caption(f"追加済みの英訳: {len(annotations)} 件。続けて別の箇所を追加できます。")
        instruction = st.text_input("英訳の指示", value="Translate to natural English.")

        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.12)",
            stroke_width=2,
            stroke_color="#ff0000",
            background_image=composite_img,
            update_streamlit=True,
            height=img_h,
            width=img_w,
            drawing_mode="rect",
            # Key varies with the annotation count so the canvas re-initializes with
            # the updated composite background (and drops stale drawn rectangles).
            key=f"canvas_extract_{len(annotations)}",
        )

        if st.button("選択範囲を英訳", type="primary"):
            rect = _last_rect_pdf(canvas_result, scale)
            if rect is None:
                st.warning("矩形を描いてください。")
            else:
                # Extract words lazily (page 1 only), cached for later reruns.
                if "spans" not in st.session_state:
                    with st.spinner("テキストを抽出中..."):
                        st.session_state["spans"] = extract_japanese_spans(
                            pdf_bytes, PAGE_INDEX
                        )
                spans = st.session_state["spans"]
                source_text = collect_text_in_rect(spans, PAGE_INDEX, rect)
                if not source_text:
                    st.warning("矩形内に日本語が見つかりませんでした。")
                else:
                    with st.spinner("Claudeで英訳中..."):
                        try:
                            translation = translate_text(source_text, instruction)
                        except Exception as e:
                            st.error(f"英訳失敗: {e}")
                            translation = ""
                    if translation:
                        st.session_state["source_text"] = source_text
                        st.session_state["translation"] = translation
                        st.session_state["stage"] = "place"
                        st.rerun()

    # ----- Stage 2: place the current translation (NO Japanese lookup here) -----
    elif stage == "place":
        translation = st.session_state.get("translation", "")
        st.subheader("ステップ2: 英訳を置く場所を矩形で囲む")
        st.write(f"**抽出した日本語**: {st.session_state.get('source_text', '')}")
        st.markdown(f"**英訳**: :red[{translation}]")

        # st_canvas does not reliably paint its background on the place-stage canvas
        # (same media-loading flakiness as the "Missing file" warnings). Show the
        # composite (PDF page + already-placed translations) with st.image, which
        # always renders, directly above the same-sized drawing canvas so the
        # placement rectangle can be lined up with the drawing.
        st.image(composite_img, width=img_w, caption="現在の配置（PDF＋追加済みの英訳）。下の枠の同じ位置に矩形を描いてください。")

        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.12)",
            stroke_width=2,
            stroke_color="#ff0000",
            background_image=composite_img,
            update_streamlit=True,
            height=img_h,
            width=img_w,
            drawing_mode="rect",
            # Key varies with the annotation count so the canvas re-initializes with
            # the updated composite background (and drops stale drawn rectangles).
            key=f"canvas_place_{len(annotations)}",
        )

        cols = st.columns([0.5, 0.5])
        with cols[0]:
            if st.button("この英訳を追加", type="primary"):
                rect = _last_rect_pdf(canvas_result, scale)
                if rect is None:
                    st.warning("矩形を描いてください。")
                else:
                    annotations.append(
                        {
                            "translation": translation,
                            "source_text": st.session_state.get("source_text", ""),
                            "rect": rect,
                        }
                    )
                    st.session_state.pop("translation", None)
                    st.session_state.pop("source_text", None)
                    st.session_state["stage"] = "extract"
                    st.rerun()
        with cols[1]:
            if st.button("この英訳を破棄（ステップ1へ）"):
                st.session_state.pop("translation", None)
                st.session_state.pop("source_text", None)
                st.session_state["stage"] = "extract"
                st.rerun()

    else:
        # Unexpected stage value — recover to stage 1 instead of running either branch.
        st.session_state["stage"] = "extract"
        st.rerun()

    # ----- Shared footer: list, undo, and combined download -----
    st.divider()
    st.write(f"**追加済みの英訳: {len(annotations)} 件**")
    for i, a in enumerate(annotations, 1):
        st.markdown(f"{i}. :red[{a['translation']}]　（元: {a['source_text']}）")

    if annotations:
        fcols = st.columns([0.5, 0.5])
        with fcols[0]:
            if st.button("最後の1件を取り消す"):
                annotations.pop()
                st.rerun()
        with fcols[1]:
            # Burn ALL annotations into one PDF (reportlab), cached by signature so it
            # runs once per change — never for the on-screen overlay.
            if st.session_state.get("burn_sig") != anno_sig:
                with st.spinner("PDFを生成中..."):
                    st.session_state["burn_pdf"] = render_texts_in_rects(
                        st.session_state["pdf_bytes"],
                        PAGE_INDEX,
                        [(a["rect"], a["translation"]) for a in annotations],
                    )
                st.session_state["burn_sig"] = anno_sig
            st.download_button(
                "全ての英訳をまとめてダウンロード（PDF）",
                data=st.session_state["burn_pdf"],
                file_name="annotated.pdf",
                mime="application/pdf",
            )
