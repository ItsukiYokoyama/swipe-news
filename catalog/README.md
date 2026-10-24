# おすすめのメディアの一覧 (catalog/feeds.json)

アプリの「メディア」→「おすすめから追加」は、この一覧を
**https://ditsuki.com/swipe-news/feeds.json** から読み込みます
(環境変数 `SWIPE_NEWS_CATALOG_URL` で別の場所にできます)。
このフォルダの `feeds.json` が元のファイルです。更新したら ditsuki.com の同じ場所に置き直してください。

一覧は、Swipe News の作者が独自に調べた「RSS が公開されていて、robots.txt でフィードと記事ページの取得が拒否されていない」
メディアです。**一覧に載っていることは、各メディアが利用を許可していることを意味しません。**
アプリは、利用者が「個人で読む目的に限ること」「そのメディアの利用規約を読んで守ること」を確かめてからでないと追加しません。

## 形式

```json
{
  "format": "swipe-news-catalog",
  "version": 1,
  "updated": "2026-10-24",
  "notice": "一覧の注意書き",
  "feeds": [
    {
      "id": "rss-itmedia-co-jp-rss-2-0-aiplus-xml",
      "name": "ITmedia AI+",
      "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml",
      "genre": "AI",
      "mixed": false,
      "site_url": "https://www.itmedia.co.jp/aiplus/",
      "terms_url": "https://corp.itmedia.co.jp/media/rss_condition/",
      "note": "RSS 利用条件の要点など",
      "checked": "2026-10-20"
    }
  ]
}
```

| 項目 | 必須 | 内容 |
|---|---|---|
| `format` / `version` | ○ | `swipe-news-catalog` / `1`。形式を変えるときは `version` を上げ、アプリの `feeds.CATALOG_VERSION` も合わせる |
| `id` | ○ | 一覧の中で重ならない ID。一度決めたら変えない (追加済みかどうかの判定に使う) |
| `name` | ○ | カードに出典として出る名前 |
| `url` | ○ | RSS / Atom フィードの URL (http / https) |
| `genre` | ○ | 小ジャンル。`src/swipe_news/genres.yaml` の名前のどれか (違う項目はアプリが読み飛ばす) |
| `mixed` | | `true` なら総合系 (AI がジャンルを自由に振り分ける) |
| `site_url` | | メディアのサイト。無ければフィードに書かれたものを使う |
| `terms_url` | | 利用規約・RSS の利用条件のページ。見つかったものだけ書く |
| `note` | | 利用条件の要点など、追加する人に知ってほしいこと |
| `checked` | | RSS・robots.txt・更新が続いていることを確かめた日 |

記事の画像 (og:image) を表示するかは、一覧では決めません (アプリでは既定でオフ。利用者が規約を確かめてからメディアごとにオンにする)。

## 載せる基準

- RSS / Atom フィードが公開されていて、更新が続いている
- robots.txt で、フィードと記事ページの取得が拒否されていない
- 有料会員向けの記事が中心ではない
- 官公庁・NHK は載せない (0.3 で外した方針のまま)

規約は変わるので、追加・見直しのときは各メディアの利用規約を読み直し、`checked` を更新してください。

`tests/test_feeds.py` が、この一覧がアプリの形式とジャンルに合っているかを確かめます。
