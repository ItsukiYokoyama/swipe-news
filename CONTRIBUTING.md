# 開発に参加する

## 環境を作る

Python 3.11 以上と [uv](https://docs.astral.sh/uv/) (または pip) を使います。

```sh
uv venv --python 3.12
uv pip install -e ".[desktop,dev]"
```

## 動かす

ふだんのデータを汚さないように、データのフォルダを分けて起動できます。

```sh
# Windows (PowerShell)
$env:SWIPE_NEWS_DATA = "$env:TEMP\swipe-news-dev"; .venv\Scripts\python -m swipe_news --port 7871 --no-tray
# macOS / Linux
SWIPE_NEWS_DATA=/tmp/swipe-news-dev .venv/bin/python -m swipe_news --port 7871 --no-tray
```

| 環境変数 | 既定 | 内容 |
|---|---|---|
| `SWIPE_NEWS_DATA` | OS ごとのデータのフォルダ | データ (DB・設定・ログ・モデル) の置き場所 |
| `SWIPE_NEWS_CRAWL_INTERVAL_MIN` | 30 | 巡回の間隔 (分) |
| `SWIPE_NEWS_MAX_NEW_PER_FEED` | 10 | 1 回の巡回でフィードごとに取る記事の上限。0 なら新しい記事を取らない (画面の確認に) |
| `SWIPE_NEWS_RETENTION_DAYS` | 7 | 配信からこの日数を過ぎた記事は消す |
| `SWIPE_NEWS_AI_GENRE` | true | 内蔵 AI でジャンルを判定・好みを学習する |
| `SWIPE_NEWS_CATALOG_URL` | https://ditsuki.com/swipe-news/feeds.json | おすすめの一覧 |

## テストとコードのチェック

```sh
ruff check src tests
python -m pytest
```

テストはモデルも通信も使いません (フィードは `tests/conftest.py` の偽のサーバーから返す)。
push と pull request のたびに GitHub Actions で同じものが動きます (`.github/workflows/ci.yml`)。

画面の動き (カードのドラッグ・キーの長押し・ドパモード) は、ヘッドレス Chrome に PointerEvent / KeyboardEvent を送るスクリプトを
差し込み、`--dump-dom` で結果を読んで確かめています。

## 画面の CSS (tailwind.css) を作り直す

`index.html` や `app.js` で新しい Tailwind のクラスを使ったら、`src/swipe_news/static/tailwind.css` を作り直してコミットします
(利用者が Node.js を入れなくても、オフラインでも画面が崩れないように、作ったものを同梱しています)。

```sh
cd frontend
npx tailwindcss@3.4.16 -c tailwind.config.js -i input.css -o ../src/swipe_news/static/tailwind.css --minify
```

Node.js が無ければ、[Tailwind の Releases](https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.16) の
単体の実行ファイル (standalone CLI) を `npx tailwindcss@3.4.16` の代わりに使えます。

## Windows 版の zip を作る

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-portable.ps1 -ModelDir <model_int8.onnx と tokenizer.json のフォルダ>
```

`dist\SwipeNews-<版>-windows.zip` ができます。python.org の埋め込み用 Python (版とハッシュを固定し、署名も確かめる) と、
ライブラリ・アプリ・モデル・拡張機能を 1 つのフォルダにまとめます。独自の exe は作りません
(署名の無い exe はセキュリティソフトに隔離されやすいため)。

- `tar.exe` は System32 のものをフルパスで呼ぶ (Git の GNU tar が先に見つかると zip にならない)
- .pyc を同梱の版で作るため `uv pip install --python 3.12` にしている
- PowerShell 5.1 で読めるように、`.ps1` は BOM 付きの UTF-8 で保存する

## おすすめのメディアの一覧

`catalog/feeds.json` を編集します。形式と載せる基準は [catalog/README.md](catalog/README.md) にあります。
`tests/test_feeds.py` が、一覧がアプリの形式とジャンルに合っているかを確かめます。

## コードの書き方

- コード中のコメント・docstring・ログは英語、画面の文言と利用者に見せるエラーメッセージは日本語です
- 記事の文面を改変・要約する機能は入れません。利用者が規約を確かめずにメディアを取得するような機能も入れません
