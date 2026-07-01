"""PDF Annotator v2 — draw rectangles directly on the page image.

Rebuilt on streamlit-image-annotation (detection mode), which renders the
background image reliably and returns multiple rectangles. This file is a
SEPARATE entry point; app.py is left untouched and only imported from.

This first cut is intentionally a SINGLE-ITEM flow to verify that the drawn
rectangle maps to the burned position with no offset:
  1 target rect -> 1 translation -> 1 placement rect -> burn 1 into the PDF.
Multiple rectangles + label mapping come next, after coordinates are confirmed.
"""

import os

import streamlit as st
from streamlit_image_annotation import detection

from annotator.claude_client import translate_text
from annotator.extract import collect_text_in_rect, extract_japanese_spans
from annotator.imaging import overlay_texts_on_image, render_page_image
from annotator.render import render_texts_in_rects

st.set_page_config(page_title="PDF Annotator v2", layout="wide")
st.title("PDF Annotator v2 — 座標検証（単一件）")

DISPLAY_WIDTH = 900
PAGE_INDEX = 0

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("ANTHROPIC_API_KEY が未設定です。環境変数に設定してから起動してください。")


def _bbox_to_pdf_rect(bbox, scale):
    """detection() bbox [x, y, w, h] (image px, top-left) -> PDF rect (top-origin)."""
    x, y, w, h = bbox
    return (x / scale, y / scale, (x + w) / scale, (y + h) / scale)


def _first_bbox(result):
    """Return the first drawn bbox [x, y, w, h] or None."""
    if not result:
        return None
    return result[0]["bbox"]


uploaded = st.file_uploader("PDFをアップロード", type=["pdf"], key="v2_upload")

if uploaded is not None:
    pdf_bytes = uploaded.getvalue()
    file_sig = hash(pdf_bytes)
    if st.session_state.get("v2_file_sig") != file_sig:
        for k in ("v2_page_img", "v2_spans", "v2_pending", "v2_preview", "v2_pdf"):
            st.session_state.pop(k, None)
        st.session_state["v2_file_sig"] = file_sig
        st.session_state["v2_stage"] = "extract"

    # Rasterize once per file. detection() shows this image directly (no white canvas).
    if "v2_page_img" not in st.session_state:
        st.session_state["v2_page_img"] = render_page_image(pdf_bytes, PAGE_INDEX, DISPLAY_WIDTH)
    page_img = st.session_state["v2_page_img"]
    scale = page_img.scale
    img_w, img_h = page_img.image.size
    stage = st.session_state.get("v2_stage", "extract")

    # ----- Stage 1: select the Japanese to translate -----
    if stage == "extract":
        st.subheader("ステップ1: 対象の日本語を矩形で囲む（PDF画像の上で直接）")
        st.caption("検証のためまず1件。矩形を1つ描いて「英訳する」を押してください。")
        # NOTE: pass a COPY — detection() calls image.thumbnail() in place.
        result = detection(
            image_path=page_img.image.copy(),
            label_list=["対象"],
            bboxes=[],
            labels=[],
            height=img_h,
            width=img_w,
            key="v2_det_extract",
        )

        if st.button("英訳する", type="primary"):
            bbox = _first_bbox(result)
            if bbox is None:
                st.warning("矩形を描いてください。")
            else:
                rect = _bbox_to_pdf_rect(bbox, scale)
                if "v2_spans" not in st.session_state:
                    with st.spinner("テキストを抽出中..."):
                        st.session_state["v2_spans"] = extract_japanese_spans(
                            pdf_bytes, PAGE_INDEX
                        )
                source_text = collect_text_in_rect(
                    st.session_state["v2_spans"], PAGE_INDEX, rect
                )
                if not source_text:
                    st.warning("矩形内に日本語が見つかりませんでした。")
                else:
                    with st.spinner("Claudeで英訳中..."):
                        try:
                            translation = translate_text(source_text)
                        except Exception as e:
                            st.error(f"英訳失敗: {e}")
                            translation = ""
                    if translation:
                        st.session_state["v2_pending"] = {
                            "source": source_text,
                            "translation": translation,
                        }
                        st.session_state["v2_stage"] = "place"
                        st.rerun()

    # ----- Stage 2: place the translation -----
    else:
        pending = st.session_state.get("v2_pending", {})
        st.subheader("ステップ2: 英訳を置く場所を矩形で囲む（同じPDF画像の上で）")
        st.write(f"**抽出した日本語**: {pending.get('source', '')}")
        st.markdown(f"**英訳**: :red[{pending.get('translation', '')}]")

        result = detection(
            image_path=page_img.image.copy(),
            label_list=["配置"],
            bboxes=[],
            labels=[],
            height=img_h,
            width=img_w,
            key="v2_det_place",
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("配置してPDFを生成", type="primary"):
                bbox = _first_bbox(result)
                if bbox is None:
                    st.warning("矩形を描いてください。")
                else:
                    rect = _bbox_to_pdf_rect(bbox, scale)
                    translation = pending.get("translation", "")
                    # On-screen prediction (PIL) at the SAME image-pixel rect.
                    px_rect = (bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3])
                    st.session_state["v2_preview"] = overlay_texts_on_image(
                        page_img.image, [(px_rect, translation)]
                    )
                    # Ground truth: burn into the real PDF.
                    st.session_state["v2_pdf"] = render_texts_in_rects(
                        pdf_bytes, PAGE_INDEX, [(rect, translation)]
                    )
                    st.rerun()
        with c2:
            if st.button("やり直す（ステップ1へ）"):
                for k in ("v2_pending", "v2_preview", "v2_pdf"):
                    st.session_state.pop(k, None)
                st.session_state["v2_stage"] = "extract"
                st.rerun()

        # Coordinate check: the PIL preview and the burned PDF should both land
        # exactly where the rectangle was drawn.
        if st.session_state.get("v2_preview") is not None:
            st.image(
                st.session_state["v2_preview"],
                width=img_w,
                caption="画面プレビュー（PIL）。囲った位置に英訳が乗っているか確認",
            )
        if st.session_state.get("v2_pdf"):
            st.download_button(
                "焼き込んだPDFをダウンロード（位置確認用）",
                data=st.session_state["v2_pdf"],
                file_name="annotated_v2.pdf",
                mime="application/pdf",
            )
