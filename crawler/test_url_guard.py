"""SSRFガードのテスト。ネットワークには一切出ない（resolve を差し替える）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from url_guard import UrlNotAllowed, check_url, ip_reason, is_allowed  # noqa: E402

PUBLIC = ["93.184.216.34"]


def fixed(*addrs):
    return lambda host: list(addrs)


def boom(host):
    raise OSError("gaierror")


class IpReason(unittest.TestCase):
    def test_公開アドレスは通す(self):
        self.assertIsNone(ip_reason("93.184.216.34"))
        self.assertIsNone(ip_reason("2606:2800:220:1:248:1893:25c8:1946"))

    def test_クラウドのメタデータ宛は拒否(self):
        # ここが本命。robots.txt が404を返すと全許可へ倒れる経路を塞ぐ
        self.assertIn("リンクローカル", ip_reason("169.254.169.254"))

    def test_ループバックは拒否(self):
        self.assertIn("ループバック", ip_reason("127.0.0.1"))
        self.assertIn("ループバック", ip_reason("::1"))

    def test_プライベートは拒否(self):
        for a in ("10.0.0.5", "172.16.0.1", "192.168.1.1"):
            self.assertIn("プライベート", ip_reason(a), a)

    def test_未指定とマルチキャストは拒否(self):
        self.assertIn("未指定", ip_reason("0.0.0.0"))
        self.assertIn("マルチキャスト", ip_reason("224.0.0.1"))

    def test_IPv4射影で内部を隠せない(self):
        self.assertIn("ループバック", ip_reason("::ffff:127.0.0.1"))
        self.assertIn("プライベート", ip_reason("::ffff:10.0.0.1"))

    def test_アドレスでない文字列(self):
        self.assertIn("読めない", ip_reason("not-an-ip"))


class CheckUrl(unittest.TestCase):
    def test_公開ホストは通る(self):
        check_url("https://www.city.minato.tokyo.jp/a.html", resolve=fixed(*PUBLIC))

    def test_httpとhttps以外は拒否(self):
        for u in ("file:///etc/passwd", "gopher://a.jp/", "ftp://a.jp/"):
            with self.assertRaises(UrlNotAllowed, msg=u):
                check_url(u, resolve=fixed(*PUBLIC))

    def test_ホスト名が無ければ拒否(self):
        with self.assertRaises(UrlNotAllowed):
            check_url("http:///a.html", resolve=fixed(*PUBLIC))

    def test_空URLは拒否(self):
        for u in ("", "   ", None):
            with self.assertRaises(UrlNotAllowed):
                check_url(u, resolve=fixed(*PUBLIC))

    def test_名前を解決できなければ拒否(self):
        # 分からないものは通さない（fail-closed）
        with self.assertRaises(UrlNotAllowed) as cm:
            check_url("https://nowhere.invalid/a", resolve=boom)
        self.assertIn("解決できない", str(cm.exception))

    def test_解決結果が空でも拒否(self):
        with self.assertRaises(UrlNotAllowed):
            check_url("https://a.jp/", resolve=fixed())

    def test_内部アドレスに解決されたら拒否(self):
        with self.assertRaises(UrlNotAllowed) as cm:
            check_url("https://evil.example/a", resolve=fixed("169.254.169.254"))
        self.assertIn("リンクローカル", str(cm.exception))

    def test_1件でも内部が混ざれば拒否(self):
        # DNS rebinding 対策。公開アドレスに紛れ込ませても通さない
        with self.assertRaises(UrlNotAllowed):
            check_url("https://evil.example/a", resolve=fixed("93.184.216.34", "127.0.0.1"))

    def test_localhost直書きも拒否(self):
        with self.assertRaises(UrlNotAllowed):
            check_url("http://localhost:8080/admin", resolve=fixed("127.0.0.1"))

    def test_is_allowedは例外を投げない(self):
        self.assertTrue(is_allowed("https://a.jp/", resolve=fixed(*PUBLIC)))
        self.assertFalse(is_allowed("http://a.jp/", resolve=fixed("10.0.0.1")))


if __name__ == "__main__":
    unittest.main()
