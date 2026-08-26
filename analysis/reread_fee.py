"""読ませなかったページを読ませて、「手数料が書いていない」が本当かを確かめる。

**なぜ要るか**: AI読は「23区中22区が転入届の手数料を書いていない」と言ってきた。
だが探索台帳（`analysis/read_ledger.py`）が示したとおり、候補599本のうち
**読解に渡したのは41本**で、290本は**リンク一覧にも載せていない**。
「書いていない」と「読み落とした」が分かれていない。

**測るもの**: 未読の本命ページのうち、手数料の語を含むものを1本ずつ読ませ、
**転入届そのものの手数料**が書かれているかを判定する。

**これは追試であって、測定のやり直しではない**:

- 手数料1項目だけ。他3項目は触っていない
- 起点ページからの導線ではなく、こちらが選んだページを直接渡している
- だから **`web/data/scores-*.json` にそのまま混ぜてはいけない。**
  混ぜるには `read_breadth=strong_all` で本測定を通し直す必要がある

**言えること**: 「読み落としがあったか / 無かったか」
**言えないこと**: その区の点数が何点になるか

    python3 analysis/reread_fee.py --procedure tennyu --limit 3   # 動作確認
    python3 analysis/reread_fee.py --procedure tennyu             # 本番（約90回）
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "crawler" / "cache"
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from discover import score_link  # noqa: E402
from htmlutil import parse  # noqa: E402

from evidence_check import VERIFIED_VERDICTS, check_one  # noqa: E402
from extractor.fact_extract import (  # noqa: E402
    MAX_TEXT_CHARS,
    call_claude,
    keywords_for,
)
from extractor.response_contract import parse_json_reply  # noqa: E402

REREAD_VERSION = "reread-fee-0.1"
READ_BREADTH = "strong_all"
STRONG_SCORE = 10          # リンク題に手続きの語が入っている（discover の strong は10点）
FIELD = "手数料"

# ★語は「答えが載る場所の形」で選ぶ。金額の形（\d+円）を入れると
#   児童手当の支給額の表まで拾って数が3倍になった（plans/decisions/table-reading.md）。
FEE_WORDS = re.compile(r"手数料|費用|無料|かかりません")

# ★偽陽性の実物を名指しで外す。語だけで絞ったとき24/24自治体が当たり、
#   中身は住民票300円・戸籍謄本450円・Adobe Reader無料・プラネタリウム入場無料だった。
PROMPT = """このページの本文に、**転入届そのものの手数料**が書かれているかを判定してください。

転入届とは、他の市区町村から{muni}へ引っ越してきたときに出す届出です。

## これは「転入届の手数料」ではありません（found=false にしてください）

- 住民票の写し・戸籍謄本・印鑑登録証明書など、**証明書の交付手数料**
- **マイナンバーカード**の再交付手数料、電子証明書の発行手数料
- Adobe Reader などソフトの「無料ダウンロード」
- 施設の入場料、イベントの参加費、講座の受講料
- 転出届・転居届・国外転出など、**別の届出**の手数料
- 「手数料一覧」へのリンク名だけがあって、金額そのものは無い場合

## 書かれている場合

「無料」「かかりません」「◯◯円」のいずれでも found=true です。
`evidence` には**本文からそのまま引き写して**ください。言い換えないでください。

## 返す形（JSONだけ）

{{"found": true, "value": "無料", "evidence": "転入届の手数料は無料です。", "why_not": ""}}
{{"found": false, "value": "", "evidence": "", "why_not": "住民票の交付手数料しか無い"}}

---

## 本文（{url}）

