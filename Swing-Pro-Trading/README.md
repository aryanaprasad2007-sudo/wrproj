# iAPE (formerly SWING_PRO / Swing-Pro-Trading) — file map

*Product renamed to **iAPE** on 2026-07-14 — same engine, same evidence, new name.
Folder, scheduled-task names (`SwingPro_*`), env vars (`SWINGPRO_BROKER`), and the
`swing_pro.py` module keep their old identifiers on purpose: they are live plumbing
for the running forward tests, and renaming them mid-audition risks silent breakage.
Consolidated 2026-07-01. One live Pine script; everything it replaced is in `legacy/`.*

## Live — the iAPE TradingView kit

| File | What it is |
|---|---|
| **`iAPE_v4.pine`** | **THE script** (formerly `SWING_PRO_v3.pine`; v4 = rebrand, engine v2.2 unchanged). Strategy + signals + alerts + plain-English dashboard, Mode selector (Validated v2.2 / Strict / Comfort), auto daily-flagship config on D charts, live stop/target lines. Flagship use: **DAILY charts** (30y validated); 5m = running experiment. Default = longs only. |
| `iAPE_XRAY.pine` | Idea engine: 7 gate heat-rows, 0–7 confluence score, near-miss diamonds, live "why no trade" table. |
| `iAPE_MR.pine` | Strategy #2 — MR-1 daily mean-reversion (RSI(3)<15 in uptrend). Per-symbol Pine can't enforce the validated portfolio caps — judge across a watchlist. |
| `iAPE_Backflow.pine` | Lower-pane order-flow proxy (CVD, divergences, blocks, absorption; formerly `OrderFlow_Proxy.pine`). Wires into iAPE_v4 group 7 "External confirmation". |
| `backtest/` | Python validation harness + the live forward-test machine (`forward_trader.py`, `daily_signals.py`, `mr_forward.py`, `switch_shadow.py`, `dashboard.py`, `cockpit.py`, `news_scanner.py`, study runners, reports). |
| `alpaca_stream.py` | Live IEX order-flow tape (CVD / imbalance / blocks). |
| `darkpool_orderbook.py` | Delayed Polygon dark-pool context tool. |
| `USER_GUIDE.md` / `QUICKSTART.md` | Operating the machine (dashboard, venue switch, settings). |
| `WEBULL_INTEGRATION.md` | Webull API architecture, credentials, promotion path. |
| `UNUSUAL_WHALES_INTEGRATION.md` | Plan for wiring UW options-flow/dark-pool/GEX data into the formula. |
| `OrderFlow_DarkPool_Notes.md` | Why Pine can't see the order book, and the proxy/paid-feed paths. |

## TradingView migration (one-time, after the rename)

1. Remove from your chart: every old SWING_PRO / Swing1m script AND their alerts
   (`SWING_PRO_S`, `SWING_PRO`, `SWING_PRO_v2`, `SWING_PRO_v3`, `SWING_BUY`, `SWING_SELL`).
2. Pine Editor → paste `iAPE_v4.pine` → Save → Add to chart.
3. Re-create alerts from v4's alert conditions (they're tagged `[iAPE_v4]`).
   If you use Backflow's connector outputs, re-select them in iAPE_v4 group 7
   (indicator titles changed, so the source dropdown resets).
4. Strategy Tester → Properties → set your broker's real commission + slippage.

## `legacy/` (superseded — kept for reference, don't add to charts)

- `SWING_PRO_strategy.pine` — v1 strategy, sell-only build
- `1_SWING_PRO_S_strategy.pine` — v1 all-in-one (the v2 skeleton)
- `2/3_..._indicator.pine` + `4/5_..._SIGNAL.pine` — the old 2-layer indicator/wiring
  workaround; obsolete now that one script draws its own signals
- `Swing1m_PRO(.strategy).pine` — 1m experiments; the 5m lineage superseded them
- Reversal entries + anti-chase guard live only in these legacy files (v2 deleted them
  as dead code — off in every tested config)

`../Pine-Trading-Scripts/` is the older generation of all of this and stays as an archive.

## Where the edge actually is (evidence summary)

- **Daily timeframe is the flagship** — 30y validation: PF 1.96 overall, 1,090 trades,
  all 22 symbols profitable (`backtest/reports/daily_30y_2026-07-04.md`); gap-risk
  measured and CLEAR (~0.08 PF tax). 5m intraday = running experiment (thin edge,
  PF ≈ 1.10 variant B), 1h/1m/crypto/metals all REJECTED.
- **MR-1 mean-reversion validated** as Strategy #2 (PF 1.36/1.22/1.21 by decade);
  switch-vs-parallel test says regime-SWITCHING beats running both in parallel
  (in-sample) — a pre-registered shadow audition is live.
- Full verdict ledger lives in the memory files + `backtest/reports/`.

**Status: three paper auditions are running (5m intraday, iAPE-D daily, MR-1 shadow).
Nothing trades real money until its audition passes (≥30 closed trades at/above
benchmark).** Not financial advice.
