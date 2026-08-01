#!/bin/bash
# 実測から作った「整った答え」をKVへ投入する。
# 先に  node build_answers.mjs  を実行しておくこと。
# 招待メールが届いて wrangler login を済ませてから使う。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f answers/_index.json ]; then
  echo "answers/_index.json がありません。先に node build_answers.mjs を実行してください。" >&2
  exit 1
fi

node -e '
const idx = require("./answers/_index.json");
for (const r of idx) console.log(`${r.key}\t${r.file}`);
' | while IFS=$'\t' read -r key file; do
  echo "put ${key}"
  npx wrangler kv key put --binding=ANSWERS "$key" --path "answers/${file}" --remote
done

echo "完了: $(node -e 'console.log(require("./answers/_index.json").length)') 件"
