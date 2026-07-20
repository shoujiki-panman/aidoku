"""読解層 (Layer A) — キャッシュ済みページから4項目を抽出する。

LLM は `claude -p` のヘッドレス呼び出しで回す。APIキー不要で、手元の認証をそのまま使えるため。
ネットワークには触らない（触るのは crawler だけ）。入力は crawler/cache と crawler/out のみ。

出力: out/extract_<自治体>_<手続き>.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "crawler"))
from htmlutil import parse  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

ROOT = Path(__file__).parent.parent
DISCOVERY_DIR = ROOT / "crawler" / "out"
OUT_DIR = Path(__file__).parent / "out"
PROMPT = Path(__file__).parent / "prompt.md"
# online_clarity は4項目の抽出とは別のプロンプトで聞く。
# 同じプロンプトに同居させると「曖昧」という語が4項目の判定にも漏れて、
# 必要書類などが「見つからず(曖昧)」に落ちる副作用が出た（2026-07-21 実測）。
CLARITY_PROMPT = Path(__file__).parent / "clarity_prompt.md"

FIELDS = ["必要書類", "窓口オンライン可否", "期限", "手数料"]
MAX_TEXT_CHARS = 18000
MAX_LINKS = 40
MAX_FOLLOW = 2


def pick_page(discovery: dict) -> dict | None:
    """探索結果から、抽出対象にする1ページを選ぶ（スコア最上位のHTMLページ）。"""
    for c in discovery.get("candidates", []):
        if c.get("is_pdf") or c.get("status") != 200:
            continue
        if (c.get("text_len") or 0) < 200:
            continue
        return c
    return None


def build_input(page: dict, muni: str, proc: str, fetcher: PoliteFetcher,
                extra_pages: list[tuple[str, str]] | None = None) -> tuple[str, dict]:
    r = fetcher.cached(page["url"])
    if r is None or not r.body_path:
        raise SystemExit(f"キャッシュに無い: {page['url']}（先に crawler/discover.py を実行）")
    links, text, jsonld = parse(r.body(), page["url"])

    truncated = len(text) > MAX_TEXT_CHARS
    body = text[:MAX_TEXT_CHARS]

    link_lines = []
    seen = set()
    for ln in links:
        if not ln.text or ln.href in seen:
            continue
        seen.add(ln.href)
        link_lines.append(f"- {ln.text} → {ln.href}")
        if len(link_lines) >= MAX_LINKS:
            break

    prompt = PROMPT.read_text(encoding="utf-8")
    parts = [
        prompt,
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- ページURL: {page['url']}\n",
        f"\n## 構造化データ (JSON-LD)\n\n{'（なし）' if not jsonld else chr(10).join(jsonld)[:2000]}\n",
        f"\n## ページ本文{'（長いため冒頭のみ）' if truncated else ''}\n\n{body}\n",
        f"\n## このページから出ているリンク（最大{MAX_LINKS}件）\n\n" + ("\n".join(link_lines) or "（なし）"),
    ]
    for url, ptext in (extra_pages or []):
        parts.append(f"\n---\n\n## リンク先ページの本文（{url}）\n\n{ptext[:MAX_TEXT_CHARS]}\n")
    if extra_pages:
        parts.append(
            "\n（上のリンク先ページはあなたの要求で開いたものです。ここから答えが取れた項目は "
            "found=true / source=\"linked_page\" とし、failure_reason は null にしてください。）"
        )
    meta = {"has_jsonld": bool(jsonld), "text_len": len(text), "truncated": truncated,
            "n_links": len(link_lines)}
    return "".join(parts), meta


def judge_clarity(page: dict, muni: str, proc: str, fetcher: PoliteFetcher,
                  model: str) -> dict:
    """ページの性質として online_clarity だけを1回観測する（4項目の抽出とは別呼び出し）。"""
    r = fetcher.cached(page["url"])
    if r is None or not r.body_path:
        return {"online_clarity": "記載なし", "evidence": ""}
    _, text, _ = parse(r.body(), page["url"])
    prompt = "".join([
        CLARITY_PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- ページURL: {page['url']}\n",
        f"\n## ページ本文\n\n{text[:MAX_TEXT_CHARS]}\n",
    ])
    data = parse_json_reply(call_claude(prompt, model))
    clarity = (data.get("online_clarity") or "").strip()
    if clarity not in ("明記", "曖昧", "記載なし"):
        clarity = "記載なし"
    return {"online_clarity": clarity, "evidence": (data.get("evidence") or "").strip()}


def call_claude(prompt: str, model: str, timeout: int = 300) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout


def parse_json_reply(raw: str) -> dict:
    """コードフェンスや前置きが付いていても JSON を取り出す。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSONが見つからない: {raw[:300]}")
    return json.loads(text[start:end + 1])


