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
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

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

sys.path.insert(0, str(Path(__file__).parent.parent))
from fact_types import EXTRACTOR_KEYS  # noqa: E402
from evidence_check import (  # noqa: E402
    MAX_TEXT_CHARS_PER_PAGE,
    attach_checks_across_pages,
    summarize,
    truncate_page_text,
)
from measurement import (  # noqa: E402
    MeasurementError,
    build_measurement,
    prompt_version,
    utc_timestamp,
)

# 4項目の定義は fact_types.json が唯一の出どころ。ここに直書きしない。
FIELDS = EXTRACTOR_KEYS
MAX_TEXT_CHARS = MAX_TEXT_CHARS_PER_PAGE
MAX_LINKS = 40
MAX_FOLLOW = 2


# HTML以外の添付ファイル。本文の代わりにバイナリが渡ると、
# text_len だけは大きくなるので「本文200字以上」の条件をすり抜ける。
# 実測: 台東区が .docx（Word）を診断ページに選び、ZIP/XMLのバイナリを採点していた。
NON_HTML_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rtf", ".odt", ".ods", ".csv",
)


def is_non_html(url: str) -> bool:
    """URL の拡張子が HTML 以外のファイルを指しているか。"""
    return urlsplit(url).path.lower().endswith(NON_HTML_SUFFIXES)


def pick_page(discovery: dict) -> dict | None:
    """探索結果から、抽出対象にする1ページを選ぶ（スコア最上位のHTMLページ）。"""
    for c in discovery.get("candidates", []):
        if c.get("is_pdf") or is_non_html(c.get("url") or ""):
            continue
        if c.get("status") != 200:
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
    normalized = parse(r.body(), page["url"])
    links, text, jsonld = normalized.links, normalized.text, normalized.jsonld

    truncated = len(text) > MAX_TEXT_CHARS
    body = truncate_page_text(text)

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
        parts.append(
            f"\n---\n\n## リンク先ページの本文（{url}）\n\n"
            f"{truncate_page_text(ptext)}\n"
        )
    if extra_pages:
        parts.append(
            "\n（上のリンク先ページはあなたの要求で開いたものです。ここから答えが取れた項目は "
            "found=true / source=\"linked_page\" とし、failure_reason は null にしてください。）"
        )
    meta = {"has_jsonld": bool(jsonld), "text_len": len(text), "truncated": truncated,
            "n_links": len(link_lines)}
    return "".join(parts), meta


def build_evidence_pages(page: dict, fetcher: PoliteFetcher,
                         extra_pages: list[tuple[str, str]] | None = None) -> list[str]:
    """LLMへ本文として渡した各ページを、混ぜずに照合用へ返す。"""
    r = fetcher.cached(page["url"])
    if r is None or not r.body_path:
        raise SystemExit(f"キャッシュに無い: {page['url']}（先に crawler/discover.py を実行）")
    normalized = parse(r.body(), page["url"])
    pages = [truncate_page_text(normalized.text)]
    pages.extend(truncate_page_text(ptext) for _, ptext in (extra_pages or []))
    return pages


def judge_clarity(page: dict, muni: str, proc: str, fetcher: PoliteFetcher,
                  model: str, extra_pages: list[tuple[str, str]] | None = None) -> dict:
    """ページの性質として online_clarity だけを1回観測する（4項目の抽出とは別呼び出し）。

    読む範囲は4項目の抽出と必ず揃える（本体ページ＋--follow で開いたリンク先）。
    本体ページだけで判定していた頃、入口が薄い自治体（八王子）で4項目は
    リンク先を読み clarity は読まない非対称が起き、判定が「記載なし」に落ちていた。
    入口が薄いこと自体のコストは「情報到達」で別に測っているので、ここで二重に引かない。
    """
    r = fetcher.cached(page["url"])
    if r is None or not r.body_path:
        return {"online_clarity": "記載なし", "evidence": "", "pages": []}
    text = parse(r.body(), page["url"]).text
    parts = [
        CLARITY_PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- ページURL: {page['url']}\n",
        f"\n## ページ本文\n\n{text[:MAX_TEXT_CHARS]}\n",
    ]
    for url, ptext in (extra_pages or []):
        parts.append(f"\n---\n\n## リンク先ページの本文（{url}）\n\n{ptext[:MAX_TEXT_CHARS]}\n")
    if extra_pages:
        parts.append("\n（上のリンク先ページも、このページから1クリックで到達できる範囲です。"
                     "同じ手続きの説明として合わせて読んでください。）")
    data = parse_json_reply(call_claude("".join(parts), model))
    clarity = (data.get("online_clarity") or "").strip()
    if clarity not in ("明記", "曖昧", "記載なし"):
        clarity = "記載なし"
    return {"online_clarity": clarity, "evidence": (data.get("evidence") or "").strip(),
            "pages": [page["url"], *(u for u, _ in (extra_pages or []))]}


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


