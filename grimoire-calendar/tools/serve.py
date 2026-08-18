#!/usr/bin/env python3
"""Grimoire Calendar — local host + iCal passthrough.

Why this exists at all: Google's iCal endpoint sends no Access-Control-Allow-
Origin header, so a browser refuses to let the page read the feed itself. The
Docket solves this with a Vercel function; this is the same idea with no
deployment, no account, and no Node — stdlib Python only.

It does two things:
  * serves the folder above tools/ as static files
  * answers /ics?cal=<n> by fetching calendar <n> from your config and handing
    the response back same-origin

Run it with:  py -3 tools\\serve.py
or just double-click Grimoire-Calendar.bat, which does the same thing and then
opens the app in its own window.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import re
import socket
import socketserver
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORT = 8787

EMPTY_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "PRODID:-//Grimoire//empty//EN\r\nEND:VCALENDAR\r\n"
)

# Matches   url: 'https://...'   or   url: "https://..."   inside config.js.
# Order matters: the client addresses feeds by index, so entry 0 here must be
# entry 0 there. Blank urls are kept as '' so the indexes never shift.
URL_RE = re.compile(r"""\burl\s*:\s*(['"])(.*?)\1""", re.DOTALL)


def load_calendar_urls() -> list[str]:
    """Read the feed URLs out of config.local.js, falling back to config.js.

    This regex-scrapes a JavaScript file, which is admittedly crude — but it
    keeps ONE source of truth. If the config and the proxy could disagree about
    which calendar is index 2, you would get silently wrong events, which is far
    worse than a parse that occasionally needs a nudge. Keep each `url:` on one
    line and it will be fine.
    """
    for name in ("config.local.js", "config.js"):
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        urls = [m.group(2).strip() for m in URL_RE.finditer(text)]
        if urls:
            print(f"[grimoire] {len(urls)} calendar slot(s) from {name}")
            return urls
    print("[grimoire] no calendars configured yet — see config.example.js")
    return []


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):  # noqa: N802  (stdlib naming)
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path.rstrip("/") == "/ics":
            self.serve_ics(urllib.parse.parse_qs(parsed.query))
            return

        # config.local.js is optional. Serving an empty module when it's absent
        # (rather than a 404) keeps the console clean on a fresh copy AND makes
        # a later failure meaningful: once the file exists, any import error is
        # a real syntax error in it, not just "you haven't made it yet".
        if parsed.path == "/config.local.js" and not os.path.exists(
            os.path.join(ROOT, "config.local.js")
        ):
            body = b"/* no config.local.js yet - see config.example.js */\nexport const CONFIG = null;\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def serve_ics(self, query: dict) -> None:
        urls = load_calendar_urls()
        try:
            index = int(query.get("cal", ["0"])[0])
        except ValueError:
            index = 0

        # An unconfigured or out-of-range feed returns a valid EMPTY calendar
        # rather than an error: one blank slot must not fail the whole sync.
        url = urls[index] if 0 <= index < len(urls) else ""
        if not url:
            self.send_ics(EMPTY_ICS.encode("utf-8"), source="unconfigured")
            return

        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        if not url.lower().startswith(("http://", "https://")):
            self.send_error(400, "Calendar URL must be http(s)")
            return

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Grimoire/1.0"})
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read()
        except urllib.error.HTTPError as err:
            self.send_error(502, f"Calendar {index} responded {err.code}")
            return
        except Exception as err:  # noqa: BLE001 — surface the reason to the UI
            self.send_error(502, f"Could not reach calendar {index}: {err}")
            return

        self.send_ics(body, source=f"upstream:{index}")

    def send_ics(self, body: bytes, source: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Grimoire-Source", source)  # Cache-Control set in end_headers
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        """Force revalidation on every static file.

        Without this the browser holds onto grimoire.css and app.js, so you edit
        dayMark(), reload, and see absolutely no change — then waste twenty
        minutes doubting the edit rather than the cache. Nothing here is served
        over a network worth optimising for; correctness beats a saved request.
        """
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        """Quieten the log to just the feed traffic and real errors.

        args[0] is NOT always a string: log_error() passes an HTTPStatus enum,
        so testing `"/ics" in args[0]` raises TypeError — inside the request
        thread, which kills the connection mid-response and hands the browser an
        empty reply. That looks exactly like a broken app, and it is not.
        """
        try:
            line = fmt % args
        except Exception:  # noqa: BLE001 — logging must never break a request
            line = str(fmt)
        if "/ics" in line or " 404 " in line or "code 4" in line or "code 5" in line:
            sys.stderr.write(f"[grimoire] {line}\n")


class Server(socketserver.ThreadingTCPServer):
    """Threading matters: the page fetches several feeds at once, and a single-
    threaded server would serialise them behind each other (and deadlock if a
    feed is slow while the browser waits on a static asset)."""

    allow_reuse_address = True
    daemon_threads = True


def find_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"No free port in {preferred}–{preferred + 19}")


BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]


def open_app_window(url: str) -> None:
    """Open in Brave's app mode — no tabs, no address bar, its own taskbar entry.

    This is what makes it feel like a program rather than a web page. Falls back
    to the default browser if Brave isn't where we expect it.
    """
    for path in BRAVE_PATHS:
        if os.path.exists(path):
            os.spawnv(os.P_NOWAIT, path, [f'"{path}"', f"--app={url}"])
            return
    webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Grimoire Calendar locally.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="don't launch a browser")
    args = parser.parse_args()

    port = find_port(args.port)
    url = f"http://localhost:{port}/"

    with Server(("127.0.0.1", port), Handler) as httpd:
        print(f"[grimoire] serving {ROOT}")
        print(f"[grimoire] {url}   (Ctrl-C to stop)")
        if not args.no_open:
            threading.Timer(0.6, open_app_window, args=[url]).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[grimoire] closed")


if __name__ == "__main__":
    main()
