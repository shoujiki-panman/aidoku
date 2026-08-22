"""公開データの機械可読な目次（web/data/index.json）を作る。

「AIから叩ける形であるべきだ」と測って回っている当人が、自分のデータには
人間向けの散文（README.md）しか置いていない、という穴を塞ぐためのもの。
AIが最初にこの1枚を読めば、どのファイルに何があり、どこまで測ってあり、
どこからが測っていないのかが分かる。

**説明文は人が書き、数字は必ずファイルから読む。** 件数も生成日時も
手で書かない。書くと、いつか実体とズレて、目次そのものが嘘になる。

    python3 analysis/export_data_index.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "web" / "data"

LICENSE = {
    "id": "CC-BY-4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/deed.ja",
    "attribution": '正直パンマン「AI読（アイドク）」 https://github.com/shoujiki-panman/aidoku',
    "covers": "点数・集計・改善案・到達クリック数・観察記録（このリポジトリが作った部分）",
    "does_not_cover": (
        "自治体サイトの実文。著作権は各自治体にあり、2026-08-18 以降は "
        "fields[].agent_value を空にして配信していない（quote_withheld: true）"
    ),
}

# 全国の市町村1,718 + 特別区23。全国規模での被覆率を正直に出すために持つ。
MUNICIPALITIES_JAPAN = 1741

SCORE_FIELDS = {
    "id": "自治体の識別子（英字）。ファイル間の突き合わせに使う",
    "name": "自治体名",
    "lg_code": "全国地方公共団体コード。並び順の正はこれ（漢字の文字コード順にしない）",
    "total": "100点満点の合計",
    "breakdown": (
        "項目ごとの点。必要書類・窓口/オンライン可否・期限・手数料は "
        "20（読めた）か 0（読めなかった）の2値。オンライン明示だけ "
        "20（明記）/ 10（曖昧）/ 0（記載なし）の3値"
    ),
    "hops": "自治体トップページから、検索エンジンを使わずリンクだけで到達したクリック数",
    "page_url": "実際に採点したページ",
    "fields": "項目ごとの判定（verdict は「読めた」「読めない」）",
    "improvements": "読めなかった項目について、何をどこに書けば読めるようになるか",
    "page_status": "そのページが採点対象として妥当だったか",
    "notes": "判定者（LLM）の所見。散文であり、点の根拠そのものではない",
}


def describe(path: Path, doc: object) -> dict:
    """1ファイルぶんの実測値。ここに手書きの数字を入れない。"""
    raw = path.read_bytes()
    out = {
        "path": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if isinstance(doc, dict) and isinstance(doc.get("generated_at"), str):
        out["generated_at"] = doc["generated_at"]
    return out


def load(name: str) -> object:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def count_at(doc: object, key: str | None) -> int | None:
    if key is None or not isinstance(doc, dict):
        return None
    value = doc.get(key)
    return len(value) if isinstance(value, (list, dict)) else None


def dataset(name: str, title: str, description: str,
            record_path: str | None = None, fields: dict | None = None,
            join: str | None = None) -> dict:
    doc = load(name)
    out = {"id": name.removesuffix(".json"), "title": title, "description": description}
    out.update(describe(DATA_DIR / name, doc))
    n = count_at(doc, record_path)
    if record_path:
        out["records"] = {"path": record_path, "count": n}
    if fields:
        out["fields"] = fields
    if join:
        out["join"] = join
    out["license"] = LICENSE["id"]
    return out


def score_datasets(procs: list[dict]) -> list[dict]:
    out = []
    for p in procs:
        out.append(dataset(
            p["file"],
            f'{p["name"]}の実測（23区）',
            f'東京23区の「{p["name"]}」のページを住民のAIに読ませ、'
            "4項目を読み取れたかを測った結果。",
            record_path="municipalities", fields=SCORE_FIELDS,
            join="municipalities[].id / lg_code で他のファイルと突き合わせる"))
    return out


def coverage(procs: list[dict]) -> dict:
    """どこまで測ってあるか。**測っていない場所を隠さない**のがこの節の目的。"""
    measured = sum(len(load(p["file"])["municipalities"]) for p in procs)
    cells_japan = MUNICIPALITIES_JAPAN * len(procs)
    return {
        "unit": "自治体 × 手続き（1セル）",
        "measured_cells": measured,
        "municipalities": 23,
        "procedures": [p["id"] for p in procs],
        "area": "東京都特別区（23区）のみ",
        "japan": {
            "municipalities": MUNICIPALITIES_JAPAN,
            "cells": cells_japan,
            "measured_ratio": round(measured / cells_japan, 4),
        },
        "note": (
            "測っていない自治体は「読めない」ではなく「まだ調べていない」。"
            "画面でも灰色で区別し、0点とは別に扱う。"
        ),
    }


GOLDEN_DIR = Path(__file__).resolve().parent.parent / "scorer" / "golden"


def calibration(procs: list[dict]) -> dict:
    """較正（人手の正解データ）がどこまであるか。

    ★ここを黙っていると、時系列を見た人が「点が動いた＝サイトが変わった」と
      読んでしまう。較正の無い手続きでは、それは判定器が動いただけかもしれない。
    """
    have = {}
    for proc in procs:
        path = GOLDEN_DIR / f'{proc["id"]}.csv'
        if not path.exists():
            have[proc["id"]] = {"rows": 0, "municipalities": 0}
            continue
        rows = [r for r in path.read_text(encoding="utf-8-sig").splitlines()[1:]
                if r.strip() and not r.startswith("#")]
        munis = {r.split(",", 1)[0] for r in rows}
        have[proc["id"]] = {"rows": len(rows), "municipalities": len(munis)}
    missing = [k for k, v in have.items() if v["rows"] == 0]
    return {
        "what": "人手で作った正解データ。判定器のぶれを測るために使う",
        "by_procedure": have,
        "missing": missing,
        "note": (
            "較正の無い手続きでは、点が動いたときに「サイトが変わった」と"
            "「判定器が変わった」を区別できない。差を見るときはここを先に見ること。"
        ) if missing else "全手続きに較正がある",
    }


def model_label(run: dict) -> str:
    """モデル名。記録が無い回を "None/None" と出さない（Python の見た目が漏れる）。"""
    name, version = run.get("model"), run.get("model_version")
    if not name and not version:
        return "未記録"
    return f'{name or "未記録"}/{version or "未記録"}'


def provenance(procs: list[dict]) -> dict:
    """どの条件で測ったか。記録が無いなら、無いと言う。"""
    per = {}
    for proc in procs:
        m = load(proc["file"]).get("measurement") or {}
        # runs[] は自治体ごとの明細で、ここに全部並べると目次が埋まる。
        # 目次に要るのは「何回ぶんあるか」と「どのモデルだったか」だけ。
        runs = m.get("runs") or []
        models = sorted({model_label(r) for r in runs})
        per[proc["id"]] = {
            "recording_status": m.get("recording_status"),
            "runs": len(runs),
            "models": models,
            "conditions": {k: v for k, v in m.items()
                           if v not in (None, [], "")
                           and k not in ("recording_status", "runs")},
        }
    unrecorded = [k for k, v in per.items() if v["recording_status"] != "recorded"]
    out = {
        "condition_keys": [
            "measurement_version", "prompt_version", "follow", "max_follow",
            "max_depth", "beam", "max_fetches", "max_text_chars", "max_links",
            "model", "model_version",
        ],
        "by_procedure": per,
        "unrecorded": unrecorded,
    }
    if unrecorded:
        out["note"] = (
            "いま配信している実測は、測定条件（モデル・プロンプト版・探索の上限）が"
            "記録されていない回のもの。したがって過去との差が出ても、"
            "サイトが変わったのか判定器が変わったのかを断定できない。"
            "history/ の差分もこの場合、自治体のせいにしない。"
        )
    return out


def build() -> dict:
    procs = load("procedures.json")["procedures"]
    return {
        "_about": (
            "AI読（アイドク）の公開データの目次。人間向けの説明は README.md、"
            "機械向けはこのファイル。まずここを読めば、どこに何があり、"
            "どこまで測ってあるかが分かる。"
        ),
        "name": "AI読（アイドク）公開データ",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "homepage": "https://shoujiki-panman.github.io/aidoku/web/",
        "repository": "https://github.com/shoujiki-panman/aidoku",
        "base_url": "https://shoujiki-panman.github.io/aidoku/web/data/",
        "publisher": {
            "name": "正直パンマン（個人）",
            "official": False,
            "note": "行政機関の公式発表ではない。個人による第三者調査。",
        },
        "license": LICENSE,
        "provenance": provenance(procs),
        "calibration": calibration(procs),
        "coverage": coverage(procs),
        "self_description": {
            "path": "index.json",
            "note": "この目次自身。datasets[] の path は base_url からの相対。",
        },
        "skill": {
            "path": "../skill/SKILL.md",
            "note": (
                "このデータを使って行政の質問に答えるときの手順。"
                "読み取れなかった項目を推測で埋めないための指示が入っている。"
            ),
        },
        "datasets": datasets(procs),
    }


def datasets(procs: list[dict]) -> list[dict]:
    out = [dataset(
        "procedures.json", "手続きの一覧",
        "測った3手続きと、その平均点・満点の数・0点の数。"
        "procedures[].file が各手続きの実測ファイル名。",
        record_path="procedures")]
    out += score_datasets(procs)
    out += [
        dataset("barriers.json", "AIがつまずいた段差",
                "点数ではなく、どこで読めなくなったかと、何を変えるとどれだけ改善するか。",
                record_path="barriers",
                join="municipality と procedure で scores-*.json と突き合わせる"),
        dataset("journeys.json", "AIの道のり",
                "自治体トップページから、AIがどのリンクを選んで、どこで力尽きたか。"
                "選択の点数の内訳まで入っている。",
                record_path="journeys"),
        dataset("site-status.json", "ページの見張り",
                "採点済みページが変わっていないかの毎日の確認（LLMは呼ばない）。"
                "変わっていれば測り直しが必要という意味で、悪くなったという意味ではない。",
                record_path="items"),
        dataset("archive.json", "過去の版",
                "Internet Archive にいつの版が残っているか。HTMLの写しは持っていない。",
                record_path="pages"),
        dataset("tokyo23.json", "23区の境界",
                "地図用のSVGパス。出典は『歴史的行政区域データセットβ版』（CODH作成）で、"
                "この部分のライセンスは CC BY 4.0（作成者は当方ではない）。",
                record_path="wards"),
        dataset("fact-types.json", "測っている項目の定義",
                "4項目それぞれについて、何を必須要素とみなすか。判定の基準そのもの。",
                record_path="fact_types"),
    ]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DATA_DIR / "index.json")
    args = ap.parse_args()
    doc = build()
    args.out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = len(doc["datasets"])
    print(f"{args.out}: {n}件 / 被覆 {doc['coverage']['measured_cells']}セル "
          f"/ {args.out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
