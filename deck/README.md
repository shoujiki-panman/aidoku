# deck — プレゼン資料（16:9）

作品提出フォーム 5-1 に提出するスライド。

| ファイル | |
|---|---|
| `index.html` | ソース。数値は実測データから生成した値を直書き |
| `AI読_プレゼン資料.pdf` | **提出物**。7ページ・1200×675pt（16:9）・約1.8MB（上限100MB） |

`captures/` の実画面キャプチャ（`cap_map.png` / `poster.png` / `cap_journey.png`・各1600×900）を
スライド3・5に埋め込んでいる。**合成はしない。** `.shot` は CSS で原寸の一部を切り出しているだけで、
拡大・加工はしていない（`transform:scale()` は縮小方向のみ）。切り出し位置を変えたら、
PDFを作り直して**全ページを画像で見る**こと。

## 作り直す

```bash
cd deck
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --no-pdf-header-footer --print-to-pdf=AI読_プレゼン資料.pdf --virtual-time-budget=6000 index.html
```

## 溢れていないか確かめる（必ずやる）

**本文を足すと、黙ってフッターの下に潜る。**過去に一度やった。
目視だけに頼らず、まず機械で測る。

```bash
pdftoppm -r 100 -png "AI読_プレゼン資料.pdf" /tmp/deckpng/p   # 全ページを画像にして目で見る
```

本文の下端とフッターの間の余白は、Playwright で測れる（`node_modules` は mulmoclaude から借りる）。
**目安は 25px 以上。**1桁になっていたら、フォント差で次回は溢れる。

## 数値を実データと突き合わせる（必ずやる）

スライドの数字は手打ちではなく、実測から生成した値。
更新したら必ず突き合わせて確認すること。
一度、新宿区を20点と書いていた（実測40点）のを、この照合で発見した。

```bash
python3 - <<'PY'
import json, glob, re, subprocess
from pathlib import Path

CL = {"明記": 20, "曖昧": 10, "記載なし": 0}
FIELDS = ["必要書類", "窓口オンライン可否", "期限", "手数料"]
PROCS = ["tennyu", "jidouteate", "sodaigomi"]
html = Path("index.html").read_text(encoding="utf-8")
bad = []

def want(cond, msg):
    if not cond:
        bad.append(msg)

# --- 実測を数え直す（八王子市は23区の集計に混ぜない） ---
cells, scores = {}, {}
for p in PROCS:
    for f in sorted(glob.glob(f"../extractor/out/extract_*_{p}.json")):
        d = json.load(open(f))
        if d["municipality_id"] == "hachioji":
            continue
        it = d.get("items", {})
        got = sum(1 for k in FIELDS if it.get(k, {}).get("found"))
        cells[(d["municipality"], p)] = (got, it)
        if p == "tennyu":
            scores[d["municipality"].replace("区", "") if d["municipality"] != "港区" else "港"] = \
                got * 20 + CL.get(d.get("online_clarity", ""), 0)

# --- スライド4 ランキング ---
m = re.search(r"const D=\[(.*?)\];", html, re.S)
for a, b in re.findall(r'\["([^"]+)",(\d+)\]', m.group(1)):
    k = a.replace("区", "") if a != "港区" else "港"
    want(scores.get(k) == int(b), f"スライド4 {a}: デッキ{b} / 実測{scores.get(k)}")

# --- スライド2 カード（転入届） ---
t4 = [w for (w, p), (g, _) in cells.items() if p == "tennyu" and g == 4]
t0 = [w for (w, p), (g, _) in cells.items() if p == "tennyu" and g == 0]
fee = [w for (w, p), (g, i) in cells.items() if p == "tennyu" and not i.get("手数料", {}).get("found")]
want(t4 == ["港区"] and "港区だけ" in html, f"スライド2 4項目すべて読めた区: 実測{t4}")
want(f"{len(t0)}区" in html and len(t0) == 4, f"スライド2 4項目とも読めなかった区: 実測{len(t0)}区")
want(f"{len(fee)}区" in html and len(fee) == 22, f"スライド2 手数料が読めない区: 実測{len(fee)}区")

# --- スライド4 セル数 ---
want(f"＝{len(cells)}セル" in html, f"スライド4 セル総数: 実測{len(cells)}")
want(f"のは<strong>{sum(1 for v in cells.values() if v[0] == 4)}セル</strong>" in html,
     f"スライド4 4項目そろったセル: 実測{sum(1 for v in cells.values() if v[0] == 4)}")
n0 = sum(1 for v in cells.values() if v[0] == 0)
want(f"のは<strong>{n0}セル</strong>" in html and f"その{n0}セルを" in html,
     f"スライド4 4項目とも読めなかったセル: 実測{n0}")

# --- スライド4 対照実験 / スライド5 測定条件（web/data/pipeline.json = 実ファイルを数えた値） ---
pipe = json.load(open("../web/data/pipeline.json"))
want(f"測定条件{len(pipe['condition_keys'])}項目" in html,
     f"スライド5 測定条件: 実測{len(pipe['condition_keys'])}項目")
ex = {v["key"]: v for v in pipe["experiment"]["variants"]}
n = pipe["experiment"]["trials"]
want(f"{n}回中{ex['before']['all_four']}回 → {n}回中{ex['after']['all_four']}回" in html,
     f"スライド4 対照実験: 実測 {n}回中 before {ex['before']['all_four']} / after {ex['after']['all_four']}")
cf = pipe["counterfactual"]
want(f"{n}回とも37日" in html and "37日" in cf["changed"] and cf["returned_modified"] == n,
     f"スライド4 反実仮想: 実測 {cf['returned_modified']}/{n}・{cf['changed']}")

# --- スライド5 リンクの並べ替え（LLMを呼ばず、保存済みページだけで測る） ---
out = subprocess.run(["python3", "../analysis/probes/check_link_order.py"],
                     capture_output=True, text=True).stdout
g = dict(re.findall(r"^\s{2}(.+?): (\d+)", out, re.M))
cell = g.get("手続き名を含むリンクを、新しく渡せるようになったセル")
tot = g.get("そのリンクの総数")
lost = g.get("逆に渡せなくなった（手続き名つき）")
want(f"{cell}セルに手続き名つきリンク{tot}件" in html and f"渡せなくなったものは{lost}件" in html,
     f"スライド5 並べ替え: 実測 {cell}セル / {tot}件 / 失った{lost}件")

print("\n".join("⚠️ " + b for b in bad) if bad else "照合完了")
PY
```

## 言い回しの禁止事項

`../METHOD.md` §6「言わないと決めていること」を、資料を触るたびに読むこと。
特に **「±2点」は3自治体12行の正解データで測った採点器のぶれ**であって、23区の点数のぶれではない。
同種の言い切り（サンプル数の無い断定）を他に作らないこと。
