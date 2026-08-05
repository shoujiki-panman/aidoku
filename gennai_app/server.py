#!/usr/bin/env python3
"""AI読(アイドク) — 源内 行政実務用AIアプリ 互換エンドポイント（最小実装）

準拠元: digital-go-jp/genai-web docs/AIアプリAPI仕様.md (2026-03時点版)
        digital-go-jp/genai-ai-api aws/query-expansion-rag (POST /invoke + x-api-key)

Python標準ライブラリのみ。外部依存なし。

  同期:   POST /invoke        -> 200 {"outputs": "<markdown>"}
  非同期: POST /requests      -> 202 {"outputs","request_id","status":"PENDING","status_url"}
          GET  /status/<id>   -> 200 {"status": PENDING|IN_PROGRESS|COMPLETED|ERROR, ...}
  補助:   GET  /request-format -> 源内「チーム管理」に貼り付けるリクエスト形式JSON（仕様外の便宜）

認証: x-api-key ヘッダ（仕様のcurl例に準拠）。環境変数 AIDOKU_API_KEY、既定 "dev-local-key"。

判定は aidoku_engine が行う（本物）。
23区は2026-07-22の実測値を即返し、未知のURLはその場で取得してclaude -pで判定する。
"""

import base64
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ.get("AIDOKU_API_KEY", "dev-local-key")
import aidoku_engine as engine

PORT = int(os.environ.get("AIDOKU_PORT", "8791"))

# 源内「リクエスト形式」定義。仕様書のコンポーネント型のみを使う。
REQUEST_FORMAT = {
    "url": {
        "type": "text",
        "title": "診断するページのURL",
        "desc": "自治体サイトの手続きページURLを入力してください。",
        "required": True,
        "max_length": 2000,
    },
    "checks": {
        "type": "checkbox",
        "title": "採点する項目",
        "desc": "未選択の場合は全項目を採点します。",
        "items": [
            {"title": "必要書類", "value": "documents"},
            {"title": "窓口/オンライン可否", "value": "online"},
            {"title": "期限", "value": "deadline"},
            {"title": "手数料", "value": "fee"},
        ],
    },
    "mode": {
        "type": "radio",
        "title": "出力モード",
        "items": [
            {"title": "採点のみ", "value": "score"},
            {"title": "採点＋処方箋", "value": "full"},
        ],
        "default_value": "full",
    },
    "app_version": {"type": "hidden", "default_value": "aidoku-0.2"},
    "conversation_history": {
        "type": "textarea",
        "title": "会話履歴",
        "desc": "過去の会話履歴を入力すると、その内容を参照した回答を生成します",
    },
}

# 採点定義: 4項目 × 20点 + オンライン明示(明記20/曖昧10/記載なし0) = 100点
ITEM_LABELS = {
    "documents": "必要書類",
    "online": "窓口/オンライン可否",
    "deadline": "期限",
    "fee": "手数料",
}

_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _normalize_files(inputs):
    """仕様書内で2形式が併記されているため両方を受ける。

    A) 送出されるリクエスト節: files:[{"key":k,"files":[{"filename","content"}]}]
    B) 非同期curl例:           files:[{"key":k,"contents":"...","filename":"..."}]
    戻り値: [(key, filename, nbytes)]
    """
    out = []
    for entry in inputs.get("files") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key", "")
        if isinstance(entry.get("files"), list):  # 形式A
            for f in entry["files"]:
                out.append((key, f.get("filename", ""), _b64len(f.get("content"))))
        elif "contents" in entry:  # 形式B
            out.append((key, entry.get("filename", ""), _b64len(entry.get("contents"))))
    return out


def _b64len(s):
    if not isinstance(s, str):
        return 0
    try:
        return len(base64.b64decode(s, validate=False))
    except Exception:
        return 0


