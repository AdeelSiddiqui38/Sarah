import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sarah_core as sc

HITS = []


class FakeHub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok(self, body, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        HITS.append(("GET", self.path))
        if self.path == "/":
            return self._ok(b"<html>Command Center</html>", "text/html")
        self._ok(json.dumps({"path": self.path}).encode())

    def do_POST(self):
        HITS.append(("POST", self.path))
        self._ok(b'{"ok": true}')


class TradingProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        sc.DATA_DIR = Path(cls.tmp.name)
        sc.DB_PATH = sc.DATA_DIR / "sarah.db"
        sc.init_db()
        cls.hub = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
        threading.Thread(target=cls.hub.serve_forever, daemon=True).start()
        sc.TRADING_HUB_URL = f"http://127.0.0.1:{cls.hub.server_port}"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), sc.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        sc.EXTRA_ORIGINS.append(cls.base)
        cls.cookie = "sarah_session=" + sc.new_session()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.hub.shutdown(); cls.tmp.cleanup()

    def req(self, path, method="GET", cookie=True, origin=None, data=None):
        h = {"Cookie": self.cookie} if cookie else {}
        if origin:
            h["Origin"] = origin
        r = urllib.request.Request(self.base + path, method=method, headers=h, data=data)
        opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a: None}))
        try:
            with opener.open(r, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_logged_out_is_sent_to_login(self):
        code, _, h = self.req("/trading/", cookie=False)
        self.assertEqual((code, h.get("Location")), (302, "/"))

    def test_dashboard_and_api_are_proxied(self):
        code, body, _ = self.req("/trading/")
        self.assertEqual((code, body), (200, b"<html>Command Center</html>"))
        code, body, _ = self.req("/trading/api/state?x=1")
        self.assertEqual(json.loads(body)["path"], "/api/state?x=1")
        self.assertEqual(self.req("/trading")[0], 302)

    def test_keys_page_and_hub_controls_are_blocked(self):
        for p in ("/trading/secrets", "/trading/api/secrets/status"):
            self.assertEqual(self.req(p)[0], 403, p)
        before = len(HITS)
        for p in ("/trading/api/shutdown", "/trading/api/sync", "/trading/api/secrets"):
            self.assertEqual(self.req(p, "POST", origin=self.base, data=b"{}")[0], 403, p)
        self.assertEqual(len(HITS), before)

    def test_phone_view(self):
        self.assertEqual(self.req("/trading-m", cookie=False)[0], 302)
        code, body, _ = self.req("/trading-m")
        self.assertEqual(code, 200)
        self.assertIn(b"<title>Trading (phone)</title>", body)

    def test_post_needs_sarah_origin(self):
        self.assertEqual(self.req("/trading/api/service/gappers/restart", "POST", origin="https://evil.example", data=b"")[0], 403)
        code, body, _ = self.req("/trading/api/service/gappers/restart", "POST", origin=self.base, data=b"")
        self.assertEqual((code, json.loads(body)), (200, {"ok": True}))
        self.assertEqual(HITS[-1], ("POST", "/api/service/gappers/restart"))


if __name__ == "__main__":
    unittest.main()
