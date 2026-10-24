# 変更履歴

## 0.4.0 (2026-10-24)

公開に向けて、ソースの構成を整理しました。

### 追加
- 取得するメディアの設定 (画面の「メディア」): おすすめの一覧 (https://ditsuki.com/swipe-news/feeds.json) から追加、
  RSS やサイトの URL を入れて追加、ジャンル・総合系・記事の画像・取得するかの変更、外す
- 追加するたびに「個人で使うこと・利用規約を読んだこと」の確認を必須に
- 初めて起動したときに、メディアの追加を案内
- 自動テスト (pytest)、コードのチェック (ruff)、GitHub Actions
- LICENSE (GPL-3.0-or-later)、CONTRIBUTING.md、docs/ARCHITECTURE.md

### 変更
- パッケージ名を `news` から `swipe_news` に、フォルダを `src/swipe_news/` に (起動は `python -m swipe_news` / `swipe-news`)
- 初期設定のメディアを空に (0.3 のデータのフォルダの `feeds.yaml` は、初回の起動でそのまま取り込む)
- 記事の画像 (og:image) は、メディアごとに既定でオフ
- 画面の CSS (Tailwind) と QR コードのライブラリを CDN から読むのをやめ、Tailwind は作った CSS を同梱 (オフラインでも崩れない)
- 画面を index.html / app.js / style.css に分けた
- 環境変数の名前に `SWIPE_NEWS_` を付けた
- DB のスキーマに版を付け (`PRAGMA user_version`)、0.3 の DB から自動で移る

### 削除
- AI 要約 (Ollama)。対象のメディアが無く、記事の文面を加工しない方針のため
- Docker 版、`install-windows.ps1` (Windows は zip 版に一本化)
- スマホから見る機能 (LAN への公開・QR コード)。PC で使うアプリにした
- 使っていなかった API (`/api/sources` `/api/news/kept` `/api/stats` `/api/categories`) と、0.3 までの「キープ」「閲覧済み」の操作
  (記録は「開く」として傾向と学習に残る)

## 0.3.0 (2026-10-23)
- ドパモード、Windows 版の zip (Python ごと同梱)
