# deck — プレゼン資料（16:9）

作品提出フォーム 5-1 に提出するスライド。

| ファイル | |
|---|---|
| `index.html` | ソース。数値は実測データから生成した値を直書き |
| `AI読_プレゼン資料.pdf` | **提出物**。6ページ・1200×675px（16:9）・約0.9MB |

## 作り直す

```bash
cd deck
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --no-pdf-header-footer --print-to-pdf=AI読_プレゼン資料.pdf --virtual-time-budget=4000 index.html
```

## 数値を実データと突き合わせる（必ずやる）

スライド4のランキングは手打ちではなく、実測から生成した値。
更新したら必ず `extractor/out/*.json` と突き合わせて確認すること。
一度、新宿区を20点と書いていた（実測40点）のを、この照合で発見した。

```bash
python3 - <<'PY'
import json, glob, re
from pathlib import Path
CL={"明記":20,"曖昧":10,"記載なし":0}
real={}
for f in sorted(glob.glob("../extractor/out/extract_*_tennyu.json")):
    d=json.load(open(f))
    if d["municipality_id"]=="hachioji": continue
    n=sum(1 for v in d.get("items",{}).values() if v.get("found"))
    real[d["municipality"].replace("区","")]=n*20+CL.get(d.get("online_clarity",""),0)
m=re.search(r"const D=\[(.*?)\];", Path("index.html").read_text(encoding="utf-8"), re.S)
for a,b in re.findall(r'\["([^"]+)",(\d+)\]', m.group(1)):
    k=a.replace("区","") if a!="港区" else "港"
    r=real.get(k)
    if r is None or r!=int(b): print(f"⚠️ {a}: デッキ{b} / 実測{r}")
else: print("照合完了")
PY
```