{text}
"""


def procedure_name(procedure_id: str) -> str:
    """手続きIDから名前を引く。キーワードは名前で引くため。"""
    doc = json.loads((ROOT / "crawler/targets.json").read_text(encoding="utf-8"))
    for proc in doc["procedures"]:
        if proc["id"] == procedure_id:
            return proc["name"]
    raise SystemExit(f"手続きが見つからない: {procedure_id}")


def cache_text(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    path = CACHE / host / f"{key}.html"
    if not path.exists():
        return None
    try:
        return parse(path.read_text(encoding="utf-8", errors="replace"), url).text
    except Exception:                                     # noqa: BLE001
        return None


def read_urls(extract: dict) -> set[str]:
    return {extract["page"]["url"], *(extract.get("followed_urls") or [])}


def targets_for(discovery: dict, extract: dict, kw: dict) -> list[dict]:
    """読ませる対象。未読 × 本命 × 手数料の語がある、の3条件すべて。"""
    read = read_urls(extract)
    out = []
    for cand in discovery.get("candidates") or []:
        url = cand.get("url") or ""
        if url in read or score_link(cand.get("link_text") or "", url, kw) < STRONG_SCORE:
            continue
        text = cache_text(url)
        if not text or not FEE_WORDS.search(text):
            continue
        out.append({"url": url, "link_text": cand.get("link_text"),
                    "score": cand.get("score"), "text": text})
    return out


def ask_page(target: dict, muni: str, model: str) -> dict:
    """1ページだけ読ませ、引用を本文と照合する。"""
    prompt = PROMPT.format(muni=muni, url=target["url"], text=target["text"][:MAX_TEXT_CHARS])
    data = parse_json_reply(call_claude(prompt, model))
    check = check_one(data.get("evidence"), target["text"])
    return {
        "url": target["url"],
        "link_text": target["link_text"],
        "score": target["score"],
        "found": bool(data.get("found")),
        "value": str(data.get("value") or ""),
        "evidence": str(data.get("evidence") or ""),
        "why_not": str(data.get("why_not") or ""),
        "evidence_check": check,
        # ★引用が本文に無いものを「読めた」に数えない。捏造をここで止める。
        "verified": bool(data.get("found")) and check["verdict"] in VERIFIED_VERDICTS,
    }


def previous_verdict(procedure: str) -> dict[str, str]:
    """いま公開している判定。比較の基準にする。"""
    path = ROOT / "web" / "data" / f"scores-{procedure}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for muni in doc["municipalities"]:
        fee = [f for f in muni.get("fields", []) if f["field"] == FIELD]
        out[muni["id"]] = fee[0]["verdict"] if fee else "不明"
    return out


def summarize(rows: list[dict], before: dict[str, str]) -> dict:
    changed = [r for r in rows if r["now_found"] and before.get(r["municipality_id"]) != "読めた"]
    return {
        "municipalities": len(rows),
        "pages_read": sum(len(r["pages"]) for r in rows),
        "already_readable": sum(1 for r in rows if before.get(r["municipality_id"]) == "読めた"),
        # ★見出しの数字: 読み落としだった区
        "newly_found": len(changed),
        "newly_found_names": [r["municipality"] for r in changed],
        "still_not_found": sum(1 for r in rows if not r["now_found"]),
        # 引用が本文に無く「読めた」に数えなかった回。捏造の量
        "unverified_claims": sum(
            len([p for p in r["pages"] if p["found"] and not p["verified"]]) for r in rows),
    }


def load_pairs(procedure: str) -> list[tuple[dict, dict]]:
    extracts = {}
    for path in sorted(glob.glob(str(ROOT / f"extractor/out/*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        extracts[doc["municipality_id"]] = doc
    pairs = []
    for path in sorted(glob.glob(str(ROOT / f"crawler/out/discovery_*_{procedure}.json"))):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if doc["municipality_id"] in extracts:
            pairs.append((doc, extracts[doc["municipality_id"]]))
    return pairs


def run_one(discovery: dict, extract: dict, kw: dict, model: str) -> dict | None:
    targets = targets_for(discovery, extract, kw)
    if not targets:
        return {"municipality": extract["municipality"],
                "municipality_id": extract["municipality_id"],
                "pages": [], "now_found": False, "value": ""}
    pages = []
    for target in targets:
        try:
            pages.append(ask_page(target, extract["municipality"], model))
        except Exception as exc:                          # noqa: BLE001
            # ★失敗を「書いていない」に混ぜない。数えないで記録する。
            print(f"    ! {target['url']}: {exc}", file=sys.stderr)
            pages.append({"url": target["url"], "error": str(exc)[:200],
                          "found": False, "verified": False})
    hit = next((p for p in pages if p.get("verified")), None)
    return {"municipality": extract["municipality"],
            "municipality_id": extract["municipality_id"],
            "pages": pages, "now_found": hit is not None,
            "value": hit["value"] if hit else ""}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", default="tennyu")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--limit", type=int, default=0, help="最初のN自治体だけ")
    args = ap.parse_args(argv)

    pairs = load_pairs(args.procedure)
    if args.limit:
        pairs = pairs[: args.limit]
    kw = keywords_for(procedure_name(args.procedure))
    before = previous_verdict(args.procedure)
    rows = []
    for discovery, extract in pairs:
        row = run_one(discovery, extract, kw, args.model)
        rows.append(row)
        was = before.get(row["municipality_id"], "不明")
        mark = "★読み落としだった" if row["now_found"] and was != "読めた" else ""
        print(f"  {row['municipality']:6} {len(row['pages'])}本 → "
              f"{'書いてある' if row['now_found'] else '見つからない'} {row['value']} {mark}")

    doc = {
        "_about": "読ませていなかった本命ページを読ませ直した追試の記録。"
                  "手数料1項目のみ。測定のやり直しではないので scores-*.json には混ぜられない。",
        "reread_version": REREAD_VERSION,
        "procedure": args.procedure,
        "field": FIELD,
        "conditions": {"read_breadth": READ_BREADTH, "model": args.model,
                       "strong_score": STRONG_SCORE, "fee_words": FEE_WORDS.pattern},
        "summary": summarize(rows, before),
        "before": before,
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"reread-fee_{args.procedure}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['municipalities']}自治体 / {s['pages_read']}ページ読んだ")
    print(f"  ★読み落としだった区: {s['newly_found']}  {s['newly_found_names']}")
    print(f"  やはり見つからない区: {s['still_not_found']}")
    print(f"  引用が本文に無く数えなかった回: {s['unverified_claims']}")


if __name__ == "__main__":
    main()
