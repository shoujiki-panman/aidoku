#!/bin/zsh
# 測定条件が古い区を測り直し、公開データまで作り直す。**止まった所から再開できる。**
#
# なぜ要るか: 手順が5つに分かれていて、毎回どこまで進んだかを人が覚えていた。
# 途中で利用上限に当たることもあり、そのたび残りを数え直していた。
#
#   ① 残っている区を数える（tools/stale.py・**条件ひとまとまり**で見る）
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

python3 tools/stale.py > /tmp/aidoku-todo.txt
left=$(wc -l < /tmp/aidoku-todo.txt | tr -d ' ')
echo "① 測り直しが要る: ${left}組（自治体×手続き。24自治体×3手続き＝72組が満数）"
if [ "${1:-}" = "--check" ]; then
  python3 tools/stale.py --why
  exit 0
fi

# ★続けて失敗したら止める。利用上限に当たると `claude -p failed (rc=1)` が延々出て、
#   残り61組ぶん空振りした（実測）。**失敗を積み上げても意味がない。**
LIMIT=3
echo "② 測り直す（1組ずつ・落ちても失うのは1組）"
fails=0
while read -r m p; do
  [ -z "$m" ] && continue
  printf '   %-12s %-10s ' "$m" "$p"
  line=$(python3 extractor/extract.py -m "$m" -p "$p" --follow 2>&1 | tail -1)
  echo "$line"
  case "$line" in
    *"claude -p failed"*|*RuntimeError*) fails=$((fails + 1)) ;;
    *) fails=0 ;;
  esac
  if [ "$fails" -ge "$LIMIT" ]; then
    echo "   ★${LIMIT}連続で失敗した。利用上限の可能性が高いので止める。"
    echo "   残りは tools/run_pipeline.sh でそのまま再開できる。"
    break
  fi
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
