#!/usr/bin/env python3
"""源内Web(genai-web)フロント用 ローカルスタブ・バックエンド

目的: AWS(CloudFormation/Cognito/Lambda/DynamoDB)を一切使わずに、
      源内Webフロントの「AIアプリ(ExApp)」画面を動かすための最小API。
      実行(invoke)は自作のAI読APIサーバ(既定 http://127.0.0.1:8791/invoke)へ転送する。

実装しているのはフロントが実際に叩く経路だけ（packages/web/src の grep 結果に基づく）:
  GET  /exapps                                  -> ListExAppsResponse
  GET  /teams/{teamId}/exapps/{exAppId}         -> ExApp
  GET  /exapps/histories?teamId=&exAppId=       -> ListInvokeExAppHistoriesResponse
  GET  /exapps/history?...                      -> GetInvokeExAppHistoryResponse
  POST /exapps/invoke                           -> InvokeExAppResponse
  GET  /teams                                   -> チーム一覧(最小)
Python標準ライブラリのみ。
"""

import json
import os
import time
import urllib.error
import uuid
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.environ.get("STUB_PORT", "8787"))
AIDOKU_URL = os.environ.get("AIDOKU_URL", "http://127.0.0.1:8791/invoke")

# 実行履歴（源内の「このアプリの利用履歴」に出す）。プロセス内に保持する。
HISTORY = []
HISTORY_MAX = 40
AIDOKU_API_KEY = os.environ.get("AIDOKU_API_KEY", "dev-local-key")

HERE = os.path.dirname(os.path.abspath(__file__))
REQUEST_FORMAT_PATH = os.environ.get(
    "REQUEST_FORMAT_PATH",
    os.path.join(os.path.dirname(HERE), "feasibility", "gennai_app", "request_format.json"),
)

with open(REQUEST_FORMAT_PATH, encoding="utf-8") as f:
    PLACEHOLDER = f.read()

TEAM_ID = "team-aidoku"
EXAPP_ID = "aidoku"
NOW = "2026-07-26T00:00:00.000Z"

EXAPP = {
    "teamId": TEAM_ID,
    "exAppId": EXAPP_ID,
    "exAppName": "AI読（アイドク）",
    "endpoint": AIDOKU_URL,
    "placeholder": PLACEHOLDER,
    "description": "自治体サイトの手続きページが「読んで分かるか」を採点し、処方箋を出します。",
    "howToUse": "診断したいページのURLを入力して実行してください。\n\n※ローカル検証用のスタブ・バックエンド経由で動作しています。",
    "apiKey": AIDOKU_API_KEY,
    "copyable": True,
    "status": "published",
    "createdDate": NOW,
    "updatedDate": NOW,
}

TEAM = {"teamId": TEAM_ID, "teamName": "AI読 検証チーム", "createdDate": NOW, "updatedDate": NOW}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/exapps":
            return self._json(200, [dict(EXAPP, teamName=TEAM["teamName"])])

        if path == "/exapps/histories":
            return self._json(200, {"history": list(reversed(HISTORY)),
                                    "lastEvaluatedKey": None})

        if path == "/exapps/history":
            return self._json(404, {"message": "history not found (stub)"})

        if path == "/teams":
            return self._json(200, {"teams": [TEAM], "lastEvaluatedKey": None})

        parts = [p for p in path.split("/") if p]
        # /teams/{teamId}/exapps/{exAppId}
        if len(parts) == 4 and parts[0] == "teams" and parts[2] == "exapps":
            return self._json(200, EXAPP)
        # /teams/{teamId}/exapps
        if len(parts) == 3 and parts[0] == "teams" and parts[2] == "exapps":
            return self._json(200, {"teamExApps": [EXAPP], "lastEvaluatedKey": None})

        return self._json(404, {"message": f"not implemented in stub: GET {path}"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if path != "/exapps/invoke":
            return self._json(404, {"message": f"not implemented in stub: POST {path}"})

        started = now_iso()
        upstream_payload = json.dumps(
            {"inputs": body.get("inputs", {})}, ensure_ascii=False
        ).encode("utf-8")
        req = urllib.request.Request(
            AIDOKU_URL,
            data=upstream_payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": EXAPP["apiKey"],
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                upstream = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            return self._json(
                502, {"message": f"AI読API HTTP {e.code}", "detail": detail}
            )
        except Exception as e:  # noqa: BLE001
            return self._json(502, {"message": f"AI読APIに接続できません: {e!r}"})

        ended = now_iso()
        out = {
            "outputs": upstream.get("outputs", ""),
            "timestamps": {"processingStartedAt": started, "processingEndedAt": ended},
        }
        # 利用履歴に積む（源内の画面右側に出る）
        inputs_in = body.get("inputs", {}) or {}
        target = str(inputs_in.get("url", ""))
        # 一覧の見出し。判定結果からスコア行を拾えたらそれを使う
        title = target.replace("https://", "").replace("http://", "")[:48]
        for line in (out["outputs"] or "").splitlines():
            if line.startswith("# AI読 診断結果"):
                title = line.replace("# ", "").strip()
            if "スコア:" in line:
                title = f"{title}（{line.split('スコア:')[1].strip().replace('**','')}）"
                break
        HISTORY.append({
            "invokeExAppHistoryId": uuid.uuid4().hex,
            "teamId": EXAPP.get("teamId", "team-aidoku"),
            "exAppId": EXAPP.get("exAppId", "aidoku"),
            "exAppName": EXAPP.get("exAppName", "AI読（アイドク）"),
            "status": "COMPLETED",
            # フロントは createdDate をエポックミリ秒として扱う
            # （ExAppInvokedHistoryItem.tsx: new Date(Number(history.createdDate))）
            "createdDate": str(int(time.time() * 1000)),
            "predictedTitle": title,
            "inputs": inputs_in,
            "outputs": out["outputs"],
            "createdAt": started,
            "updatedAt": ended,
            "timestamps": out["timestamps"],
        })
        del HISTORY[:-HISTORY_MAX]
        if upstream.get("artifacts"):
            out["artifacts"] = upstream["artifacts"]
        return self._json(200, out)

    def log_message(self, fmt, *args):
        super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"stub backend (源内Web team API) listening on http://127.0.0.1:{PORT}", flush=True)
    print(f"  -> AI読API: {AIDOKU_URL}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
