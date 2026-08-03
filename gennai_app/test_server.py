"""源内AIアプリAPIのテスト — 「仕様に準拠」という主張の中身を固定する。

提出フォームにも README にも「源内のAIアプリAPI仕様に準拠した独立API」と書いている。
その準拠が本当かどうかは、いままで手で叩いて目で見るしかなかった。

本物のサーバを 127.0.0.1 の空きポートで立てて、HTTPで叩く。
判定そのもの（`claude -p` を呼ぶ部分）は差し替える。ここで見たいのは
「仕様どおりの受け答えをするか」であって判定の中身ではない。

標準ライブラリのみ。

実行: python3 -m unittest discover -s gennai_app -p 'test_*.py'
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402

KEY = server.API_KEY


class ServerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # アクセスログでテスト出力が埋まるので黙らせる
        cls._quiet = mock.patch.object(server.Handler, "log_message", lambda *a, **k: None)
        cls._quiet.start()
        cls.httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._quiet.stop()

    def call(self, method, path, *, body=None, key=KEY, raw_body=None):
        data = None
        if raw_body is not None:
            data = raw_body.encode("utf-8")
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if key is not None:
            req.add_header("x-api-key", key)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class AuthTest(ServerTestBase):
    """認証は x-api-key ヘッダ（仕様のcurl例に準拠）。"""

    def test_鍵が無ければ401(self):
        code, body = self.call("POST", "/invoke", body={"inputs": {"url": "https://a.lg.jp/"}},
                               key=None)
        self.assertEqual(code, 401)
        self.assertEqual(body["status"], "ERROR")

    def test_鍵が違えば401(self):
        code, _ = self.call("POST", "/invoke", body={"inputs": {"url": "https://a.lg.jp/"}},
                            key="wrong-key")
        self.assertEqual(code, 401)

    def test_statusの参照にも鍵が要る(self):
        code, _ = self.call("GET", "/status/none", key=None)
        self.assertEqual(code, 401)

    def test_healthzは鍵なしで見られる(self):
        code, body = self.call("GET", "/healthz", key=None)
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")


class RequestShapeTest(ServerTestBase):
    """入力の形。仕様は {"inputs": {...}} でくるむこと。"""

    def test_inputsで包んでいなければ400(self):
        code, body = self.call("POST", "/invoke", body={"url": "https://a.lg.jp/"})
        self.assertEqual(code, 400)
        self.assertIn("inputs", body["error"]["message"])

    def test_壊れたJSONは400(self):
        code, body = self.call("POST", "/invoke", raw_body="{壊れている")
        self.assertEqual(code, 400)
        self.assertEqual(body["status"], "ERROR")

    def test_request_formatを返す(self):
        code, body = self.call("GET", "/request-format", key=None)
        self.assertEqual(code, 200)
        self.assertIsInstance(body, dict)

    def test_知らないパスは404(self):
        for method, path in [("GET", "/nope"), ("POST", "/nope")]:
            with self.subTest(method=method):
                code, _ = self.call(method, path)
                self.assertEqual(code, 404)


class BadUrlTest(ServerTestBase):
    """⚠️ 入力ミスは 400 ではなく 200 で返す。理由が server.py にコメントされている。

    400を返すと源内の画面には何も出ず「押しても無反応」に見える。
    利用者の入力ミスはプロトコルエラーではない、という設計判断。
    """

    def test_URLが空でも200で案内を返す(self):
        code, body = self.call("POST", "/invoke", body={"inputs": {"url": ""}})
        self.assertEqual(code, 200)
        self.assertIn("入力を確認してください", body["outputs"])

    def test_httpで始まらないURLは200で案内を返す(self):
        code, body = self.call("POST", "/invoke", body={"inputs": {"url": "港区 転入届"}})
        self.assertEqual(code, 200)
        self.assertIn("入力を確認してください", body["outputs"])

    def test_URLが無い場合も200(self):
        code, body = self.call("POST", "/invoke", body={"inputs": {}})
        self.assertEqual(code, 200)
        self.assertIn("URLが空欄です", body["outputs"])


class InvokeTest(ServerTestBase):
    """同期実行。判定そのものは差し替える。"""

    def setUp(self):
        self.p1 = mock.patch.object(server, "score_page", return_value={"dummy": True})
        self.p2 = mock.patch.object(server, "render_markdown", return_value="# 結果\n\n100点")
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)

    def test_200でoutputsを返す(self):
        code, body = self.call("POST", "/invoke",
                               body={"inputs": {"url": "https://a.lg.jp/x.html"}})
        self.assertEqual(code, 200)
        self.assertEqual(body["outputs"], "# 結果\n\n100点")

    def test_判定が落ちても接続を切らず理由を返す(self):
        """無応答だと源内の画面では原因不明のエラーにしか見えない。"""
        with mock.patch.object(server, "score_page", side_effect=RuntimeError("取得に失敗")):
            code, body = self.call("POST", "/invoke",
                                   body={"inputs": {"url": "https://a.lg.jp/x.html"}})
        self.assertEqual(code, 500)
        self.assertEqual(body["status"], "ERROR")
        self.assertIn("取得に失敗", body["error"]["details"])

    def test_checksは未指定なら全項目(self):
        with mock.patch.object(server, "score_page", return_value={}) as m:
            self.call("POST", "/invoke", body={"inputs": {"url": "https://a.lg.jp/x.html"}})
        checks = m.call_args[0][1]
        self.assertEqual(list(checks), list(server.ITEM_LABELS))

    def test_checksはカンマ区切りで絞れる(self):
        target = list(server.ITEM_LABELS)[0]
        with mock.patch.object(server, "score_page", return_value={}) as m:
            self.call("POST", "/invoke",
                      body={"inputs": {"url": "https://a.lg.jp/x.html", "checks": target}})
        self.assertEqual(m.call_args[0][1], [target])

    def test_知らないchecksは黙って捨てる(self):
        with mock.patch.object(server, "score_page", return_value={}) as m:
            self.call("POST", "/invoke",
                      body={"inputs": {"url": "https://a.lg.jp/x.html", "checks": "存在しない項目"}})
        self.assertEqual(m.call_args[0][1], [])


class AsyncTest(ServerTestBase):
    """非同期実行（POST /requests → GET /status/<id>）。"""

    def test_202とrequest_idとstatus_urlを返す(self):
        with mock.patch.object(server, "score_page", return_value={}), \
             mock.patch.object(server, "render_markdown", return_value="ok"):
            code, body = self.call("POST", "/requests",
                                   body={"inputs": {"url": "https://a.lg.jp/x.html"}})
        self.assertEqual(code, 202)
        self.assertEqual(body["status"], "PENDING")
        self.assertTrue(body["request_id"])
        self.assertEqual(body["status_url"], f"/status/{body['request_id']}")

    def test_知らないrequest_idは404(self):
        code, body = self.call("GET", "/status/not-exist")
        self.assertEqual(code, 404)
        self.assertEqual(body["status"], "ERROR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
