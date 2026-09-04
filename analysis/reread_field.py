"""手数料以外の3項目でも、読ませなかったページに答えが無いかを確かめる。

`analysis/reread_fee.py` を4項目に広げたもの。手数料は**読み落とし0件**だったが、
未読290本が効くのは手数料より **必要書類** の方だと見込んでいる（様式へのリンクや
「持ち物」の節は、本命ページの隣にあることが多い）。

**これは追試であって、測定のやり直しではない**（`reread_fee.py` と同じ）:

- 起点ページからの導線ではなく、こちらが選んだページを直接渡している
- だから `web/data/scores-*.json` にそのまま混ぜてはいけない

★項目ごとに**除外するもの**を名指しする。手数料で実証済みの作法。
  語だけで絞ると、住民票の交付手数料・戸籍謄本450円・Adobe無償が全部当たった。
  「何を答えとしないか」を書かないと、隣の手続きの答えを拾う。

    python3 analysis/reread_field.py -p tennyu -f 必要書類 --check   # 対象数だけ
    python3 analysis/reread_field.py -p tennyu -f 必要書類           # 読む
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "analysis" / "out"

sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "crawler"))
sys.path.insert(0, str(ROOT))
from discover import score_link  # noqa: E402
from reread_fee import (  # noqa: E402
    READ_BREADTH,
    STRONG_SCORE,
    cache_text,
    procedure_name,
    read_urls,
)

from evidence_check import VERIFIED_VERDICTS, check_one  # noqa: E402
from extractor.fact_extract import MAX_TEXT_CHARS, call_claude, keywords_for  # noqa: E402
from extractor.response_contract import parse_json_reply  # noqa: E402

VERSION = "reread-field-0.1"

# 語は「答えが載る場所の形」で選ぶ。答えそのものの形（金額・日付）は入れない。
HINTS = {
    "必要書類": re.compile(r"必要なもの|お持ちください|持ち物|必要書類|ご用意|本人確認書類"),
    "期限": re.compile(r"以内に|までに|期限|いつまで|日以内"),
    "窓口/オンライン可否": re.compile(r"窓口|受付時間|オンライン|電子申請|マイナポータル|来庁"),
    "手数料": re.compile(r"手数料|費用|無料|かかりません"),
}

# 項目ごとに「これは答えではない」を名指しする。ここが空だと隣の手続きを拾う。
NOT_THIS = {
    "必要書類": """- 住民票の写し・戸籍謄本など、**証明書を請求するとき**の必要書類
- **転出届・転居届**など、別の届出の必要書類
- マイナンバーカードの**交付・再交付**を受けるときの必要書類
- 「様式ダウンロード」のリンク名だけで、何を持参するかが本文に無い場合""",
    "期限": """- 証明書の**有効期限**、写真の「6か月以内に撮影」など、書類側の条件
- **転出届**の期限（転入届とは別）
- 受付時間・開庁時間（これは「窓口」の話）
- 「◯月◯日まで」のイベントやキャンペーンの期日""",
    "窓口/オンライン可否": """- 証明書のコンビニ交付・オンライン請求（**届出ではない**）
- **転出届**のオンライン（引越しワンストップは転出側。転入は来庁が要る場合が多い）
- 区の代表電話・問い合わせフォームだけの案内
- 他の課（税・保険）の窓口""",
    "手数料": """- 住民票の写し・戸籍謄本など、**証明書の交付手数料**
- マイナンバーカードの再交付手数料
- Adobe Reader などソフトの「無料ダウンロード」
- 施設の入場料・イベントの参加費
- **転出届・転居届**など、別の届出の手数料""",
}

ASK = """このページの本文に、**{muni}の{proc}そのものの{field}**が書かれているかを判定してください。

{proc}とは、他の市区町村から{muni}へ引っ越してきたときに出す届出です。

## これは「{proc}の{field}」ではありません（found=false にしてください）

{not_this}

## 書かれている場合

`evidence` には**本文からそのまま引き写して**ください。言い換えないでください。

## 返す形（JSONだけ）

