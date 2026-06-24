import os

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from annotator.claude_client import translate_text
from annotator.extract import collect_text_in_rect, extract_japanese_spans
from annotator.imaging import overlay_text_on_image, render_page_image
from annotator.render import render_text_in_rect

st.set_page_config(page_title="PDF Annotator", layout="wide")
st.title("PDF Annotator")

DISPLAY_WIDTH = 900
PAGE_INDEX = 0

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("ANTHROPIC_API_KEY が未設定です。環境変数に設定してから起動してください。")


WORK_KEYS = ("source_text", "translation", "place_rect", "preview_image", "burn_key", "burn_pdf")


def _reset_state(pdf_bytes: bytes, file_sig: int) -> None:
    """Reset session state for a freshly uploaded file."""
    for k in WORK_KEYS + ("page_img", "spans"):
        st.session_state.pop(k, None)
    st.session_state["file_sig"] = file_sig
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["stage"] = "extract"


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

    # ----- Stage 1: select the Japanese text to translate -----
    if stage == "extract":
        st.subheader("ステップ1: 英訳する日本語を矩形で囲む")
        instruction = st.text_input("英訳の指示", value="Translate to natural English.")

        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.12)",
            stroke_width=2,
            stroke_color="#ff0000",
            background_image=page_img.image,
            update_streamlit=True,
            height=img_h,
            width=img_w,
            drawing_mode="rect",
            key="canvas_extract",
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

    # ----- Stage 2: place the translation -----
    else:
        translation = st.session_state.get("translation", "")
        st.subheader("ステップ2: 英訳を置く場所を矩形で囲む")
        st.write(f"**抽出した日本語**: {st.session_state.get('source_text', '')}")
        st.markdown(f"**英訳**: :red[{translation}]")

        # The canvas background shows the live overlay (the translation drawn at the
        # chosen rect) once placed; otherwise the plain page image.
        bg_image = st.session_state.get("preview_image", page_img.image)
        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.12)",
            stroke_width=2,
            stroke_color="#ff0000",
            background_image=bg_image,
            update_streamlit=True,
            height=img_h,
            width=img_w,
            drawing_mode="rect",
            key="canvas_place",
        )

        cols = st.columns([0.5, 0.5])
        with cols[0]:
            if st.button("この位置に英訳を表示", type="primary"):
                rect = _last_rect_pdf(canvas_result, scale)
                if rect is None:
                    st.warning("矩形を描いてください。")
                else:
                    # On-screen overlay only (PIL) — no PDF burn-in here.
                    px_rect = tuple(v * scale for v in rect)
                    st.session_state["place_rect"] = rect
                    st.session_state["preview_image"] = overlay_text_on_image(
                        page_img.image, px_rect, translation
                    )
                    st.rerun()
        with cols[1]:
            if st.button("やり直す（ステップ1へ）"):
                for k in WORK_KEYS:
                    st.session_state.pop(k, None)
                st.session_state["stage"] = "extract"
                st.rerun()

        # Burn into a real PDF only to provide the download (reportlab is NOT used
        # for the on-screen overlay above). Cached per placement so it runs once.
        place_rect = st.session_state.get("place_rect")
        if place_rect:
            st.caption("配置した英訳は上の画像に重ねて表示しています。確定したらダウンロードしてください。")
            burn_key = (place_rect, translation)
            if st.session_state.get("burn_key") != burn_key:
                with st.spinner("PDFを生成中..."):
                    st.session_state["burn_pdf"] = render_text_in_rect(
                        st.session_state["pdf_bytes"], PAGE_INDEX, place_rect, translation
                    )
                st.session_state["burn_key"] = burn_key
            st.download_button(
                "ダウンロード（PDF）",
                data=st.session_state["burn_pdf"],
                file_name="annotated.pdf",
                mime="application/pdf",
            )