def measurement_for(discovery: dict, *, follow: bool, model: str,
                    prompt: str, run_at: str) -> dict:
    return build_measurement(
        discovery.get("measurement"),
        prompt=prompt,
        follow=follow,
        max_follow=MAX_FOLLOW,
        max_text_chars=MAX_TEXT_CHARS,
        max_links=MAX_LINKS,
        model_version=model,
        run_at=run_at,
    )


def load_discovery(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MeasurementError(f"{path}: 探索結果JSONを読めない: {error}") from error
    if not isinstance(value, dict):
        raise MeasurementError(f"{path}: 探索結果のrootがオブジェクトでない")
    return value


def prepare_discoveries(files: Sequence[Path], *, follow: bool, model: str,
                        prompt: str, run_at: str) -> list[tuple[dict, dict]]:
    """全入力を先に検証し、途中失敗で既存出力を一部上書きしない。"""
    prepared = []
    for path in files:
        discovery = load_discovery(path)
        try:
            measurement = measurement_for(
                discovery, follow=follow, model=model, prompt=prompt, run_at=run_at
            )
        except MeasurementError as error:
            raise MeasurementError(f"{path}: {error}") from error
        prepared.append((discovery, measurement))
    return prepared


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

    run_at = utc_timestamp()
    current_prompt = prompt_version([PROMPT, CLARITY_PROMPT])
    try:
        prepared = prepare_discoveries(
            files, follow=args.follow, model=args.model,
            prompt=current_prompt, run_at=run_at,
        )
    except MeasurementError as error:
        raise SystemExit(str(error)) from error

    fetcher = PoliteFetcher()
    results = []
    for disc, measurement in prepared:
        page = pick_page(disc)
        if page is None:
            print(f"[{disc['municipality']}] 抽出対象ページなし（到達失敗）")
            result = {"municipality": disc["municipality"], "municipality_id": disc["municipality_id"],
                      "procedure": disc["procedure"], "procedure_id": disc["procedure_id"],
                      "page": None, "reached": False, "model": args.model,
                      "measurement": measurement, "items": {}, "error": "到達失敗",
                      "evidence_check_status": "not_applicable",
                      "evidence_check_scope": {"pages": [],
                                               "max_text_chars_per_page": MAX_TEXT_CHARS},
                      "evidence_summary": summarize({})}
        else:
            prompt, meta = build_input(page, disc["municipality"], disc["procedure"], fetcher)
            raw = call_claude(prompt, args.model)
            data = parse_json_reply(raw)

            # 探索順序4「リンク先1階層」— エージェントが開きたいと言ったページだけを追う。
            # ここだけ取得層に降りるが、通すのは同じ PoliteFetcher（robots・3秒・キャッシュ）。
            followed: list[str] = []
            extra: list[tuple[str, str]] = []
            if args.follow:
                wants = [u for u in (data.get("follow_urls") or []) if str(u).startswith("http")]
                for url in wants[:MAX_FOLLOW]:
                    fr = fetcher.fetch(url)
                    if not fr.body_path:
                        continue
                    ptext = parse(fr.body(), url).text
                    extra.append((url, ptext))
                    followed.append(url)
                if extra:
                    prompt2, _ = build_input(page, disc["municipality"], disc["procedure"],
                                             fetcher, extra_pages=extra)
                    data = parse_json_reply(call_claude(prompt2, args.model))

            # ページの性質として1回だけ観測する。採点側はこれを機械的に点に変えるだけで、
            # LLMに判定し直させない（同じ判定を二重に使うとスコアのぶれが増幅されるため）
            # 読む範囲は4項目と揃える（extra_pages を同じように渡す）
            clarity = judge_clarity(page, disc["municipality"], disc["procedure"],
                                    fetcher, args.model, extra_pages=extra)

            items, evidence_summary = attach_checks_across_pages(
                normalize_items(data), build_evidence_pages(page, fetcher, extra_pages=extra)
            )

            result = {
                "municipality": disc["municipality"], "municipality_id": disc["municipality_id"],
                "procedure": disc["procedure"], "procedure_id": disc["procedure_id"],
                "page": {"url": page["url"], "hops": page["hops"], "link_text": page["link_text"], **meta},
                "reached": True,
                "model": args.model,
                "measurement": measurement,
                "followed_urls": followed,
                "online_clarity": clarity["online_clarity"],
                "online_clarity_evidence": clarity["evidence"],
                # 何を読んで判定したかを残す（判定範囲が4項目とずれていないかの確認用）
                "online_clarity_pages": clarity["pages"],
                "items": items,
                "evidence_check_status": "complete",
                "evidence_check_scope": {
                    "pages": [page["url"], *followed],
                    "max_text_chars_per_page": MAX_TEXT_CHARS,
                },
                "evidence_summary": evidence_summary,
                "page_notes": data.get("page_notes", ""),
            }
            found = sum(1 for v in result["items"].values() if v["found"])
            tail = f" (+リンク先{len(followed)}件)" if followed else ""
            print(f"[{disc['municipality']}] hop{page['hops']} {found}/4項目 抽出"
                  f" / オンライン明示={clarity['online_clarity']}{tail} — {page['url']}")

        results.append(result)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for result in results:
        out = OUT_DIR / f"extract_{result['municipality_id']}_{result['procedure_id']}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
