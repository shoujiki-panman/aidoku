#!/bin/zsh
# CI と同じものを、手元で1回で回す。
#
# ★なぜ要るか: 手元では `python3 -m unittest discover` を**リポジトリ直下でしか**
#   回していなかった。CI は test_*.py のあるディレクトリを全部探して1つずつ回す。
#   直下の465件はずっと緑で、`./analysis` だけが8日間赤だった。
#   **「テストが通る」の意味が、私とCIで違っていた。** その差をこの1本で無くす。
#
#   tools/check.sh
cd "$(dirname "$0")/.." || exit 1
fail=0

echo "① python（test_*.py のあるディレクトリを全部）"
for d in $(find . -name 'test_*.py' -not -path './node_modules/*' -exec dirname {} \; | sort -u); do
  r=$(python3 -m unittest discover -s "$d" -p 'test_*.py' 2>&1 | grep -E "^(OK|FAILED)" | tr '\n' ' ')
  printf '   %-18s %s\n' "$d" "$r"
  case "$r" in *FAILED*) fail=1 ;; esac
done

echo "\n② lint（ruff）"
if python3 -m ruff check . 2>&1 | tail -1; then :; else fail=1; fi
python3 -m ruff check . >/dev/null 2>&1 || fail=1

echo "\n③ gatekeeper（node）"
for f in gatekeeper/test_*.mjs web/test_*.mjs; do
  [ -e "$f" ] || continue
  if node "$f" >/dev/null 2>&1; then printf '   ok   %s\n' "$f"
  else printf '   ★NG %s\n' "$f"; fail=1; fi
done

echo
if [ "$fail" -eq 0 ]; then echo "全部緑"; else echo "★赤がある"; fi
exit $fail
