# #67 Page Normalizerを仕様どおりにする計画

## 目的

HTMLを本文だけへ潰さず、ページの名前・説明・見出し構造・更新日時を
後段が機械的に使える形で保存する。

## 契約

- `htmlutil.parse()` は `NormalizedPage` を返す。
- `NormalizedPage` は既存のリンク・本文・JSON-LD生文字列に加えて、次を持つ。
  - `title`
  - `meta`（`description` と `og:*`）
  - `headings`（文書順の `level` と `text`）
  - JSON-LD内の `dateModified` / `datePublished`
- JSON-LD日時は、object・array・`@graph` の入れ子を再帰的に読む。
  壊れたJSONや文字列でない日時は無視し、生文字列は失わない。
- `FetchResult` は `Last-Modified` / `ETag` を保存する。
  新フィールドは省略可能にし、既存の `*.meta.json` は変更せず読める。
- crawlerの候補出力にも正規化結果とHTTP更新情報を残す。
- `parse()` のtuple互換shimは作らず、全呼び出し元を属性参照へ更新する。
  古いAPIと新しいAPIが併存して理解を難しくしないため。

## 実装

1. title・meta・heading・JSON-LD blockをそれぞれ独立して収集する。
2. 空白正規化とJSON-LD日時抽出を小さなpure functionへ分ける。
3. `PoliteFetcher` が成功レスポンスの2ヘッダーをcache metadataへ保存する。
4. crawler出力へ正規化済みメタデータを運ぶ。
5. extractor・experiment・源内アプリを新しい戻り値へ移行する。
6. METHOD / STATUS / READMEの実態説明を同期する。

## テスト

- headの文字列は本文へ混ぜず、title・description・ogだけ取れる
- h1〜h6の順序・level・入れ子要素内の文字列を保持する
- link・本文・JSON-LD生文字列の既存挙動を保つ
- object・array・`@graph`の日時を取り、壊れたJSONを無視する
- `Last-Modified` / `ETag` を保存し、cache hitでも保持する
- 新フィールドの無い旧cache metadataを読める
- crawlerの成功結果に正規化情報が残る
- edge / error caseを含むunit testと全CI相当を通す

## 完了条件

取得済みHTMLとHTTPレスポンスから、issue #67の5種類の情報を再クロール後の
discovery JSONで復元でき、古いcache metadataも例外なく読める。

## 実施結果

- `NormalizedPage` へtitle・meta・見出し・JSON-LD日時を追加し、全呼び出し元を移行した。
- `Last-Modified` / `ETag` をcache metadataとdiscovery JSONへ保存するようにした。
- #55・#56を含む最新mainへの統合後、Python 217件・Node 78件、
  合計295件の全テストが通過した。
- 実cache 1,759 HTMLで旧実装と比較し、本文・リンク先/件数・JSON-LD生文字列・
  既存の非空リンク文字列に差がないことを確認した。旧cache metadata 1,862件も
  全件読めた。
- 空だった画像リンク文字列だけは、画像の`alt`を使うよう改善した。
