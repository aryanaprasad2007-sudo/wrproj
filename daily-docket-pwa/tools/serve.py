#!/usr/bin/env python3
"""Local dev server for Daily Docket. Python 3.8+, standard library only.

    py -3 tools/serve.py                 # serve on http://localhost:8080
    py -3 tools/serve.py --port 5173
    py -3 tools/serve.py --demo          # ignore the real calendar, use fake data
    py -3 tools/serve.py --ics "https://calendar.google.com/.../basic.ics"

It does two jobs:

  1. Serves the app as static files (with no-cache headers, so edits show up).
  2. Proxies GET /ics to your secret iCal URL and adds the CORS header Google
     doesn't send. That's the whole reason this script exists — without it the
     browser refuses to read the feed.

The URL is looked up in this order:
    --ics argument  →  $DOCKET_ICS_URL  →  icsUrl in config.local.js  →  config.js
If none of those has one, /ics serves a generated demo calendar so you can see
the app working immediately.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCH_TIMEOUT = 25
UA = "DailyDocket-dev-proxy/1.0"

# The Windows console defaults to cp1252, which chokes on the emoji below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

EMPTY_CALENDAR = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    b"PRODID:-//Daily Docket//empty//EN\r\nEND:VCALENDAR\r\n"
)


# --------------------------------------------------------------------------- #
# finding the calendar URL
# --------------------------------------------------------------------------- #

def calendars_from_config() -> list[dict]:
    """Read the `calendars` list out of config.local.js / config.js.

    Parsed with regexes rather than executed — it's a JS module, and the dev
    server has no business running it. Order is preserved because the client
    addresses feeds positionally as /ics?cal=<index>.
    """
    for name in ("config.local.js", "config.js"):
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")

        block = re.search(r"calendars\s*:\s*\[(.*?)\n\s*\],", text, re.S)
        if block:
            out = []
            # Each { ... } object literal inside the calendars array.
            for entry in re.finditer(r"\{(.*?)\}", block.group(1), re.S):
                body = entry.group(1)
                def field(key):
                    m = re.search(r"""%s\s*:\s*['"]([^'"]*)['"]""" % key, body)
                    return m.group(1).strip() if m else ""
                enabled = not re.search(r"enabled\s*:\s*false", body)
                out.append({
                    "id": field("id") or f"cal{len(out)}",
                    "label": field("label") or f"Calendar {len(out) + 1}",
                    "url": field("url"),
                    "enabled": enabled,
                })
            if out:
                return out

        # Fall back to a single legacy icsUrl.
        match = re.search(r"""icsUrl\s*:\s*['"]([^'"]*)['"]""", text)
        if match and match.group(1).strip():
            return [{"id": "default", "label": "Calendar", "url": match.group(1).strip(),
                     "enabled": True}]
    return []


def resolve_calendars(cli_value: str | None) -> list[dict]:
    """--ics wins, then $DOCKET_ICS_URL, then whatever config.js lists."""
    if cli_value and cli_value.strip():
        return [{"id": "cli", "label": "Calendar (--ics)", "enabled": True,
                 "url": cli_value.strip().replace("webcal://", "https://")}]

    env = os.environ.get("DOCKET_ICS_URL", "").strip()
    if env:
        # Accept several, comma or newline separated, optionally "Label|url".
        out = []
        for i, raw in enumerate(re.split(r"[,\n]+", env)):
            raw = raw.strip()
            if not raw:
                continue
            label, _, url = raw.rpartition("|")
            out.append({"id": f"env{i}", "label": label.strip() or f"Calendar {i + 1}",
                        "enabled": True, "url": url.strip().replace("webcal://", "https://")})
        if out:
            return out

    cals = calendars_from_config()
    for c in cals:
        c["url"] = c["url"].replace("webcal://", "https://")
    return cals


# --------------------------------------------------------------------------- #
# demo calendar — generated relative to right now so it always looks alive
# --------------------------------------------------------------------------- #

def demo_calendar() -> bytes:
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    def stamp(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%S")

    def day(dt: datetime) -> str:
        return dt.strftime("%Y%m%d")

    def timed(uid, summary, start, minutes, location="", transp="OPAQUE", extra=""):
        end = start + timedelta(minutes=minutes)
        return (
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}@demo.docket\r\n"
            f"DTSTAMP:{stamp(now)}Z\r\n"
            f"DTSTART;TZID=Demo/Local:{stamp(start)}\r\n"
            f"DTEND;TZID=Demo/Local:{stamp(end)}\r\n"
            f"SUMMARY:{summary}\r\n"
            + (f"LOCATION:{location}\r\n" if location else "")
            + f"TRANSP:{transp}\r\n"
            + extra
            + "END:VEVENT\r\n"
        )

    def allday(uid, summary, date):
        return (
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}@demo.docket\r\n"
            f"DTSTAMP:{stamp(now)}Z\r\n"
            f"DTSTART;VALUE=DATE:{day(date)}\r\n"
            f"DTEND;VALUE=DATE:{day(date + timedelta(days=1))}\r\n"
            f"SUMMARY:{summary}\r\n"
            "TRANSP:TRANSPARENT\r\n"
            "END:VEVENT\r\n"
        )

    # A VTIMEZONE block so the timezone-registration path gets exercised too.
    offset = now.astimezone().utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    off = f"{sign}{abs(total)//3600:02d}{(abs(total)//60)%60:02d}"

    parts = [
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Daily Docket//demo feed//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "X-WR-CALNAME:Docket Demo\r\n"
        "BEGIN:VTIMEZONE\r\n"
        "TZID:Demo/Local\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:19700101T000000\r\n"
        f"TZOFFSETFROM:{off}\r\n"
        f"TZOFFSETTO:{off}\r\n"
        "TZNAME:LOCAL\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
    ]

    # ---- today -----------------------------------------------------------
    parts += [
        allday("bday", "🎂 Maya's birthday", today),
        allday("milestone", "Week 4 of summer session", today),
        timed("gym", "Gym — push day", today + timedelta(hours=7), 75, "RecCenter"),
        timed("lecture", "BIO 20A lecture", today + timedelta(hours=9, minutes=30), 80, "Thimann 003"),
        timed("lunch", "Lunch + walk", today + timedelta(hours=12), 45),
        # A repeating block, to exercise RRULE expansion.
        timed(
            "market", "Market open — watchlist review",
            today.replace(hour=6, minute=30) - timedelta(days=30), 30,
            extra="RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\n",
        ),
        # The one that should win the spotlight.
        timed("lab", "Lab 3 report due ⏰", today + timedelta(hours=23, minutes=59), 1, "Canvas"),
        timed("study", "Deep work — problem set", now + timedelta(hours=2), 120, "Library"),
        timed("call", "Call with advisor", now + timedelta(minutes=40), 30),
        # These two must NOT appear: overlay prefix, and a free/transparent block.
        timed("wr1", "WR · ambient focus overlay", now + timedelta(minutes=15), 180),
        timed("wr2", "WR - secondary overlay", now + timedelta(hours=4), 60),
        timed("free", "Tentative hangout (free)", now + timedelta(hours=5), 90, transp="TRANSPARENT"),
        timed("cancelled", "Cancelled thing", now + timedelta(hours=3), 60,
              extra="STATUS:CANCELLED\r\n"),
    ]

    # ---- tomorrow --------------------------------------------------------
    parts += [
        allday("tmw-milestone", "🌱 30-day streak", tomorrow),
        timed("t-gym", "Gym — pull day", tomorrow + timedelta(hours=7), 75, "RecCenter"),
        timed("t-lab", "CHEM 1B lab", tomorrow + timedelta(hours=10), 180, "PSB 240"),
        timed("t-exam", "Midterm exam", tomorrow + timedelta(hours=14), 120, "Classroom Unit 2"),
        timed("t-dance", "Dance rehearsal", tomorrow + timedelta(hours=18, minutes=30), 90),
        timed("t-wr", "WR · overlay", tomorrow + timedelta(hours=9), 60),
    ]

    parts.append("END:VCALENDAR\r\n")
    return "".join(parts).encode("utf-8")


# --------------------------------------------------------------------------- #
# request handling
# --------------------------------------------------------------------------- #

class DocketHandler(SimpleHTTPRequestHandler):
    calendars: list = []
    demo: bool = False
    ics_file: str | None = None

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".webmanifest": "application/manifest+json",
        ".ics": "text/calendar",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
        "": "application/octet-stream",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # -- logging: quieter, and it says which day it is ----------------------
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s  %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self):
        # No caching in dev, or you'll chase ghosts after every edit.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Service-Worker-Allowed", "/")
        super().end_headers()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path.rstrip("/") in ("/ics", "/api/ics"):
            self.serve_ics(query)
            return
        super().do_GET()

    def send_calendar(self, body: bytes, source: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Docket-Source", source)
        self.end_headers()
        self.wfile.write(body)

    def serve_ics(self, query: str):
        params = urllib.parse.parse_qs(query)
        try:
            index = int(params.get("cal", ["0"])[0])
        except ValueError:
            index = 0

        # A file beats everything: handy for testing against an exported .ics.
        if self.ics_file:
            try:
                self.send_calendar(Path(self.ics_file).read_bytes(), "file")
            except OSError as err:
                self.send_error(502, f"Could not read {self.ics_file}: {err}")
            return

        if self.demo or not self.calendars:
            # One demo feed only — anything past the first index is empty, so
            # the client sees "this calendar has nothing" rather than duplicates.
            body = demo_calendar() if index == 0 else EMPTY_CALENDAR
            self.send_calendar(body, "demo")
            return

        if index >= len(self.calendars):
            self.send_calendar(EMPTY_CALENDAR, "out-of-range")
            return

        cal = self.calendars[index]
        if not cal.get("url"):
            # Configured but no URL yet — an empty calendar keeps the other
            # feeds working instead of failing the whole sync.
            self.send_calendar(EMPTY_CALENDAR, f"unconfigured:{cal['id']}")
            return

        req = urllib.request.Request(cal["url"], headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as upstream:
                body = upstream.read()
        except urllib.error.HTTPError as err:
            self.send_error(502, f"{cal['label']} responded {err.code}")
            return
        except Exception as err:                      # noqa: BLE001 - report anything
            self.send_error(502, f"Could not reach {cal['label']}: {err}")
            return

        self.send_calendar(body, f"upstream:{cal['id']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily Docket dev server")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 to reach it from your phone on the same wifi")
    ap.add_argument("--ics", help="a single secret iCal URL (overrides config and env)")
    ap.add_argument("--ics-file", help="serve this local .ics for every feed (offline testing)")
    ap.add_argument("--demo", action="store_true", help="always serve the generated demo feed")
    ap.add_argument("--open", action="store_true", help="open a browser window")
    args = ap.parse_args()

    DocketHandler.calendars = resolve_calendars(args.ics)
    DocketHandler.ics_file = args.ics_file

    # Nothing filled in anywhere → show the demo feed rather than a blank docket,
    # so a fresh clone does something interesting on the first run.
    # Only enabled feeds count: config.js ships with Holidays and Moreau
    # pre-filled but switched off, and those shouldn't suppress the demo.
    nothing_configured = not any(
        c.get("url") for c in DocketHandler.calendars if c.get("enabled", True)
    )
    DocketHandler.demo = args.demo or (nothing_configured and not args.ics_file)

    url = f"http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}/"
    print("\n  🗓️  Daily Docket dev server")
    print(f"      serving  {ROOT}")

    if args.ics_file:
        print(f"      /ics     →  {args.ics_file} (local file, all feeds)")
    elif DocketHandler.demo:
        print("      /ics     →  generated demo feed")
        if nothing_configured and not args.demo:
            print("                  (no calendar URLs in config.js yet — add them there,")
            print("                   or open the app and use ⚙ Settings)")
    else:
        for i, cal in enumerate(DocketHandler.calendars):
            if not cal.get("enabled", True):
                state = "off"
            elif cal["url"]:
                state = cal["url"][:44] + "…" if len(cal["url"]) > 44 else cal["url"]
            else:
                state = "— no URL yet, serving an empty calendar"
            print(f"      /ics?cal={i}  {cal['label']:<14} {state}")

    print(f"\n      open     {url}\n")

    if args.open:
        webbrowser.open(url)

    try:
        with ThreadingHTTPServer((args.host, args.port), DocketHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  bye 👋\n")
    except OSError as err:
        print(f"\n  could not bind {args.host}:{args.port} — {err}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