{{"found": true, "value": "…", "evidence": "本文そのまま", "why_not": ""}}
{{"found": false, "value": "", "evidence": "", "why_not": "何の話だったか"}}

---

## 本文（{url}）

{text}
"""


def targets_for(discovery: dict, extract: dict, kw: dict, hint: re.Pattern) -> list[dict]:
    """未読 × 本命 × その項目の語がある、の3条件すべて。"""
    read = read_urls(extract)
    out = []
    for cand in discovery.get("candidates") or []:
        url = cand.get("url") or ""
        if url in read or score_link(cand.get("link_text") or "", url, kw) < STRONG_SCORE:
            continue
        text = cache_text(url)
        if not text or not hint.search(text):
            continue
        out.append({"url": url, "link_text": cand.get("link_text"),
                    "score": cand.get("score"), "text": text})
    return out


def ask_page(target: dict, muni: str, proc: str, field: str, model: str) -> dict:
    prompt = ASK.format(muni=muni, proc=proc, field=field, not_this=NOT_THIS[field],
                        url=target["url"], text=target["text"][:MAX_TEXT_CHARS])
    data = parse_json_reply(call_claude(prompt, model))
    check = check_one(data.get("evidence"), target["text"])
    return {"url": target["url"], "link_text": target["link_text"],
            "found": bool(data.get("found")), "value": str(data.get("value") or ""),
            "evidence": str(data.get("evidence") or ""),
            "why_not": str(data.get("why_not") or ""), "evidence_check": check,
            "verified": bool(data.get("found")) and check["verdict"] in VERIFIED_VERDICTS}


def before_verdicts(procedure: str, field: str) -> dict[str, str]:
    doc = json.loads((ROOT / "web" / "data" / f"scores-{procedure}.json").read_text("utf-8"))
    out = {}
    for muni in doc["municipalities"]:
        hit = [f for f in muni.get("fields", []) if f["field"] == field]
        out[muni["id"]] = hit[0]["verdict"] if hit else "不明"
    return out


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


def errored(row: dict) -> int:
    """読めなかったページ数。**「読んで無かった」と混ぜない。**"""
    return sum(1 for p in row["pages"] if p.get("error"))


def summarize(rows: list[dict], before: dict[str, str]) -> dict:
    changed = [r for r in rows if r["now_found"] and before.get(r["municipality_id"]) != "読めた"]
    # ★1ページでも読めていない区の「見つからない」は結論にならない。
    #   実際に利用上限で71ページが落ち、7区の「見つからない」が嘘になった。
    #   墨田区は11本すべて失敗していたのに「見つからない」と出ていた。
    incomplete = [r for r in rows if errored(r) and not r["now_found"]]
    return {
        "municipalities": len(rows),
        "pages_read": sum(len(r["pages"]) - errored(r) for r in rows),
        "pages_failed": sum(errored(r) for r in rows),
        "already_readable": sum(1 for r in rows if before.get(r["municipality_id"]) == "読めた"),
        "newly_found": len(changed),
        "newly_found_names": [r["municipality"] for r in changed],
        # ★この区の「見つからない」は信用できない。再実行が要る
        "inconclusive": len(incomplete),
        "inconclusive_names": [r["municipality"] for r in incomplete],
        "unverified_claims": sum(
            len([p for p in r["pages"] if p.get("found") and not p.get("verified")])
            for r in rows),
    }


def run_one(discovery: dict, extract: dict, kw: dict, field: str,
            proc: str, model: str, done: dict[str, dict] | None = None) -> dict:
    """1自治体ぶん。`done` に読めているページがあれば呼び直さない。

    ★再開できないと、利用上限に当たった時点までの結果が無駄になる。
      実際に71ページ落ちた。エラーのページだけ呼び直す。
    """
    targets = targets_for(discovery, extract, kw, HINTS[field])
    pages = []
    for target in targets:
        prev = (done or {}).get(target["url"])
        if prev and not prev.get("error"):
            pages.append(prev)
            continue
        try:
            pages.append(ask_page(target, extract["municipality"], proc, field, model))
        except Exception as exc:                          # noqa: BLE001
            print(f"    ! {target['url']}: {exc}", file=sys.stderr)
            pages.append({"url": target["url"], "error": str(exc)[:200],
                          "found": False, "verified": False})
    hit = next((p for p in pages if p.get("verified")), None)
    return {"municipality": extract["municipality"],
            "municipality_id": extract["municipality_id"],
            "pages": pages, "now_found": hit is not None,
            "value": hit["value"] if hit else ""}


def already_done(out: Path) -> dict[str, dict[str, dict]]:
    """前回の出力から、エラー無しで読めているページを拾う。自治体ID→URL→結果。"""
    if not out.exists():
        return {}
    doc = json.loads(out.read_text(encoding="utf-8"))
    return {row["municipality_id"]: {p["url"]: p for p in row["pages"] if not p.get("error")}
            for row in doc.get("rows", [])}


def safe_name(field: str) -> str:
    """項目名をファイル名にする。

    ★項目名を公開データに合わせて `窓口/オンライン可否` にした結果、
      **スラッシュがパスの区切りになって 284回ぶんの結果が捨てられた。**
      名前をデータに合わせるのは正しかったが、そのままファイル名にしたのが誤り。
    """
    return re.sub(r"[/\\:*?\"<>|\s]+", "-", field).strip("-")


def write_out(out: Path, args, rows: list[dict], before: dict[str, str],
              complete: bool = False) -> dict:
    """途中でも書く。**溜めてから最後に書くと、落ちた瞬間に全部消える。**"""
    doc = {
        "_about": "読ませていなかった本命ページを読ませ直した追試。"
                  "測定のやり直しではないので scores-*.json には混ぜられない。",
        "version": VERSION, "procedure": args.procedure, "field": args.field,
        "conditions": {"read_breadth": READ_BREADTH, "model": args.model,
                       "strong_score": STRONG_SCORE, "hint": HINTS[args.field].pattern},
        "complete": complete,
        "summary": summarize(rows, before), "before": before, "rows": rows,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--field", "-f", default="必要書類", choices=sorted(HINTS))
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="読まずに対象数だけ数える")
    args = ap.parse_args(argv)

    pairs = load_pairs(args.procedure)
    if args.limit:
        pairs = pairs[: args.limit]
    proc = procedure_name(args.procedure)
    kw = keywords_for(proc)
    before = before_verdicts(args.procedure, args.field)

    if args.check:
        total = 0
        for discovery, extract in pairs:
            n = len(targets_for(discovery, extract, kw, HINTS[args.field]))
            total += n
            print(f"  {extract['municipality']:6} {n:3}本"
                  f"  （公開判定: {before.get(extract['municipality_id'], '不明')}）")
        print(f"\n{args.field}: 読ませる対象 {total}本")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"reread-{args.procedure}_{safe_name(args.field)}.json"

    done = already_done(out)
    rows = []
    for discovery, extract in pairs:
        row = run_one(discovery, extract, kw, args.field, proc, args.model,
                      done.get(extract["municipality_id"]))
        rows.append(row)
        was = before.get(row["municipality_id"], "不明")
        mark = "★読み落としだった" if row["now_found"] and was != "読めた" else ""
        print(f"  {row['municipality']:6} {len(row['pages']):2}本 → "
              f"{'書いてある' if row['now_found'] else '見つからない'} {mark}")
        # ★1自治体ごとに書く。最後にまとめて書いていたら、284回のLLM呼び出しが
        #   最後の1行（ファイル名にスラッシュが入っていた）で全部消えた。実際に消えた。
        write_out(out, args, rows, before)

    doc = write_out(out, args, rows, before, complete=True)
    s = doc["summary"]
    print(f"\n→ {out}")
    print(f"  {s['municipalities']}自治体 / 読めた {s['pages_read']}ページ / "
          f"読めなかった {s['pages_failed']}ページ")
    if s["inconclusive"]:
        print(f"  ★結論を出せない区: {s['inconclusive']}  {s['inconclusive_names']}")
    print(f"  ★読み落としだった区: {s['newly_found']}  {s['newly_found_names']}")
    print(f"  引用が本文に無く数えなかった回: {s['unverified_claims']}")


if __name__ == "__main__":
    main()
