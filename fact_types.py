"""fact_type（住民が知りたい事実の種類）の唯一の定義を読む。

**4項目の文字列を、このファイルと fact_types.json 以外に書かない。**

2026-08-16 時点で12か所以上に直書きされ、英語IDが2系統・日本語が2表記に
割れていた。Failure を横に繋げられない原因だったので集約する。

既存の出力JSONのキー名は変えていない。変えると web/data/*.json と
公開4画面が同時に壊れるため、ここは「どの表記が何を指すか」の対応表に徹する。

    from fact_types import EXTRACTOR_KEYS, DISPLAY_KEYS, FIX_TEXT, by_id
"""

from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).parent / "fact_types.json"
_DOC = json.loads(_PATH.read_text(encoding="utf-8"))

VERSION: str = _DOC["version"]
FACT_TYPES: list[dict] = _DOC["fact_types"]
EXTRA_MEASURES: list[dict] = _DOC["extra_measures"]

# extractor / prompt.md / scorer が使うキー（出力JSONのキー名でもある）
EXTRACTOR_KEYS: list[str] = [f["extractor_key"] for f in FACT_TYPES]

# 画面と export_dashboard が使うラベル（「窓口/オンライン可否」とスラッシュ入り）
DISPLAY_KEYS: list[str] = [f["display_label"] for f in FACT_TYPES]

# extractor のキー → 画面ラベル
EXTRACTOR_TO_DISPLAY: dict[str, str] = {
    f["extractor_key"]: f["display_label"] for f in FACT_TYPES
}

# 画面ラベル → 処方箋の文。オンライン明示も含む（画面では5項目ぶん出す）
FIX_TEXT: dict[str, str] = {
    **{f["display_label"]: f["fix_hint"] for f in FACT_TYPES},
    **{m["display_label"]: m["fix_hint"] for m in EXTRA_MEASURES},
}

_BY_ID = {f["id"]: f for f in FACT_TYPES}


def by_id(fact_id: str) -> dict:
    """fact_type の id から定義を引く。未知のIDは黙って通さない。"""
    if fact_id not in _BY_ID:
        raise KeyError(f"未知の fact_type: {fact_id}（fact_types.json を見よ）")
    return _BY_ID[fact_id]


def id_of(key: str) -> str:
    """どの表記からでも id を引く。表記ゆれの吸収用。"""
    for f in FACT_TYPES:
        if key in (f["id"], f["label"], f["extractor_key"], f["display_label"],
                   f.get("gatekeeper_key"), f.get("gennai_key")):
            return f["id"]
    raise KeyError(f"どの fact_type にも一致しない表記: {key}")
