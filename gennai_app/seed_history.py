"""デモ用: 23区ぶんの診断を実行して、源内の「利用履歴」に並べる。

点の低い順に投げる。源内の履歴は新しい順に出るので、画面では
100点（港区）→ 0点（世田谷・中央・台東・墨田・荒川）の並びになる。
＝源内の中にランキングが立ち上がる。

    python3 seed_history.py            # 既定 http://127.0.0.1:8787
    STUB_URL=http://127.0.0.1:8787 python3 seed_history.py
"""

from __future__ import annotations

import glob
import json
import os
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STUB = os.environ.get("STUB_URL", "http://127.0.0.1:8787")
CLARITY = {"明記": 20, "曖昧": 10}


def main() -> None:
    rows = []
    for f in sorted(glob.glob(str(REPO / "extractor" / "out" / "extract_*_tennyu.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if d.get("municipality_id") == "hachioji":  # 市部は23区の一覧から外す
            continue
        url = (d.get("page") or {}).get("url")
        if not url:
            continue
        found = sum(1 for v in d.get("items", {}).values() if v.get("found"))
        score = found * 20 + CLARITY.get(d.get("online_clarity", ""), 0)
        rows.append((score, d["municipality"], url))

    rows.sort()  # 低い順に投げる → 履歴では高い順に見える
    ok = 0
    for score, name, url in rows:
        body = json.dumps({"inputs": {"url": url}}).encode("utf-8")
        req = urllib.request.Request(f"{STUB}/exapps/invoke", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=30).read()
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  失敗 {name}: {e}")
        time.sleep(0.05)

    print(f"{ok}/{len(rows)}区を履歴に積んだ")
    if rows:
        print(f"  最高: {rows[-1][1]} {rows[-1][0]}点 / 最低: {rows[0][1]} {rows[0][0]}点")


if __name__ == "__main__":
    main()
