"""AI読の判定エンジン（本物）。

スタブを置き換える。判定の出どころは2つ:

  measured … 23区の実測結果（2026-07-22にクロール→claude -p で判定済み）を返す。
              即座に返るのでデモ向き。値は実測そのもの（作っていない）。
  live     … 未知のURLは、その場で取得して claude -p で判定する。
              1回30〜60秒かかるので非同期でしか使えない。

スコア = 4項目 × 20点 + オンライン明示（明記20 / 曖昧10 / 記載なし0）

処方箋について（実測で分かったこと）:
  生成された文面を「そのまま貼る」だけでは点は上がらない（3区で検証・全部0点上昇）。
  空欄を実際の値で埋めてから貼ると上がる（世田谷 0→100 / 新宿 0→80 / 港ablated 60→100）。
  だから処方箋は「穴の場所と書き方の型」として出し、埋めるのは職員、と明示する。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# このファイルの位置から導く。絶対パスを直書きすると書いた本人の手元でしか動かず、
# クローンした人は MEASURED が空になって「23区が即答されない＝壊れている」に見える。
REPO = Path(__file__).resolve().parent.parent
EXTRACT_DIR = REPO / "extractor" / "out"
MODEL = os.environ.get("AIDOKU_MODEL", "claude-sonnet-5")

ITEM_KEYS = {"documents": "必要書類", "online": "窓口オンライン可否",
             "deadline": "期限", "fee": "手数料"}
CLARITY_POINTS = {"明記": 20, "曖昧": 10, "記載なし": 0}


# ── 実測データ（23区）の読み込み ──────────────────────────

def _norm_url(u: str) -> str:
    """比較用にURLを正規化する。末尾スラッシュ・クエリ・スキームの揺れを吸収。

    小文字化を先にやる。あとからだと `WWW.` が `^www\\.` に当たらず残り、
    同じページを「未知のURL」と誤判定してライブ判定（30〜60秒）に落ちる。
    """
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("?")[0].split("#")[0].rstrip("/")


def load_measured() -> dict[str, dict]:
    """extractor/out/*.json から、URL → 実測結果 の表を作る。"""
    table: dict[str, dict] = {}
    if not EXTRACT_DIR.exists():
        return table
    for f in sorted(EXTRACT_DIR.glob("extract_*_tennyu.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        page = d.get("page") or {}
        url = page.get("url")
        if not url:
            continue
        items = d.get("items", {})
        table[_norm_url(url)] = {
            "municipality": d.get("municipality", ""),
            "found": {k: bool(items.get(jp, {}).get("found"))
                      for k, jp in ITEM_KEYS.items()},
            "values": {k: (items.get(jp, {}).get("value") or "")[:200]
                       for k, jp in ITEM_KEYS.items()},
            # 読めない理由。項目ごとの分類（記載なし/曖昧）と、ページ全体の観察記録。
            # 「読めないから何？」に答えるため、判定時の記録をそのまま画面まで運ぶ。
            "reasons": {k: (items.get(jp, {}).get("failure_reason") or "")
                        for k, jp in ITEM_KEYS.items()},
            "page_notes": (d.get("page_notes") or "").strip(),
            "clarity": (d.get("online_clarity") or "記載なし").strip(),
            "hops": page.get("hops"),
            "measured_at": "2026-07-22",
            "followed": d.get("followed_urls", []),
        }
    return table


MEASURED = load_measured()


# ── ライブ判定（未知のURL用） ───────────────────────────

def _call_claude(prompt: str, timeout: int = 300) -> str:
    p = subprocess.run(["claude", "-p", "--model", MODEL, "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"claude -p 失敗 (rc={p.returncode}): {p.stderr[:300]}")
    return p.stdout


def _parse_json(raw: str) -> dict:
    t = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"JSONが見つからない: {raw[:200]}")
    return json.loads(t[s:e + 1])


def judge_live(url: str) -> dict:
    """未知のURLを、その場で取得して判定する。1回30〜60秒かかる。"""
    sys.path.insert(0, str(REPO / "crawler"))
    from htmlutil import parse  # noqa: E402
    from polite_fetch import PoliteFetcher  # noqa: E402

    fetcher = PoliteFetcher()
    r = fetcher.fetch(url)
    if not r or not r.body_path:
        raise RuntimeError(f"取得できなかった: {url}")
    normalized = parse(r.body(), url)
    text, jsonld = normalized.text, normalized.jsonld
    body = text[:18000]

    # 4項目の抽出（リポジトリの本番プロンプトをそのまま使う）
    prompt = "".join([
        (REPO / "extractor" / "prompt.md").read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 手続き: 転入届\n- ページURL: {url}\n",
        f"\n## 構造化データ (JSON-LD)\n\n{'（なし）' if not jsonld else chr(10).join(jsonld)[:2000]}\n",
        f"\n## ページ本文\n\n{body}\n",
    ])
    data = _parse_json(_call_claude(prompt))
    items = data.get("items", {})
    found = {k: bool((items.get(jp) or {}).get("found")) for k, jp in ITEM_KEYS.items()}
    values = {k: ((items.get(jp) or {}).get("value") or "")[:200] for k, jp in ITEM_KEYS.items()}
    reasons = {k: ((items.get(jp) or {}).get("failure_reason") or "") for k, jp in ITEM_KEYS.items()}
    page_notes = (data.get("page_notes") or "").strip()

    # オンライン明示（別プロンプト。同居させると4項目の判定まで変わるため）
    cp = "".join([
        (REPO / "extractor" / "clarity_prompt.md").read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 手続き: 転入届\n- ページURL: {url}\n",
        f"\n## ページ本文\n\n{body}\n",
    ])
    cd = _parse_json(_call_claude(cp))
    clarity = (cd.get("online_clarity") or "").strip()
    if clarity not in CLARITY_POINTS:
        clarity = "記載なし"

    return {"municipality": "", "found": found, "values": values,
            "reasons": reasons, "page_notes": page_notes,
            "clarity": clarity, "hops": None, "measured_at": None, "followed": []}


# ── 採点 ────────────────────────────────────────────

def score(url: str, checks: list[str] | None, allow_live: bool = True) -> dict:
    """URLを判定して採点する。実測にあればそれを返し、無ければライブ判定。"""
    key = _norm_url(url)
    base = MEASURED.get(key)
    source = "measured"
    if base is None:
        if not allow_live:
            raise RuntimeError("実測データに無いURLです（ライブ判定は無効化されています）")
        base = judge_live(url)
        source = "live"

    targets = checks if checks else list(ITEM_KEYS.keys())
    found = {k: (base["found"][k] if k in targets else None) for k in ITEM_KEYS}
    item_pt = sum(20 for v in found.values() if v)
    clarity = base["clarity"]
    clarity_pt = CLARITY_POINTS.get(clarity, 0)

    return {
        "source": source,
        "municipality": base.get("municipality", ""),
        "found": found,
        "values": base.get("values", {}),
        "reasons": base.get("reasons", {}),
        "page_notes": base.get("page_notes", ""),
        "clarity": clarity,
        "clarity_pt": clarity_pt,
        "item_pt": item_pt,
        "total": item_pt + clarity_pt,
        "hops": base.get("hops"),
        "measured_at": base.get("measured_at"),
        "followed": base.get("followed", []),
    }


# ── 処方箋 ──────────────────────────────────────────
# 空欄（（　）で囲んだ部分）は職員が埋める。実測で「そのまま貼っても上がらない/
# 埋めれば上がる」ことが確認済みなので、そう明記して出す。

TEMPLATES = {
    "documents": (
        "## 転入届に必要なもの\n\n"
        "- 窓口に来る方の本人確認書類\n"
        "- 前住所地が発行した転出証明書\n"
        "  （マイナンバーカードで転出手続きをした場合は不要）\n"
        "- （該当する方のみ）在留カード等、委任状\n"
        "\n※（　）内は自治体の運用に合わせて書き換えてください"),
    "online": (
        "## 届出の方法と窓口\n\n"
        "転入届は窓口でのみ受け付けています。オンラインでは完結できません。\n\n"
        "- 受付窓口：（窓口名・場所を記載）\n"
        "- 受付時間：（曜日・時間を記載）"),
    "deadline": (
        "## 届出の期限\n\n"
        "新しい住所に住み始めた日から14日以内に届け出てください。\n"
        "（住み始める前の届出はできません）"),
    "fee": (
        "## 手数料\n\n"
        "転入届の届出に手数料はかかりません（無料）。"),
}