def normalize_items(data: dict) -> dict:
    items = data.get("items", {})
    out = {}
    for f in FIELDS:
        it = items.get(f) or {}
        out[f] = {
            "found": bool(it.get("found")),
            "value": (it.get("value") or "").strip(),
            "evidence": (it.get("evidence") or "").strip(),
            "source": it.get("source") or None,
            "failure_reason": it.get("failure_reason") or None,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipality", "-m", action="append")
    ap.add_argument("--procedure", "-p", default="tennyu")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--follow", action="store_true",
                    help="探索順序4に従い、エージェントが指定したリンク先を1階層だけ開いて再抽出する")
    args = ap.parse_args()

    files = sorted(DISCOVERY_DIR.glob(f"discovery_*_{args.procedure}.json"))
    if args.municipality:
        files = [f for f in files if any(f"discovery_{m}_" in f.name for m in args.municipality)]
    if not files:
        raise SystemExit("探索結果がない。先に crawler/discover.py を実行すること")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetcher = PoliteFetcher()

    for f in files:
        disc = json.loads(f.read_text(encoding="utf-8"))
        page = pick_page(disc)
        if page is None:
            print(f"[{disc['municipality']}] 抽出対象ページなし（到達失敗）")
            result = {"municipality": disc["municipality"], "municipality_id": disc["municipality_id"],
                      "procedure": disc["procedure"], "procedure_id": disc["procedure_id"],
                      "page": None, "reached": False, "items": {}, "error": "到達失敗"}
        else:
            prompt, meta = build_input(page, disc["municipality"], disc["procedure"], fetcher)
            raw = call_claude(prompt, args.model)
            data = parse_json_reply(raw)

            # 探索順序4「リンク先1階層」— エージェントが開きたいと言ったページだけを追う。
            # ここだけ取得層に降りるが、通すのは同じ PoliteFetcher（robots・3秒・キャッシュ）。
            followed: list[str] = []
            if args.follow:
                wants = [u for u in (data.get("follow_urls") or []) if str(u).startswith("http")]
                extra: list[tuple[str, str]] = []
                for url in wants[:MAX_FOLLOW]:
                    fr = fetcher.fetch(url)
                    if not fr.body_path:
                        continue
                    _, ptext, _ = parse(fr.body(), url)
                    extra.append((url, ptext))
                    followed.append(url)
                if extra:
                    prompt2, _ = build_input(page, disc["municipality"], disc["procedure"],
                                             fetcher, extra_pages=extra)
                    data = parse_json_reply(call_claude(prompt2, args.model))

            # ページの性質として1回だけ観測する。採点側はこれを機械的に点に変えるだけで、
            # LLMに判定し直させない（同じ判定を二重に使うとスコアのぶれが増幅されるため）
            clarity = judge_clarity(page, disc["municipality"], disc["procedure"],
                                    fetcher, args.model)

            result = {
                "municipality": disc["municipality"], "municipality_id": disc["municipality_id"],
                "procedure": disc["procedure"], "procedure_id": disc["procedure_id"],
                "page": {"url": page["url"], "hops": page["hops"], "link_text": page["link_text"], **meta},
                "reached": True,
                "model": args.model,
                "followed_urls": followed,
                "online_clarity": clarity["online_clarity"],
                "online_clarity_evidence": clarity["evidence"],
                "items": normalize_items(data),
                "page_notes": data.get("page_notes", ""),
            }
            found = sum(1 for v in result["items"].values() if v["found"])
            tail = f" (+リンク先{len(followed)}件)" if followed else ""
            print(f"[{disc['municipality']}] hop{page['hops']} {found}/4項目 抽出"
                  f" / オンライン明示={clarity['online_clarity']}{tail} — {page['url']}")

        out = OUT_DIR / f"extract_{disc['municipality_id']}_{disc['procedure_id']}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
