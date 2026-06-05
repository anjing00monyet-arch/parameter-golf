# Solo Master — 落語会LPテンプレート（独演会用）

独演会に特化したシングルファイルHTMLテンプレートです。演者写真フルブリードのヒーロー、演者プロフィール・略歴、演目リスト（setlist）を主役に据えた構成です。

## ファイル構成

```
solo-master/
├── index.html      ← このファイル1本だけで動作します
├── README.md       ← このファイル
├── performer.jpg   ← （任意）ヒーロー背景写真
└── profile.jpg     ← （任意）プロフィール写真
```

## カスタマイズ手順

`index.html` 先頭の `EDIT HERE` ブロック内の `EVENT` オブジェクトを書き換えてください。

```js
const EVENT = {
  performer_name:  "山田 太郎",
  performer_reading: "やまだ たろう",
  performer_rank:  "真打",
  performer_school: "○○師匠 門下",

  show_title:  "山田太郎 独演会",
  show_subtitle: "〜 古典の夕べ 〜",
  edition:     "第15回",    // 不要なら ""
  date:        "2026年9月5日（土）",
  open_time:   "開場 18:00",
  start_time:  "開演 18:30",
  end_time:    "終演予定 20:30",
  venue:       "○○ホール",
  ...
};
```

### ステータス一覧

| 値 | 表示 | 色 |
|---|---|---|
| `on_sale` | 予約受付中 | 緑 |
| `pre_sale` | 発売前 | グレー |
| `few_left` | 残席わずか | オレンジ |
| `sold_out` | 満席 | グレー（予約ボタン無効） |
| `day_ticket` | 当日券あり | 青 |

### 演者写真の設定

**ヒーロー背景写真**（オプション）:
1. `performer.jpg` を `index.html` と同じフォルダに置く
2. `index.html` の `<!-- 写真あり版: ↓コメントを外し... -->` の行を探してコメントアウトを外す
3. `<div class="hero-bg-fallback" ...>` の行を削除またはコメントアウト

**プロフィール写真**（オプション）:
1. `profile.jpg` を同じフォルダに置く
2. `<!-- <img src="profile.jpg" alt="演者写真"> -->` のコメントを外す
3. `<div class="performer-photo-placeholder ...">` を削除

### 演目リストの編集

`#setlist` セクション内の `.setlist-item` を複製・削除して使います。
初演や特別演目には `<span class="setlist-new">初演</span>` を追加できます。
未定の演目は `class="setlist-item tba"` にするとグレーアウトします。

### 受賞歴・略歴の編集

`#profile` セクション内の `.profile-bio` と `.profile-awards` を直接編集してください。
受賞歴が不要な場合は `.profile-awards` ブロックごと削除してください。

### Google Maps の埋め込み

`map_src` に Google Maps 埋め込みの `src` 値を貼り付けるだけで地図が表示されます。

## 動作環境

ブラウザのみで動作します。サーバー・Node.js 等は不要です。
外部依存は Google Fonts のみ（オフライン時はシステムフォントへフォールバック）。
