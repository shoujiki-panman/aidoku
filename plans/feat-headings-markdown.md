# 見出しをMarkdownとして渡す — 本文の構造を捨てない

Status: 実験中（本測定の条件は変えていない）
関連: [`analysis/probes/check_headings.py`](../analysis/probes/check_headings.py)（見出しの有無を数えた） /
[`analysis/probes/try_follow_prompt.py`](../analysis/probes/try_follow_prompt.py)（同じ形のA/B）

## Why — なぜ要るか

`crawler/htmlutil.py` は h1〜h6 を**レベルつきで取っている**のに、AIへ渡す本文
（`clean_body_text`）は平文で、`#` も階層も無い。`analysis/out/headings_tennyu.json`
のとおり、AIが読んだ58ページに見出しは **717本**あり、1本も無いページは **1枚だけ**。

**構造はサイトの側に有る。捨てているのは読み手（こちら）。**

表については同じことを既にやっている（`table_section()`。表のセルの字は本文にも
入るが、どの見出しの列かは潰れるので、組み直して別枠で渡す）。
**見出しだけが手つかずで残っていた。**

## What — 入れたもの

| | |
|---|---|
| `crawler/htmlutil.py` | `markdown_body()`。本文チャンクに見出しの印を戻す。`NormalizedPage.markdown` として持つ |
| `extractor/fact_extract.py` | `BODY_STRUCTURE`（`flat` / `markdown_headings`）と `body_text()`。**既定は `flat`** |
| `analysis/probes/try_headings_prompt.py` | 本文の渡し方だけを変えたA/B |

**`.text` は1文字も変えていない**（`test_本文の見え方は変えない`）。本測定は動かない。

## この実験で何が言えるか

- **上がったら** — 「区が書いていない」と数えた項目の一部は、**こちらが構造を捨てていたせい**
  だったことになる。AI読は「どこを直せば伝わるか」を示すものなので、
  読み手側の欠陥は自分から先に見つけておく側にある
- **上がらなかったら** — 「見出しは主因ではない」と数字で言える。2.4.4 でやったのと同じ形

**言ってはいけないこと**: ここで拾えた ＝ 区が書いていた。拾えなかった項目が
「書いていない」のか「読めなかった」のかは、この実験では分けない。

## 実測（2026-09-08、キャッシュ済みページ）

Markdown化で増える字は **+28〜+113字（本文の1〜3%）**。`MAX_TEXT_CHARS`（18,000）
から見て誤差で、本文を削らずに入る。足立区の例:

    # 転入届（他の市区町村や海外から足立区に引っ越してきたとき）
    ## 届出場所 / ## 届出期間 / ## お持ちいただくもの
    ### 他の市区町村から足立区へ転入した場合

**見出しがそのまま採点項目の名前になっている**（お持ちいただくもの＝必要書類、
届出期間＝期限、届出場所＝窓口）。

## 既定を切り替えるときにやること（今回はやらない）

1. `measurement.CONDITION_KEYS` に `body_structure` を足す
   — ★足した瞬間、既存の測定が**全部 stale になる**（`tools/stale.py`）。
   `analysis/probes/backfill_condition_keys.py` での backfill と通し直しが要る
2. `evidence_check` の照合を Markdown 側に合わせる
   — いまは平文と突き合わせているので、引用に `## ` が混ざると落ちる可能性がある
3. `tools/stale.py` の `current()` にも足す

**条件を変えるのは、数字が出てから。** 出ないうちに既定を動かすと、
何が効いたのか分からない測定が23区ぶん残る。

## Progress

<!-- 追記のみ。1ステップ1行。失敗も書く。書き直さない -->

- 2026-09-08 `markdown_body()` 実装。`.text` を変えずに `NormalizedPage.markdown` を足した。単体テスト5件追加、`tools/check.sh` 全部緑
- 2026-09-08 実キャッシュ8ページで確認。増える字は +28〜113字。見出しは採点項目名とほぼ一致
- 2026-09-08 `try_headings_prompt.py -p tennyu --limit 8` を実行（8自治体 × 4項目 × 2条件 = 64回）。**結果はまだ出ていない**
