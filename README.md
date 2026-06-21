# PDF Annotator

日本語PDFに英訳を赤字でオーバーレイするツール。

建設図面など日本語のPDFをアップロードすると、テキストを抽出して英訳し、選んだ箇所だけを元の位置に赤字で重ねた新しいPDFを書き出す。

## なぜ作ったか

日本語図面を英訳する作業が大量に発生する。これを毎回手作業でやっていてはとても間に合わない。可能な限り自動化したくて作った。

このツールのおかげで翻訳作業が大幅に楽になり、Adobe などの有料ツールに課金する必要もなくなりそう。

## できること

矩形で囲むだけで、**英訳する箇所**と**それを配置する場所**を指定できる。

- 英訳したい日本語を矩形で囲む → 自動で英訳
- 英訳を置きたい場所を矩形で囲む → そこに英訳を配置
- 原文に被らせず、好きな位置に英訳を置けるので仕上がりがきれい

こうした作業がクリックだけで完結するので、手作業に比べて圧倒的に速い。

その他:
- 抽出する日本語の単位は語(word)単位で、矩形に重なる語をまとめて英訳
- 生成したPDFのプレビューとダウンロード
- 「やり直す」でいつでも英訳のやり直しが可能

## セットアップ

```bash
git clone https://github.com/HisashiUehara/pdf_annotator.git
cd pdf_annotator

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

APIキーを `.env` に設定。

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

## 起動

```bash
export $(grep -v '^#' .env | xargs)
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開く。

## 使い方

1. 日本語PDFをアップロード（1ページ目が画像表示される）
2. 【ステップ1】英訳の指示を入力し、英訳したい日本語を矩形で囲む
3. 「選択範囲を英訳」→ 矩形内の日本語が抽出・英訳され、自動で配置モードへ
4. 【ステップ2】英訳を置きたい場所を矩形で囲む
5. 「この位置にPDFを生成」→ プレビュー＆ダウンロード

## 技術スタック

- Streamlit — UI
- pdfplumber — PDFのテキスト・座標抽出
- anthropic (Claude API) — 英訳
- reportlab / pypdf — PDFへの描画・合成
- streamlit-drawable-canvas — 矩形マークアップ
- pypdfium2 — PDFの画像化

## 注意点

- PDFのテキストは外部のAnthropic APIに送信される。機密図面を扱う場合は所属組織の規程に従うこと。
- 画像のみのスキャンPDFは対象外（OCRが別途必要）。
