"""この数字がどう作られたかを、実ファイルから数えて出す（web/data/pipeline.json）。

**なぜ要るか**: 「優れた技術要素あるんかな、ただのサイトみたいになってしまった」と
言われた。実際にはコードの大半が画面に出ていない。取得・読解・採点の3層も、
測定条件の署名も、対照実験も、画面のどこにも書いていなかった。

**ここで守ること**: 数字は1つも手で書かない。行数もテスト数も較正の件数も、
実ファイルを数えて出す。説明文だけが人の言葉で、数値は全部ファイル由来。

    python3 analysis/export_pipeline.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "pipeline.json"

sys.path.insert(0, str(ROOT))
from measurement import CONDITION_KEYS  # noqa: E402

# 層の説明だけが人の言葉。行数・ファイル数は数える
# (ディレクトリ, 表示名, 説明, テストのある場所)
LAYERS = [
    ("crawler", "取得層", "外部に接続するのはここだけ。robots.txt を守り、"
                          "同じドメインへの間隔を3秒以上あけ、取得したページを保存する。"),
    ("extractor", "読解層", "保存済みのページだけを読む。AIに渡すのは本文とリンク一覧で、"
                            "リンクは手続きに近い順に並べ替えてから上限40件で切る。"),
    ("scorer", "採点層", "AIには点を出させない。項目ごとの有無だけを答えさせ、"
                         "点は決められた配点で機械的に計算する。"),
    ("analysis", "集計・検証", "公開するJSON/CSVを組み立て、出したデータ自身を検査する。"),
    ("gatekeeper", "AI窓口", "デジタル庁OSS「源内」のAIアプリAPI仕様に準拠した独立API。"),
    ("web/assets", "画面", "静的ファイルのみ。ビルドを持たない。", "web"),
]

CODE_SUFFIX = (".py", ".js", ".mjs")


def is_real(path: Path) -> bool:
    """同期ソフトの複製（「 2.js」）と、テスト・キャッシュを除く。"""
    if "__pycache__" in path.parts or "node_modules" in path.parts:
        return False
    return " 2." not in path.name


def count_dir(rel: str, test_dir: str | None = None) -> dict:
    base = ROOT / rel
    files = [p for p in sorted(base.rglob("*")) if p.is_file()
             and p.suffix in CODE_SUFFIX and is_real(p)]
    code = [p for p in files if not p.name.startswith("test_")]
    # 画面のテストは web/assets ではなく web/ の直下にある
    tbase = ROOT / test_dir if test_dir else base
    tests = [p for p in sorted(tbase.glob("test_*")) if p.is_file()
             and p.suffix in CODE_SUFFIX and is_real(p)] if test_dir else \
            [p for p in files if p.name.startswith("test_")]
    lines = sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in code)
    # ★テストの件数は数えない。ファイルごとに check( / ok( と名前が違い、
    #   静的に数えると実行時の件数と合わない。合わない数字は出さない。
    return {"files": len(code), "lines": lines, "test_files": len(tests)}


def layers() -> list[dict]:
    out = []
    for row in LAYERS:
        rel, name, what = row[0], row[1], row[2]
        entry = {"dir": rel, "name": name, "what": what}
        entry.update(count_dir(rel, row[3] if len(row) > 3 else None))
        out.append(entry)
    return out


def experiment() -> dict | None:
    """世田谷の対照実験。ページを書き換えるとAIの答えが変わるか。"""
    files = sorted((ROOT / "experiment" / "out").glob("*.json"))
    if not files:
        return None
    doc = json.loads(files[-1].read_text(encoding="utf-8"))
    variants = {r["variant"]: r for r in doc.get("results", [])}
    return {
        "file": f"../experiment/out/{files[-1].name}",
        "trials": doc.get("trials_per_variant"),
        "model": doc.get("model"),
        "run_at": doc.get("run_at"),
        "variants": [
            {"key": k, "label": variants[k].get("label"),
             "all_four": (variants[k].get("summary") or {}).get("all_four")}
            for k in ("before", "after", "counterfactual") if k in variants
        ],
    }


def counterfactual() -> dict | None:
    """期限を書き換えた版で、AIがどちらの値を返したか。

    ★all_four から「書き換えた値を返した」を推測しない。barriers.json が
      returned_original / returned_modified を実数で持っているので、そこから取る。
    """
    doc = json.loads((ROOT / "web/data/barriers.json").read_text(encoding="utf-8"))
    for barrier in doc.get("barriers", []):
        cf = barrier.get("counterfactual")
        if cf and "returned_modified_37" in cf:
            return {
                "changed": cf.get("changed"),
                "returned_original": cf.get("returned_original_14"),
                "returned_modified": cf.get("returned_modified_37"),
                "conclusion": cf.get("conclusion"),
            }
    return None


def calibration() -> dict:
    doc = json.loads((ROOT / "web/data/index.json").read_text(encoding="utf-8"))
    return doc.get("calibration", {})


def build() -> dict:
    return {
        "_about": "この数字がどう作られたか。行数・テスト数・較正の件数は実ファイルを数えた値。",
        "schema": "aidoku-pipeline-1",
        "layers": layers(),
        "condition_keys": list(CONDITION_KEYS),
        "calibration": calibration(),
        "experiment": experiment(),
        "counterfactual": counterfactual(),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    doc = build()
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(x["lines"] for x in doc["layers"])
    print(f"→ {args.out}（{len(doc['layers'])}層 / 合計{total}行 / 条件{len(doc['condition_keys'])}項目）")


if __name__ == "__main__":
    main()
