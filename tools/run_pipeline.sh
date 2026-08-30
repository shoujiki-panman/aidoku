#!/bin/zsh
# 測定条件が古い区を測り直し、公開データまで作り直す。**止まった所から再開できる。**
#
# なぜ要るか: 手順が5つに分かれていて、毎回どこまで進んだかを人が覚えていた。
# 途中で利用上限に当たることもあり、そのたび残りを数え直していた。
#
#   ① 残っている区を数える（analysis/status.py と同じ判定）
#   ② 1区ずつ測り直す。1区ごとに結果ファイルが出るので、落ちても失うのは1区
#   ③ 証拠照合（LLMを呼ばない・キャッシュのみ）
#   ④ 公開データを作る。**条件が揃っていない手続きは export が拒む**ので、
#      拒まれたらそれが正しい（黙って古い条件のまま出さない）
#   ⑤ いまの状態を出す
#
# 使い方:
#   tools/run_pipeline.sh            # 全部
#   tools/run_pipeline.sh --check    # 残りを数えるだけ（LLMを呼ばない）
set -u
cd "$(dirname "$0")/.." || exit 1

todo() {
  python3 - <<'PY'
import glob, json, sys
from pathlib import Path
sys.path.insert(0, "extractor"); sys.path.insert(0, ".")
from extract import CLARITY_PROMPT, PROMPT

from measurement import prompt_version
cur = prompt_version([PROMPT, CLARITY_PROMPT])
for proc in ["tennyu", "sodaigomi", "jidouteate"]:
    for f in sorted(glob.glob(f"extractor/out/extract_*_{proc}.json")):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        if (d.get("measurement") or {}).get("prompt_version") != cur:
            print(d["municipality_id"], proc)
PY
}

todo > /tmp/aidoku-todo.txt
left=$(wc -l < /tmp/aidoku-todo.txt | tr -d ' ')
echo "① 測り直しが要る: ${left}区"
[ "${1:-}" = "--check" ] && { cat /tmp/aidoku-todo.txt; exit 0; }

echo "② 測り直す（1区ずつ・落ちても失うのは1区）"
while read -r m p; do
  [ -z "$m" ] && continue
  printf '   %-12s %-10s ' "$m" "$p"
  python3 extractor/extract.py -m "$m" -p "$p" --follow 2>&1 | tail -1
done < /tmp/aidoku-todo.txt

echo "\n③ 証拠照合（LLMは呼ばない）"
python3 analysis/apply_evidence_check.py > /dev/null 2>&1 && echo "   done"

echo "\n④ 公開データを作る（条件が揃っていなければ export が拒む）"
for p in tennyu jidouteate sodaigomi; do
  printf '   %-10s ' "$p"
  python3 analysis/export_dashboard.py -p "$p" --out "web/data/scores-$p.json" 2>&1 | tail -1
done

echo "\n⑤ いまの状態"
python3 analysis/status.py
