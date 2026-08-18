"""
capture_flow.py — daily intraday order-flow capture for the forward-test basket.

Streams live trades + quotes for all 10 symbols from Alpaca's free IEX websocket
(reusing FlowState from alpaca_stream.py) and appends one row per symbol per
minute to cache/flow/flow_<date>.csv:

  ts, symbol, cvd_session, cvd_1m, imbalance, vol_session, trades_n, blocks_n

This builds the INTRADAY flow dataset the daily-granularity test said we'd
need — accumulated free, day by day, alongside the forward test. In ~2 months:
enough history to test CVD gates against real forward trades.

Self-managing: exits immediately if the market is closed; exits at 13:02 PT.
Scheduled daily at 06:28 PT (SwingPro_Flow_Capture). IEX = ~3% sample of tape;
CVD direction is meaningful, absolute volume is not the consolidated total.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # for alpaca_stream
from alpaca_stream import FlowState  # noqa: E402
from data import _env  # noqa: E402

SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META",
           "MSTR", "ORCL", "NFLX", "AVGO", "CRWD"]
FEED = "wss://stream.data.alpaca.markets/v2/iex"
OUT_DIR = Path(__file__).parent / "cache" / "flow"
CLOSE_LOCAL = dtime(13, 2)   # PT


def _clock() -> dict:
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/clock",
        headers={"APCA-API-KEY-ID": _env("APCA_API_KEY_ID"),
                 "APCA-API-SECRET-KEY": _env("APCA_API_SECRET_KEY")})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def market_open() -> bool:
    """True once the market is open. The task fires at 06:28 PT — two minutes
    BEFORE the 06:30 open — so when the open is near, wait for it. The
    pre-2026-07-14 immediate exit killed every session's capture after day 1."""
    from datetime import timezone

    c = _clock()
    if c.get("is_open"):
        return True
    nxt = c.get("next_open")
    if not nxt:
        return False
    try:
        dt = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
        wait = (dt - datetime.now(timezone.utc)).total_seconds()
    except ValueError:
        return False
    if 0 < wait <= 45 * 60:
        print(f"market opens in {wait/60:.1f} min - waiting", file=sys.stderr)
        time.sleep(wait + 5)
        return _clock().get("is_open", False)
    return False


def main():
    if not market_open():
        print("market closed - exiting")
        return
    import websocket  # websocket-client

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_f = OUT_DIR / f"flow_{datetime.now():%Y%m%d}.csv"
    new = not out_f.exists()
    fh = open(out_f, "a", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    if new:
        wr.writerow(["ts", "symbol", "cvd_session", "cvd_1m", "imbalance",
                     "vol_session", "trades_n", "blocks_n"])

    states = {s: FlowState(s, block_size=5000, roll_seconds=60) for s in SYMBOLS}
    last = {s: {"cvd": 0, "blocks": 0} for s in SYMBOLS}
    flush_at = {"t": time.monotonic() + 60}

    def flush():
        now = datetime.now().isoformat(timespec="seconds")
        for s, fs in states.items():
            wr.writerow([now, s, fs.cvd, fs.cvd - last[s]["cvd"],
                         round(fs.imbalance(), 4), fs.total_vol, fs.n_trades,
                         len(fs.blocks) - last[s]["blocks"]])
            last[s]["cvd"] = fs.cvd
            last[s]["blocks"] = len(fs.blocks)
        fh.flush()

    def on_open(ws):
        ws.send(json.dumps({"action": "auth", "key": _env("APCA_API_KEY_ID"),
                            "secret": _env("APCA_API_SECRET_KEY")}))

    def on_message(ws, message):
        try:
            msgs = json.loads(message)
        except json.JSONDecodeError:
            return
        for m in msgs:
            T = m.get("T")
            if T == "success" and m.get("msg") == "authenticated":
                ws.send(json.dumps({"action": "subscribe", "trades": SYMBOLS,
                                    "quotes": SYMBOLS}))
                print(f"authenticated - capturing {len(SYMBOLS)} symbols",
                      file=sys.stderr)
            elif T == "q":
                st = states.get(m.get("S"))
                if st:
                    st.on_quote(m)
            elif T == "t":
                st = states.get(m.get("S"))
                if st:
                    st.on_trade(m)
        if time.monotonic() >= flush_at["t"]:
            flush_at["t"] = time.monotonic() + 60
            flush()
        if datetime.now().time() >= CLOSE_LOCAL:
            flush()
            ws.close()
            sys.exit(0)

    backoff = 2
    while datetime.now().time() < CLOSE_LOCAL:
        ws = websocket.WebSocketApp(FEED, on_open=on_open, on_message=on_message,
                                    on_error=lambda w, e: print(f"[ws] {e}", file=sys.stderr),
                                    on_close=lambda w, c, m: None)
        ws.run_forever(ping_interval=20, ping_timeout=10)
        if datetime.now().time() >= CLOSE_LOCAL:
            break
        print(f"reconnecting in {backoff}s", file=sys.stderr)
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
    fh.close()


if __name__ == "__main__":
    main()