def score_page(url, checks, mode, history):
    """本物の判定。23区は実測値、未知URLはライブ判定（30〜60秒かかる）。"""
    allow_live = os.environ.get("AIDOKU_ALLOW_LIVE", "1") == "1"
    r = engine.score(url, checks, allow_live=allow_live)
    r["mode"] = mode
    r["history_used"] = bool(history)
    return r


PRESCRIPTIONS = engine.TEMPLATES


def render_markdown(url, result):
    """主役は点数ではなく「住民がAIに聞いたときの答え」。

    住民の質問 → いまの答え → なぜそうなるか → 直したらどう答えられるか、の順に出す。
    点数は最後に参考として置く（点数が主役だと「だから何？」で終わる、と実地で分かったため）。
    """
    L = []
    muni = result.get("municipality") or ""
    vals = result.get("values", {})
    reasons = result.get("reasons", {})
    missing = [k for k, v in result["found"].items() if v is False]
    answered = [k for k, v in result["found"].items() if v is True]

    L.append(f"# AI読{('　' + muni) if muni else ''}")
    L.append("")

    # ── 主役: 住民がAIに聞いたときの答え ──
    L.append("## 住民がこのページを読んだAIに聞くと、いまはこう返ります")
    L.append("")
    L.append(f"> **住民**「{muni or 'この自治体'}に引っ越します。転入届に必要なもの・期限・"
             "手数料を教えて。オンラインでできますか？」")
    L.append("")
    L.append("**住民のAIの答え**")
    L.append("")
    for key, label in ITEM_LABELS.items():
        v = result["found"].get(key)
        if v is None:
            continue
        if v:
            got = (vals.get(key) or "").replace("|", "／").replace("\n", " ")[:110]
            L.append(f"- **{label}**: {got or '（値の記録なし）'}")
        else:
            L.append(f"- **{label}**: _このページからは分かりません_")
    L.append("")
    n_target = len([v for v in result["found"].values() if v is not None])
    if missing:
        L.append(f"**{n_target}項目のうち {len(answered)}項目しか答えられません。** "
                 "住民が知りたいことの残りは、AIには届いていません。")
    else:
        L.append(f"**{n_target}項目すべて答えられます。** "
                 "住民がAIに尋ねても、このページからは正しい答えが返ります。")
    L.append("")

    # ── なぜそうなるのか ──
    if missing or result["clarity"] != "明記":
        L.append("## なぜ答えられないのか")
        L.append("")
        notes = (result.get("page_notes") or "").strip()
        if notes:
            L.append(f"{notes}")
            L.append("")
        if missing:
            L.append("| 答えられなかった項目 | 判定AIの記録 |")
            L.append("| --- | --- |")
            for key in missing:
                r = (reasons.get(key) or "記載なし").replace("|", "／")
                L.append(f"| {ITEM_LABELS[key]} | {r} |")
            L.append("")

    # ── 直したらどうなるか ──
    if result["mode"] == "score":
        L.append("_（出力モード=採点のみ。直し方の提案は省略しました）_")
        L.append("")
    elif missing or result["clarity"] != "明記":
        L.append("## 直すと、住民のAIはこう答えられるようになります")
        L.append("")
        L.append("下の型をページに追記してください。"
                 "**（　）の中は、各自治体の実際の値に置き換えてください。**")
        L.append("")
        for key in missing:
            L.append(f"### {ITEM_LABELS[key]}（いまは答えられない）")
            L.append("")
            L.append("```markdown")
            L.append(PRESCRIPTIONS[key])
            L.append("```")
            L.append("")
        if result["clarity"] != "明記" and "online" not in missing:
            L.append("### オンラインで完結できるかが読み取りにくい")
            L.append("")
            L.append("```markdown")
            L.append(PRESCRIPTIONS["online"])
            L.append("```")
            L.append("")
        L.append("追記したら、もう一度このURLを診断してください。")
        L.append("")
        # 太字の閉じ記号の直後が日本語だと Markdown が太字として認識しない
        # （閉じ側の判定に空白か句読点が要る）。行を分けて空白を置く。
        L.append("> **実測での確認**: （　）を実際の値で埋めて追記した場合、"
                 "世田谷区で 0点 → 100点、新宿区で 0点 → 80点 に上がることを確認しています"
                 "（2026-07-26 実測）。逆に、（　）を空欄のまま貼っても点は上がりません。")
        L.append(">")
        L.append("> **AIは穴の場所と書き方を示すところまでで、値を埋めるのは職員の方です。** "
                 "これは、AIが役所の情報を作り出さないための設計です。")
        L.append("")

    # ── 参考: 点数 ──
    L.append(f"## 参考: AI判読度 {result['total']} / 100点")
    L.append("")
    L.append("| 項目 | 住民のAIに伝わるか | 配点 |")
    L.append("| --- | --- | --- |")
    for key, label in ITEM_LABELS.items():
        v = result["found"].get(key)
        if v is None:
            L.append(f"| {label} | 対象外 | - |")
        elif v:
            L.append(f"| {label} | 伝わる | 20 / 20 |")
        else:
            L.append(f"| {label} | **伝わらない** | 0 / 20 |")
    L.append(f"| オンライン明示 | {result['clarity']} | {result['clarity_pt']} / 20 |")
    L.append("")
    L.append("_AI判定です。各項目は「読めた／読めない」の2値で20点なので、判定が1つ変われば20点動きます。_")

    if result.get("history_used"):
        L.append("")
        L.append("_（会話履歴を受け取りました）_")

    L.append("")
    L.append(f"- 対象URL: {url}")
    if result.get("hops") is not None:
        L.append(f"- トップページから **{result['hops']}クリック** で到達")
    L.append(f"- 判定日時: {_now()}")
    L.append("")
    if result.get("source") == "measured":
        L.append(f"> 判定の出どころ: **実測値**（{result.get('measured_at')} に"
                 "各区の公式サイトを取得し、AIに読ませた結果）。"
                 "採点は 4項目×20点 + オンライン明示20点。")
        if result.get("followed"):
            L.append(">")
            L.append(f"> 読んだ範囲: このページ + リンク先{len(result['followed'])}件")
    else:
        L.append("> 判定の出どころ: **この場で取得して判定**（robots.txt遵守・3秒間隔）。"
                 "採点は 4項目×20点 + オンライン明示20点。")
    return "\n".join(L)


