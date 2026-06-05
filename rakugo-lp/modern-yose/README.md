# Modern Yose — 落語会LPテンプレート

黒・白・朱のクールな配色で、寄席・定例落語会・複数出演者の会に対応した単ファイルHTMLテンプレートです。

## ファイル構成

```
modern-yose/
├── index.html    ← このファイル1本だけで動作します
└── README.md     ← このファイル
```

## カスタマイズ手順

`index.html` をテキストエディタで開き、先頭付近の `EDIT HERE` ブロック内の `EVENT` オブジェクトを書き換えるだけで公開できます。

```js
const EVENT = {
  nav_title:      "第○回 ○○落語会",      // ナビに表示する短い公演名
  kicker:         "第○回",               // ヒーローの小見出し
  title:          "○○落語会",            // メインタイトル
  title_em:       "",                    // タイトル中で金色にしたい文字列（なければ空）
  subtitle:       "〜 キャッチコピー 〜",
  date:           "2026年○月○日（○）",
  open_time:      "開場 18:00",
  start_time:     "開演 18:30",
  end_time:       "終演予定 20:30",
  venue:          "○○ホール 大ホール",
  address:        "東京都○○区○○1-2-3",
  venue_access:   "○○線 ○○駅 徒歩5分",
  status:         "on_sale",             // 下記ステータス一覧を参照
  ticket_url:     "https://peatix.com/...",
  peatix_url:     "https://peatix.com/...",  // 不要なら "" に
  tiget_url:      "",
  passmarket_url: "",
  form_url:       "",
  map_src:        "",                    // Google Maps 埋め込みURL
  organizer:      "○○落語会 主催",
  contact:        "info@example.com",
};
```

### ステータス一覧

| 値 | 表示 | 色 |
|---|---|---|
| `on_sale` | 予約受付中 | 緑 |
| `pre_sale` | 発売前 | 白枠 |
| `few_left` | 残席わずか | オレンジ |
| `sold_out` | 満席 | グレー（予約ボタン無効化） |
| `day_ticket` | 当日券あり | 青 |

### 番組表の編集

`#program` セクション内の `.program-item` を複製・削除して使います。
`rank-shinuchi` / `rank-futatume` / `rank-zenza` クラスで真打・二つ目・前座のバッジが変わります。

### 出演者の編集

`#performers` セクション内の `.performer-card` を増減します。
写真を使う場合は `<img>` タグのコメントを外し、`performer-photo-placeholder` の div を削除してください。

### Google Maps の埋め込み

1. Google Maps で会場を検索
2. 共有 → 地図を埋め込む → HTML をコピー
3. `<iframe src="..."` の `src=""` の中身だけを `map_src` に貼り付け

### 写真背景（ヒーロー）

`index.html` 内の `Option B` コメント部分のコメントを外し、`hero.jpg` を同じフォルダに置いてください。

## 動作環境

ブラウザのみで動作します。サーバー・Node.js 等は不要です。
外部依存は Google Fonts のみです（オフライン環境ではシステムフォントにフォールバック）。
