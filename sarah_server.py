"""
Sarah local server.

Three jobs:
1. Serves the BRAIN folder over http://127.0.0.1:8765 so the avatar page
   has a stable origin (Chrome doesn't reliably remember microphone
   permission on file:// pages, but does over localhost).
2. Proxies OpenAI chat requests server-side at POST /proxy/openai.
   OpenAI's API does not send CORS headers, so a browser page can never
   call api.openai.com directly (Anthropic's API is the exception — it
   has an explicit opt-in header for direct browser calls). Routing the
   request through this local script sidesteps that entirely: Python
   making the call has no CORS restriction, and the browser is just
   talking to its own same-origin server.
3. Proxies GitHub REST API calls server-side at POST /proxy/github, same
   reasoning — GitHub's API doesn't allow a personal access token to be
   used from a browser via CORS either. This one is generic (method +
   path + body) rather than hard-coded to one endpoint, since GitHub's
   API surface is huge — the AI decides which endpoint to hit and this
   just forwards it with the token attached.

Nothing leaves your PC except the actual API request itself, made with
whatever key/token the browser sends over for that one call.
"""

import http.server
import json
import socketserver
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8765
BASE_DIR = Path(__file__).resolve().parent  # portable: Mac + Windows
AVATAR_FILE = "/sarah-avatar-ui.html"
OPENAI_PROXY_PATH = "/proxy/openai"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GITHUB_PROXY_PATH = "/proxy/github"
GITHUB_API_BASE = "https://api.github.com"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # quiet — runs silently in the background via pythonw

    def send_head(self):
        # Serve the avatar at the bare root, so the address bar reads
        # "127.0.0.1:8765" instead of trailing the whole filename. Done as a
        # rewrite rather than a redirect on purpose: a redirect would put the
        # long path back in the address bar, which defeats the point. There is
        # no index.html in this folder, so without this "/" would render a
        # directory listing of the BRAIN folder instead.
        if self.path in ("/", "/index.html"):
            self.path = AVATAR_FILE
        return super().send_head()

    def end_headers(self):
        # Serving sarah-avatar-ui.html over http:// (instead of file://)
        # means the browser can now cache it like a normal web page — which
        # has repeatedly caused edits to silently not take effect even after
        # a reload. Force every response to be treated as always-stale.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def do_POST(self):
        if self.path == OPENAI_PROXY_PATH:
            self._proxy_openai()
        elif self.path == GITHUB_PROXY_PATH:
            self._proxy_github()
        else:
            self.send_error(404)

    def _proxy_openai(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "Bad JSON")
            return

        api_key = payload.pop("_apiKey", None)
        if not api_key:
            self._send_json(400, {"error": "Missing API key"})
            return

        req = urllib.request.Request(
            OPENAI_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self._send_json(resp.status, None, raw_body=resp.read())
        except urllib.error.HTTPError as e:
            self._send_json(e.code, None, raw_body=e.read())
        except Exception as e:
            self._send_json(502, {"error": str(e)})

    def _proxy_github(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "Bad JSON")
            return

        token = payload.get("_token")
        method = (payload.get("method") or "GET").upper()
        path = payload.get("path") or ""
        body = payload.get("body")

        if not token:
            self._send_json(400, {"error": "Missing GitHub token"})
            return
        if not path.startswith("/"):
            self._send_json(400, {"error": "path must start with /, e.g. /repos/owner/repo/issues"})
            return
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            self._send_json(400, {"error": f"Unsupported method {method}"})
            return

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            GITHUB_API_BASE + path,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                # GitHub's API rejects requests with no User-Agent.
                "User-Agent": "Sarah-local-assistant",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self._send_json(resp.status, None, raw_body=resp.read())
        except urllib.error.HTTPError as e:
            self._send_json(e.code, None, raw_body=e.read())
        except Exception as e:
            self._send_json(502, {"error": str(e)})

    def _send_json(self, status, obj, raw_body=None):
        body = raw_body if raw_body is not None else json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