def build_artifact(url, result, md):
    return {
        "contents": base64.b64encode(md.encode("utf-8")).decode("ascii"),
        "display_name": "aidoku-prescription.md",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AidokuGennaiCompat/0.1"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    # --- helpers -------------------------------------------------
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        if self.headers.get("x-api-key") == API_KEY:
            return True
        self._send(401, {"status": "ERROR", "error": {
            "message": "Unauthorized.",
            "details": "x-api-key header is missing or invalid."}})
        return False

    def _read_inputs(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception as e:
            self._send(400, {"status": "ERROR", "error": {
                "message": "Invalid JSON body.", "details": str(e)}})
            return None
        if not isinstance(body, dict) or not isinstance(body.get("inputs"), dict):
            self._send(400, {"status": "ERROR", "error": {
                "message": "Request body must be wrapped in an 'inputs' object.",
                "details": 'Expected {"inputs": {...}} per 源内 AIアプリAPI仕様.'}})
            return None
        return body["inputs"]

    def _validate(self, inputs):
        url = inputs.get("url")
        if not isinstance(url, str) or not re.match(r"^https?://", url.strip()):
            # 利用者の入力ミスはプロトコルエラーではないので、200で案内を返す。
            # 400を返すと源内の画面には何も表示されず「押しても無反応」に見える。
            got = (url or "").strip()
            self._send(200, {"outputs": (
                "# 入力を確認してください\n\n"
                + (f"入力された値: `{got[:80]}`\n\n" if got else "URLが空欄です。\n\n")
                + "**診断するページのURLを、`https://` から始まる形で入力してください。**\n\n"
                "例:\n\n"
                "```\n"
                "https://www.city.minato.tokyo.jp/shibamadosa/kurashi/todokede/hikkoshi/tennyu.html\n"
                "```\n\n"
                "自治体の公式サイトで、転入届などの手続きを説明しているページのURLを"
                "そのまま貼り付けてください。")})
            return None
        raw_checks = inputs.get("checks")
        if isinstance(raw_checks, str) and raw_checks.strip():
            checks = [c for c in raw_checks.split(",") if c in ITEM_LABELS]
        else:
            checks = list(ITEM_LABELS)  # 未選択なら全項目
        mode = inputs.get("mode") or "full"
        history = inputs.get("conversation_history") or ""
        _normalize_files(inputs)  # 形式のみ検証（このアプリはファイル入力を使わない）
        return url.strip(), checks, mode, history

    # --- routes --------------------------------------------------
    def do_GET(self):
        if self.path == "/request-format":
            self._send(200, REQUEST_FORMAT)
            return
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if self.path.startswith("/status/"):
            if not self._auth_ok():
                return
            rid = self.path[len("/status/"):].strip("/")
            with _JOBS_LOCK:
                job = _JOBS.get(rid)
            if job is None:
                self._send(404, {"status": "ERROR", "request_id": rid, "error": {
                    "message": "Unknown request_id.",
                    "details": "The request_id was not found."}})
                return
            self._send(200, job)
            return
        self._send(404, {"status": "ERROR", "error": {
            "message": "Not found.", "details": f"No route for GET {self.path}"}})

    def do_POST(self):
        if self.path not in ("/invoke", "/requests"):
            self._send(404, {"status": "ERROR", "error": {
                "message": "Not found.", "details": f"No route for POST {self.path}"}})
            return
        if not self._auth_ok():
            return
        inputs = self._read_inputs()
        if inputs is None:
            return
        parsed = self._validate(inputs)
        if parsed is None:
            return
        url, checks, mode, history = parsed

        if self.path == "/invoke":  # 同期
            # 判定に失敗しても接続を切らず、理由を返す。
            # （源内の画面では、無応答だと原因不明のエラーにしか見えないため）
            try:
                md = render_markdown(url, score_page(url, checks, mode, history))
            except Exception as e:
                self._send(500, {"status": "ERROR", "error": {
                    "message": "判定できませんでした。", "details": str(e)[:300]}})
                return
            self._send(200, {"outputs": md})
            return

        # 非同期
        rid = str(uuid.uuid4())
        created = _now()
        with _JOBS_LOCK:
            _JOBS[rid] = {"request_id": rid, "status": "PENDING",
                          "progress": "受け付けました... ステップ 0/2",
                          "created_at": created, "updated_at": created}
        threading.Thread(target=self._run_job, args=(rid, url, checks, mode, history),
                         daemon=True).start()
        self._send(202, {"outputs": "リクエストを受け付けました", "request_id": rid,
                         "status": "PENDING", "status_url": f"/status/{rid}"})

    def _run_job(self, rid, url, checks, mode, history):
        try:
            time.sleep(1.0)
            with _JOBS_LOCK:
                _JOBS[rid].update(status="IN_PROGRESS",
                                  progress="ページ取得中... ステップ 1/2",
                                  updated_at=_now())
            time.sleep(1.0)
            result = score_page(url, checks, mode, history)
            md = render_markdown(url, result)
            with _JOBS_LOCK:
                _JOBS[rid].update(status="COMPLETED", outputs=md,
                                  artifacts=[build_artifact(url, result, md)],
                                  progress="処理が完了しました。", updated_at=_now())
        except Exception as e:  # 失敗も仕様どおりの形で返す
            with _JOBS_LOCK:
                _JOBS[rid].update(status="ERROR", updated_at=_now(),
                                  error={"message": "An error occurred during processing.",
                                         "details": repr(e)})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"AI読 源内互換エンドポイント listening on http://127.0.0.1:{PORT}", flush=True)
    print(f"  POST /invoke   POST /requests   GET /status/<id>   GET /request-format", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
