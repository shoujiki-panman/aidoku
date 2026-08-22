"""点数の履歴を追記で残し、2時点の差を出す。

**なぜ要るか**: これまで `web/data/scores-*.json` は毎回上書きで、過去の値を持つキーが
1つも無かった。履歴は実質 git のコミットにしか残らず、「前回から良くなったか」を
画面から言えなかった。

**設計で一番大事なこと**: 差を出すことと、差の原因を言うことを分ける。

    点数が 40 → 60 に動いた。
      → サイトが直ったのか？
      → それともこちらの測り方（モデル・プロンプト・探索幅）が変わったのか？

`measurement.py` の `measurement_signature` が一致し、両方とも条件が記録されている
ときだけ「差はサイト側」と言ってよい。それ以外は数字は出すが原因は unknown にする。
METHOD.md §4-8 のとおり、既存69マスは条件が復元できない（legacy_unknown）ので、
いまの実データ同士の比較は必ず unknown になる。**それが正しい。**

保存先は JSON Lines（1行1スナップショット）。追記だけで、過去行は書き換えない。
"""

from __future__ import annotations

import json
from pathlib import Path

from measurement import measurement_signature

SCHEMA_VERSION = "aidoku-history-1.0"

# 履歴に残す1区ぶんの項目。画面に出す最小限だけ持つ（生の引用は持たない）。
MUNI_KEYS = ("id", "name", "total", "breakdown", "hops")


def _page_status_code(muni: dict) -> str | None:
    status = muni.get("page_status")
    return status.get("code") if isinstance(status, dict) else None


def snapshot_from_doc(doc: dict, recorded_at: str) -> dict:
    """scores-*.json 1本から、履歴1行ぶんを作る。Pure Function。"""
    if not isinstance(doc, dict):
        raise ValueError("scores ドキュメントが dict でない")
    measurement = doc.get("measurement")
    if not isinstance(measurement, dict):
        raise ValueError("measurement が無い")
    try:
        signature = measurement_signature(measurement)
    except KeyError as exc:
        raise ValueError(f"measurement に条件キーが足りない: {exc}") from exc

    munis = []
    for m in doc.get("municipalities", []):
        if not isinstance(m, dict) or not m.get("id"):
            continue
        row = {k: m.get(k) for k in MUNI_KEYS}
        row["page_status"] = _page_status_code(m)
        munis.append(row)

    return {
        "schema": SCHEMA_VERSION,
        "recorded_at": recorded_at,
        "generated_at": doc.get("generated_at"),
        "procedure_id": doc.get("procedure_id"),
        "procedure": doc.get("procedure"),
        "measurement_signature": signature,
        "recording_status": measurement.get("recording_status"),
        "summary": doc.get("summary"),
        "municipalities": munis,
    }


def load_snapshots(path: str | Path, procedure_id: str | None = None) -> list[dict]:
    """壊れた行は黙って飛ばす。履歴は「読めるところまで読む」ほうが安全。"""
    p = Path(path)
    if p.is_dir():
        raise ValueError(f"履歴の置き場がディレクトリになっている: {p}")
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if procedure_id is not None and row.get("procedure_id") != procedure_id:
            continue
        out.append(row)
    return out


SCORE_KEY = ("procedure_id", "generated_at")
SITE_STATUS_KEY = ("checked_at",)


def append_snapshot(path: str | Path, snapshot: dict,
                    key_fields: tuple[str, ...] = SCORE_KEY) -> bool:
    """追記する。key_fields が同じ行が既にあれば書かない。

    測り直していないのに export を2回流しても、履歴が水増しされないようにする。
    キーを引数にしているのは、点数（procedure_id + generated_at）と
    見張り（checked_at）で「同じ回」の意味が違うため。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    key = tuple(snapshot.get(k) for k in key_fields)
    if all(v is None for v in key):
        raise ValueError(f"重複判定のキーが全て空: {key_fields}")
    for row in load_snapshots(p):
        if tuple(row.get(k) for k in key_fields) == key:
            return False
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def attribution(before: dict, after: dict) -> tuple[str, str]:
    """差の原因を言ってよいか。('site' | 'unknown', 理由) を返す。"""
    if before.get("measurement_signature") != after.get("measurement_signature"):
        return "unknown", "測定条件が違う（モデル・プロンプト・探索幅のいずれかが変わっている）"
    if before.get("recording_status") != "recorded" or after.get("recording_status") != "recorded":
        return "unknown", "測定条件が記録されていない期間を含む（legacy_unknown）"
    return "site", "測定条件が同じなので、差はサイト側の変化と見てよい"


def diff(before: dict, after: dict) -> dict:
    """2時点の差。**数字は必ず出し、原因の断定だけを attribution に委ねる。**"""
    how, reason = attribution(before, after)
    prev = {m["id"]: m for m in before.get("municipalities", []) if m.get("id")}
    rows = []
    for m in after.get("municipalities", []):
        mid = m.get("id")
        if not mid:
            continue
        old = prev.get(mid)
        old_total = old.get("total") if isinstance(old, dict) else None
        new_total = m.get("total")
        delta = (new_total - old_total
                 if isinstance(old_total, int) and isinstance(new_total, int) else None)
        rows.append({
            "id": mid,
            "name": m.get("name"),
            "before": old_total,
            "after": new_total,
            "delta": delta,
            "page_status_before": old.get("page_status") if isinstance(old, dict) else None,
            "page_status_after": m.get("page_status"),
            "is_new": old is None,
        })
    moved = [r for r in rows if isinstance(r["delta"], int) and r["delta"] != 0]
    return {
        "procedure_id": after.get("procedure_id"),
        "from": before.get("generated_at"),
        "to": after.get("generated_at"),
        "attribution": how,
        "attribution_reason": reason,
        "changed_count": len(moved),
        "municipalities": rows,
    }


def site_status_snapshot(report: dict) -> dict:
    """見張りの結果1回ぶんを、履歴1行にする。Pure Function。

    68件すべてではなく **変化のあったものだけ** 残す。毎日1行×365日でも軽い。
    「変化なし」は summary の数で足りる。
    """
    if not isinstance(report, dict):
        raise ValueError("見張りの結果が dict でない")
    items = report.get("items")
    changed = [
        {
            "municipality_id": i.get("municipality_id"),
            "procedure_id": i.get("procedure_id"),
            "gone": bool(i.get("gone")),
            "reason": i.get("reason"),
        }
        for i in (items if isinstance(items, list) else [])
        if isinstance(i, dict) and i.get("changed") is True
    ]
    return {
        "schema": SCHEMA_VERSION,
        "checked_at": report.get("checked_at"),
        "summary": report.get("summary"),
        "changed": changed,
    }


def series(snapshots: list[dict], municipality_id: str) -> list[dict]:
    """1区ぶんの時系列。画面の折れ線はこれを描く。"""
    out = []
    for snap in snapshots:
        for m in snap.get("municipalities", []):
            if m.get("id") == municipality_id:
                out.append({
                    "generated_at": snap.get("generated_at"),
                    "total": m.get("total"),
                    "page_status": m.get("page_status"),
                    "measurement_signature": snap.get("measurement_signature"),
                    "recording_status": snap.get("recording_status"),
                })
                break
    return out
