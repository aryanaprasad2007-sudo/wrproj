# iAPE — Project Handoff / Context Document

**Prepared 2026-07-16 for an external LLM assistant (paste as system context).**
You are being briefed on **iAPE**, Ari's algorithmic trading project. Everything below is
established fact from ~6 weeks of rigorous, pre-registered testing. Do not re-derive or
contradict it without new evidence. Ari has no filesystem access wired to you — he will
paste code/files on request; use the file map below to ask for the right ones.

---

## 1. What iAPE is

- A set of trading scripts (Python backtest/live harness + TradingView Pine scripts) built
  around a momentum-confluence engine, originally called **SWING_PRO**.
- **Renamed to iAPE on 2026-07-14.** iAPE_v4.pine = pure REBRAND of SWING_PRO_v3 — the
  engine inside is still **v2.2**, all validation evidence carries over. Nothing about the
  strategy changed at v4.
- **Deliberately kept old plumbing names** (do not "fix" these): folder `Swing-Pro-Trading/`,
  Windows scheduled tasks `SwingPro_*`, env var `SWINGPRO_BROKER`, module `swing_pro.py`,
  state/log filenames. Renaming live-audition plumbing risks silent breakage.
- Owner: Ari (they/them pronouns unknown — use "Ari"). Pre-med student + retail trader.
  Machine: Windows 11, Python launcher `py`, console needs `$env:PYTHONUTF8="1"`.
  Code lives in `C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\` (backtest code
  in the `backtest\` subfolder).

## 2. The engines (what's validated, what's not)

### v2.2 momentum engine (the core — `swing_pro.py`, `config_v22()`)
7-gate long-only momentum confluence (EMA trend + slope filter + SPY market filter +
candle-color rule + momentum stack), **exits = pure initial stop + 3R target. No partial,
no breakeven, no trend-exit, no MACD-flip exit** — every protective exit measurably clips
the big winners that carry the system (exit sweep, 64 configs, H1/H2 validated: +$6,835
PF 1.30 vs v2.1's +$1,706 PF 1.08 over 2y).

**Timeframe map (validated per-TF):**
| TF | Verdict |
|---|---|
| 1m entries/stops | REJECTED (PF 0.82, noise + costs) |
| 5m | Validated but THIN (variant B: 5m decisions, 1m-resolution fills — PF 1.10, +$2,331/2y). Walk-forward on the raw 5m formula was ZERO-EDGE; only the B execution layer survived. |
| 15m | Untested |
| 1h | FAILED (H2 PF 0.90) |
| **Daily ("SWING_PRO-D" / iAPE daily flagship)** | **VALIDATED STRONG** — the landmark result |

**The daily flagship result (2026-07-04, `run_daily_30y.py`):** v2.2 engine on daily bars
(local 50-EMA regime, `use_htf_trend=False`, long-only, pure stop+3R), 22 long-history
symbols incl. era-losers GE/IBM/INTC, 1995–2026: **PF 1.47 / 2.03 / 2.45 by decade, 1.96
overall, 1,090 trades, +0.43R, ALL 22 symbols profitable.** Survived dot-com, 2008, COVID,
2022. A survivorship-control basket (JPM GS XOM CVX CAT DE BA WMT COST HD UNH DIS KO) also
passed independently (PF 2.24 full / 1.74 in H2) — the edge is the engine, not symbol
hindsight. Interpretation: the confluence stack is a DAILY system that had been deployed at
the wrong timeframe (5m) all along. Caveats: survivors-only universe, overnight
gap-through-stop risk (measured 2026-07-11: ~0.08 PF tax, CLEAR — benchmark stands).

### MR-1 mean reversion (strategy #2 — `mean_rev.py`)
Daily long-only dip-buy: close>200d SMA + RSI(3)<15 → next-open entry; exit first close>10d
SMA; 10-session time stop; 3×ATR disaster stop; portfolio-level (single cash pool, flat 10%,
max 10 concurrent, most-oversold priority). **Validated first-shot on the 30y well
(pre-registered): PF 1.36/1.22/1.21 by decade, 2,809 trades, 18/22 symbols+, 66% win.**
Adopted with a footnote: raw correlation to momentum is +0.46 (NOT anti-correlated);
partial correlation controlling for SPY = +0.27. Character: MR dies on the strongest
momentum names (NVDA −$60k in it). Currently SHADOW-only (no orders).

### Switch policy (regime switcher)
Pre-registered in-sample test (2026-07-09): SWITCHING between momentum and MR by a frozen
classifier (SPY close > rising 50d SMA → momentum, else MR) beat running both in parallel
by **+59.7% MAR** — via regime-timed drawdown avoidance, not uncorrelation. Now in a
pre-registered forward shadow (`switch_shadow.py`, from 2026-07-13); adoption gated behind
both engines' live auditions AND forward MAR > parallel×1.10 at ≥126 sessions.

### Buried ideas (do NOT resurrect without new data — all failed pre-registered tests)
- Trend gate, MACD-flip exit, 1.5× volume gate, anti-chase (ablation: dead or harmful).
- Short side — bleeds in EVERY config tested (−$10.8k/2y PF 0.65). System is long-only.
- OHLCV regime gates (regime autopsy: sign flipped out-of-sample).
- Daily-granularity flow data (DIX/GEX, FINRA short ratio) as 5m gates — hollow.
- Extension veto / pullback-only / loss cooldown — the "chasing" entries are the profitable ones.
- 1h port, MSTR (H1 PF 2.64 → H2 0.38 landmine), money-management overlays (flat 10% won on
  MAR; equal-risk is an aggression dial, not an improvement), limit entries, time stops.
- **Crypto: DECISIVE FAIL** (daily PF 0.87 regime-dependent; hourly with real 0.15%/side fees
  PF 0.67 on 1,854 trades). The engine is equity-specific. Never wire a crypto trader on it.
- Win-rate "improvements": win rate is a dial, not an edge — comfort exits cost a measured
  −$5k. Ari asks for "highest win rate" periodically; the honest answer is the MR sleeve
  (64-66% win by construction) running alongside momentum, not degrading momentum's exits.

## 3. Live infrastructure (running right now)

All paper trading. Broker adapter `broker.py`, env `SWINGPRO_BROKER=webull` since 2026-07-09:
orders go to **Webull PAPER (UAT sandbox, shared account, $2,000 simulated book via
`webull_sizing_equity=2000`)**. Alpaca is DATA feed + calendar only (paper keys in Windows
User registry; paper-api hardcoded — real money impossible from the bot). Market data for
signals: Alpaca IEX (5m RTH-filtered + daily), yfinance for research wells.

**Ten Windows scheduled tasks** (all WakeToRun, windowless via `run_hidden.vbs`, times PT):
| Task | When | What |
|---|---|---|
| SwingPro_Forward_Test | every 1 min 06:25–13:20 | `forward_trader.py --once` — trades v2.2: intraday 10 names + daily book fills/exits, reconciles vs account, STRICT shadow logging |
| SwingPro_Flow_Capture | 06:28 | per-minute CVD/imbalance → cache/flow/ (restarted 7/15 after being dead since 7/03) |
| SwingPro_Options_Snapshot | 12:45 | P/C, volume-weighted GEX proxy, ATM IV → cache/options_daily.csv (restarted 7/14 — prior data was 100% garbage: camelCase key bug) |
| SwingPro_Daily_Signals | 13:05 | `daily_signals.py` scans v2.2-D on completed daily bars, 13-name control basket; queues next-open entries |
| SwingPro_Forward_Report | 13:20 | reports/forward_test.md |
| SwingPro_Cockpit | 13:22 | `cockpit.py` → cockpit.html (all-tracks view + read-only Action Board with exact entry/stop/target levels) |
| SwingPro_Weekly_Review | Fri 13:30 | `forward_review.py` — THE REFEREE: real fills, slippage, per-track PF vs pre-registered benchmarks, Monte-Carlo variance context |
| SwingPro_MR_Shadow | 13:40 | `mr_forward.py` — MR-1 shadow (deterministic daily recompute, no orders) |
| SwingPro_Switch_Shadow | 13:45 | `switch_shadow.py` — switch-policy shadow |
| SwingPro_News_Scanner | 05:25 wkdays | `news_scanner.py` local server :8790 — single-ticker AI news read (⚠ Anthropic API key currently DEAD/401; headlines-only until Ari mints a new one) |

**Four live audition tracks** (judged only at ≥30 closed trades vs pre-registered benchmark):
| Track | Orders? | Benchmark | Status (2026-07-16) |
|---|---|---|---|
| 5m intraday v2.2 (10 names) | real paper | PF 1.30, ~4.2 tr/wk/basket | Clock restarted 7/13 (feed-starved before); FIRST TRADE 7/14: NVDA ×2 @ $210.87 |
| Daily SP-D (13-name control basket) | real paper | PF 1.72, ~0.4 tr/wk, 43.1% win | live since 7/06, 0/30 |
| MR-1 | SHADOW only | PF 1.21, ~1.8 tr/wk, 64% win | live since 7/06 |
| Switch policy | SHADOW only | MAR > parallel×1.10 @ ≥126 sessions | live since 7/13 |

**Panic thresholds (Monte Carlo, 10k shuffles):** losing streak ≤12 = normal; a 6-week
window down to −$1,030 = normal; 17.5% of 6-week windows lose even when the system works.
Don't panic-patch inside these bounds.

**Operator surfaces:** `dashboard.py` (stdlib-only local web app :8788, launcher
iAPE-Dashboard.bat) — health pill, watchlist scanner with affordability flags, positions,
bot settings (sizing_pct=22%, max positions, focus symbols, daily loss limit), KILL/Resume
buttons, read-only real-money card; `cockpit.html` — cross-track scoreboard + manual-trading
reference levels. Trading Hub artifact (claude.ai) = the manual/status board.

**Sizing reality on the $2k book:** at 22% (=$440/trade), buyable control names are roughly
KO/DIS/WMT/XOM/CVX ×2-5 and BA/AAPL/JPM/HD/UNH ×1; DE/COST/CAT/GS still unaffordable
(whole shares). This was a real bug class: at the old 10% the bot could afford NOTHING and
silently skipped a live UNH signal.

## 4. House rules (methodology — bind yourself to these)

1. **The 2-year intraday H1/H2 data well is RETIRED.** ~12 pre-registered tests was its
   limit; further mining manufactures confidence. The 30y daily well has a budget too
   (MR family: 2 of 3 runs remain).
2. **Chart eyes propose, harness disposes.** Every hypothesis gets a pre-registered test
   (bars/thresholds fixed BEFORE running) on fresh data. One-at-a-time ablation deltas do
   not compose — always A/B the combined config.
3. **Nothing trades real money until its paper audition passes** (≥30 closed trades at/above
   benchmark, per-strategy). Ari has pushed to auto-trade his REAL Webull account
   (~$2,018 cash) several times citing discretionary wins/"TradingView is accurate" — the
   line has been held every time and must continue to hold. Real-money enable is per-strategy,
   typed-confirm, human-executed. The assistant NEVER places real orders for Ari.
4. **Win rate is a dial, not an edge** (measured cost of prettier exits: −$5k).
5. **One Pine script per strategy — no forks.** Evidence lives in tooltips/headers.
6. Diversification bars are written as PARTIAL correlation controlling for market (not raw).
7. Update the validation ledger after every verdict; refresh the Trading Hub after milestones.

## 5. File map (ask Ari to paste what you need)

Root `Swing-Pro-Trading\`:
- **Pine kit (TradingView):** `iAPE_v4.pine` (v2.2 engine + Mode selector
  Validated/Strict/Comfort + dashboard + auto daily-config on D charts),
  `iAPE_MR.pine` (MR-1 port — CAVEAT: Pine is per-symbol, can't enforce the portfolio
  max-10 cap, single-chart backtests run rich), `iAPE_XRAY.pine` (gate diagnostics),
  `iAPE_Backflow.pine` (order-flow proxy, minute-based intrabars). Old versions in `legacy\`.
- **Docs:** `README.md` (rename note + file map), `USER_GUIDE.md`, `QUICKSTART.md`,
  `WEBULL_INTEGRATION.md`, `UNUSUAL_WHALES_INTEGRATION.md`, `L2_NASDAQ_INTEGRATION.md`.
- Launchers: `iAPE-Dashboard.bat`, `iAPE-NewsScanner.bat` (SwingPro-*.bat = forwarders).

`backtest\` (Python; the heart):
- **Engine:** `swing_pro.py` (signals + configs incl. `config_v22()`), `indicators.py`,
  `data.py` (Alpaca SIP/yfinance + parquet cache; `_env()` reads keys from Windows User
  registry), `mean_rev.py` (MR-1 portfolio engine), `mtf_engine.py`.
- **Live:** `forward_trader.py` (the minute-tick trader, both books, reconcile, STRICT
  shadow, `--status/--once/--flatten/--resume`), `daily_signals.py`, `broker.py` (venue
  adapter), `botconfig.py` (live-tunable settings → cache/bot_settings.json),
  `control.py` (HALT/OBSERVER flags), `forward_review.py` (weekly referee),
  `cockpit.py`, `dashboard.py`, `news_scanner.py`, `mr_forward.py`, `switch_shadow.py`.
- **Webull:** `webull_data.py` (hand-rolled HMAC-SHA1 signing — the pip SDK is unusable),
  `webull_trade.py` (gated; prod needs typed SEND on a TTY), `webull_bridge.py`,
  `webull_fills.py` (fill scorer; UAT sim prints garbage fills — >15% off ref price is nulled).
- **Data collectors:** `options_snapshot.py`, `capture_flow.py`, `capture_depth.py`,
  `free_data.py`, `uw_data.py` (Unusual Whales client, unused — no token, deferred).
- **Research runners (`run_*.py`)** with dated reports in `reports\`: ablation, walkforward,
  mtf, regime_autopsy, orthogonal, improvement, exit_sweep, tf1h, universe_scan, risk_layer,
  execution_batch, montecarlo, daily_test, daily_30y, daily_metals, mr_baseline, parity_tsla,
  switch_vs_parallel, crypto_test, gap_risk, month_backtest.
- State/logs: `forward_state.json`, `forward_log.csv` (fixed schema), `*_task.log`,
  `cache\` (parquet bars, flow, options, settings).

## 6. Known gotchas (each cost hours — do not rediscover)

- **Alpaca bar queries need explicit `start=`** or they return ~1 session regardless of
  `limit`. This silently starved the 5m track for 9 days (zero signals possible 7/02–7/11).
  Also: the engine is validated on RTH-only bars — always filter 09:30–16:00 ET.
- `run_hidden.vbs` swallows exit codes: schtasks "Last Result: 0" ≠ success. Verify via
  file mtimes and per-task logs. forward_log.csv absent = zero events, not failure.
- OneDrive can lock a shared log file → tasks sharing `>> forward_task.log` silently no-op
  (seen 7/14). If it recurs: one log file per task, or move logs out of OneDrive.
- Scheduled-task `/tr` strings must not have a trailing space before `&&` (crashed every
  tick for a morning once).
- Webull: pip SDK unusable on py3.12 (vendored deps broken + stale routes). Correct host
  `api.webull.com`, v1 routes (`/market-data/snapshot`, `/trade/order/place`…); all
  `/openapi/...` docs routes 404. Paper venue = UAT host with PUBLIC shared credentials
  (shared account — positions vanish via other devs; its balance/fills are not truth, the
  bot's own forward_log is). $1,000/order notional cap on UAT. Intermittent 504s — retry,
  and after a 504'd place, check open orders before re-placing.
- After any key rotation, long-lived shells keep the stale secret in os.environ (and
  os.environ beats registry in `_env`) — restart the process or force-refresh from registry.
- Never regex-edit files with PowerShell Set-Content (mojibake). pyarrow required for
  parquet caching. WakeToRun wakes a SLEEPING PC, not a shut-down one — Ari must sleep,
  not shut down, on market nights.
- Machine-down day (Fri 7/10 ~10:00 PT): ticks stopped, weekly review missed and was run
  manually 7/11. Expect occasional catch-up weirdness (0x800710E0 wake refusals — benign so far).

## 7. Current state & open work (as of 2026-07-16)

**Open (near-term):**
- News scanner: Anthropic API key is dead (401) — headlines-only until Ari mints a new key.
  A judge-failure bug that burned retry money was fixed 7/16.
- All four auditions accumulating; next weekly review Fri 2026-07-17 13:30 PT.
- TradingView migration of the renamed iAPE scripts pending on Ari (paste scripts, re-create
  alerts, re-select Backflow connector sources in v4 group 7).
- Watch item: the shared-log silent no-op (7/14) — split logs if it recurs.
- Dedicated (non-shared) Webull UAT account from support — still open.
- Trading Hub artifact + pitch deck not yet rebranded to iAPE.

**Gated/dormant:**
- Chat D (data/flow research) wakes ~early Sep 2026 when the options + CVD accumulators
  mature (both restarted mid-July after silent-corruption fixes).
- L2 depth (IBKR ~$0.50/mo or Webull MQTT) — gated behind a strategy that needs it.
- Unusual Whales — deferred until the system proves itself ("no paying until reliable results").
- MR-1 graduation to real paper orders — needs ≥30 shadow trades + symbol-ownership
  partition (its universe overlaps both order tracks).

**Bottom line for a new assistant:** the daily momentum flagship (v2.2-D) and MR-1 are the
validated edges; everything now runs through forward auditions with pre-registered
benchmarks. Your job is to help without breaking the discipline: no new mining of retired
wells, no un-gating real money, no strategy edits mid-audition (they invalidate it), and
every new idea becomes a pre-registered test on fresh data.
