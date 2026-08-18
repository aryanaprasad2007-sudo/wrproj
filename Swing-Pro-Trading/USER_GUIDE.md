# iAPE — User Guide

*How to set up and operate the trading system, written for a brand-new user
(or you, on a new machine). Updated 2026-07-08.*

---

## 1. What this is (the 30-second version)

iAPE is an evidence-first paper-trading lab. It runs **three strategy
tracks simultaneously** against a $100k Alpaca **paper** account and keeps
score with pre-registered benchmarks:

| Track | What | Orders? | Benchmark |
|---|---|---|---|
| 5m intraday (v2.2) | momentum, long-only, 10 symbols in 2 baskets | real paper orders | PF 1.30 |
| Daily SP-D | same engine on daily bars, 13-symbol control basket | real paper orders | PF 1.72 |
| MR-1 | mean-reversion (RSI(3) dip-buys above SMA200) | shadow only (logged, not sent) | PF 1.21 |

**The prime directive: nothing trades real money until it survives a ≥30-trade
paper audition beating its benchmark.** Everything below exists to run that
audition honestly while you sleep.

A Webull **paper** mirror (venue #2) replays the bot's orders onto Webull's
test environment to prove execution plumbing there — Alpaca remains the
scorekeeper.

---

## 1a. Running it as an app (locally, on your PC)

The dashboard IS the app. Two ways to launch it:

- **Double-click `SwingPro-Dashboard.bat`** (in the `Swing-Pro-Trading` folder).
  A console window opens, the local server starts on `127.0.0.1:8788`, and your
  browser opens to the dashboard. Close the window to stop it. Right-click the
  .bat → *Send to → Desktop (create shortcut)*, then rename it "iAPE" and
  pick an icon if you want it to feel like a real app.
- **Or from a terminal:** `cd Swing-Pro-Trading\backtest` then `py dashboard.py`.

**Start it automatically at login (optional):** press `Win+R`, type
`shell:startup`, Enter, and drop a shortcut to `SwingPro-Dashboard.bat` in that
folder. Now the dashboard is always running when you sign in.

Everything runs **locally** — the server binds to `127.0.0.1` (your machine
only) and nothing is exposed to the internet. The bot's scheduled tasks run
independently of the dashboard; the dashboard is your window into them and your
control panel (kill switch, etc.). It shows your **real Webull account**
(read-only) at the top — see §2 for the one requirement.

> **Real-money panel shows "auth failed (401)"?** Just close the dashboard
> window and relaunch it. Both the `.bat` and `py dashboard.py` now read the
> Webull keys straight from the Windows registry at startup, so a stale login
> session (e.g. after an API-key rotation) can no longer cause this. If it
> somehow persists, sign out of Windows and back in to refresh the session
> environment permanently.

## 2. One-time setup (fresh machine)

### 2.1 Prerequisites
- Windows with Python 3.12+ (`py` launcher). Console: set `$env:PYTHONUTF8="1"`.
- Packages: `py -m pip install numpy pandas yfinance pyarrow`
  (pyarrow is required for the parquet caches; the repo-root requirements.txt
  belongs to a different project — ignore it).
- The `Swing-Pro-Trading/` folder. All commands below run from
  `Swing-Pro-Trading\backtest\`.

### 2.2 API keys (Windows *User* environment variables)
Set via `setx NAME "value"` or System Properties → Environment Variables.
`data._env()` reads os.environ first, then the User registry — so **after
changing any key, restart your shell** (a stale copy in a long-lived shell
shadows the registry).

| Variable | What | Where to get it |
|---|---|---|
| `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` | Alpaca **paper** keys | app.alpaca.markets → Paper account → API keys |
| `WEBULL_APP_KEY` / `WEBULL_APP_SECRET` | Webull OpenAPI (prod: market data + read-only account) | developer.webull.com → your app. ⚠ [Reset Key] rotates the secret and breaks the old one instantly |
| `WEBULL_UAT_APP_KEY` / `WEBULL_UAT_APP_SECRET` | Webull **paper** venue | public shared test credentials, published on the docs' SDK page |

Safety facts: the Alpaca URL is hardcoded to `paper-api.alpaca.markets`
(real money impossible on that side), and `webull_trade.py` dry-runs all
order calls unless explicitly told otherwise, with prod requiring a typed
interactive confirmation.

### 2.3 Scheduled tasks (the machine does the work)
Eight Windows scheduled tasks, all **WakeToRun** and windowless (via
`run_hidden.vbs`). Times are **Pacific**. Recreate on a new machine with
`schtasks /create` or from exported XML; verify with:

```powershell
schtasks /query /fo csv | ConvertFrom-Csv | ? TaskName -like "*SwingPro*"
```

| Task | When (PT) | What it runs |
|---|---|---|
| SwingPro_Forward_Test | every 1 min, 06:25–13:20 | `forward_trader.py --once` — the bot tick |
| SwingPro_Flow_Capture | 06:28 (self-exits 13:02) | per-minute CVD/imbalance → `cache/flow/` |
| SwingPro_Options_Snapshot | 12:45 | P/C, GEX proxy, ATM IV → `cache/options_daily.csv` |
| SwingPro_Daily_Signals | 13:05 | daily-track scan; queues next-open entries |
| SwingPro_Forward_Report | 13:20 | writes `reports/forward_test.md` |
| SwingPro_Cockpit | 13:22 | regenerates `cockpit.html` |
| SwingPro_Weekly_Review | Fri 13:30 | `forward_review.py` — the referee |
| SwingPro_MR_Shadow | 13:40 | MR-1 shadow recompute |

**Power rule: the machine must be ON or ASLEEP by 06:25 PT.** WakeToRun wakes
it from sleep — not from shutdown.

Pause everything: `schtasks /change /tn SwingPro_Forward_Test /disable`
(same per task; `/enable` to resume).

### 2.4 First-run verification
```powershell
$env:PYTHONUTF8="1"
cd Swing-Pro-Trading\backtest
py forward_trader.py --status     # account + positions from Alpaca paper
py webull_data.py                 # Webull market-data auth check
py webull_trade.py --env paper    # Webull paper venue auth check
py cockpit.py --open              # build + open the dashboard
```
All four green → the system is operational.

---

## 3. Operating it: your actual job

**The control dashboard (added 2026-07-08) is the front door:**
```powershell
py dashboard.py          # serves http://127.0.0.1:8788 and opens the browser
```
One page, auto-refreshing every 30s: equity + last-month curve, open positions
and the daily queue, the event feed (color-classed), all 8 scheduled tasks with
**Pause/Resume buttons**, and the Webull paper mirror state — plus one-click
**Mirror to Webull / Refresh cockpit / Run bot tick** actions and a link to the
full cockpit. Localhost-only by design; it cannot place real-money orders (the
actions it exposes are all paper-side by construction).

**Trading venue (SWINGPRO_BROKER): WEBULL PAPER since 2026-07-09** (cut over
live mid-session; Alpaca is retired as a broker and stays as the market-data
feed only — bars/signals are unchanged). The Alpaca book was flattened at the
switch (`VENUE_SWITCH` event in the log). Webull-mode facts: sizing uses a
simulated `WEBULL_PAPER_EQUITY` (default $10,000, which makes 10% positions fit
the shared venue's $1,000/order cap); the shared UAT account disables position
adoption — other developers' holdings are logged `RECONCILE_FOREIGN` (once per
day) and never adopted, and positions can *vanish* if another developer sells
them (reconcile drops them from state; the trade simply doesn't score). A
**dedicated test account from Webull support** removes the cap, the foreign
noise, and the vanishing-position problem — get one before treating audition
numbers as bankable. `setx SWINGPRO_BROKER alpaca` switches back;
`webull_bridge.py` self-disables in Webull mode (it would double-order).

**AAPL focus (set 2026-07-09).** The bot is focused on **AAPL only**, and AAPL
is now traded by the **daily flagship engine** (the 30-year-validated one, with
good data). Each afternoon after the close, the daily scanner checks AAPL along
with its control basket; when AAPL's daily signal fires, it queues a buy for the
next morning's open and manages the stop + target automatically. The dashboard's
**AAPL spotlight** (top) shows the live price and exactly what that daily engine
sees right now — "setup forming," "BUY triggered," or "no setup," plus trend and
market-filter state. To trade more names, edit **Symbols to trade** in the Bot
settings card (comma-separated; blank = the full validated baskets); each focus
symbol you add is scanned by the daily engine and kept off the intraday track so
the two never fight over the same position. (The fast 5-minute engine stays idle
on AAPL — the free intraday feed is too shallow for it — which is why AAPL runs
on the daily flagship instead.)

**Bot settings panel (added 2026-07-09, on the dashboard) — how much it trades:**
A "Bot settings" card lets you set, live (takes effect on the next minute tick,
no restart):
- **Sizing per position (% of equity)** — default 10%. This is the main "how
  much" dial.
- **Max concurrent positions** — total exposure cap across both books.
- **Max $ per order** — a hard notional cap per trade (0 = off).
- **Daily loss limit $** — once the day is down this much, new entries pause
  automatically for the rest of the session (exits keep running); resets the
  next day. 0 = off.
- **Track toggles** — turn the Intraday 5m or Daily SP-D tracks on/off. (The MR
  shadow is its own scheduled task — toggle it in the task list.)
- **Webull sizing equity** — the simulated capital base used for sizing in
  Webull paper mode.

All values are clamped server-side, so a fat-fingered number can't feed the bot
something dangerous. Settings persist in `cache/bot_settings.json`.

What you **cannot** change here, on purpose: the validated strategy internals
(entry gates, RSI/ADX thresholds, the pure-stop+3R exits, the baskets). They're
shown read-only under "Validated strategy internals (locked)" — editing them
live would invalidate the ≥30-trade audition you're scoring. A new strategy
variant earns its place through a fresh backtest + audition, not a live slider.

**Supervised-auto controls (added 2026-07-09, on the dashboard):**
- **KILL switch** (red button) — one click: halts new entries, market-sells
  **every** open position on the active venue, and disables the tick task.
  Reversible with **Resume** (clears the halt, re-enables the task; it does not
  re-open what it closed). Verified end-to-end.
- **Observer mode** (checkbox) — the dead-man switch. When on, the bot only
  opens **new** positions while the dashboard has polled within the last 10
  minutes; if you close the dashboard or walk away, it manages exits only and
  logs `NEW_ENTRIES_BLOCKED`. This is the "someone must be watching" rule
  enforced in code, not by trust. (Exits are *never* gated — a halt or an idle
  observer can never strand an open position.)
- **Desktop alerts** ("Enable desktop alerts" button) — browser notifications
  fire on every order the bot places and every error (`TICK_ERROR`,
  `RECONCILE_ERROR`, …), so "observing" doesn't mean staring. A red/amber
  banner also shows the latest error or the halt state at the top of the page.

Under the hood these are flag files in `cache/` (`HALT`, `OBSERVER`,
`dashboard_heartbeat`) that both the dashboard and each bot tick read, so a
fresh scheduled-task process always agrees with what you set in the UI.
CLI equivalents: `py forward_trader.py --flatten` (kill) / `--resume`.

**Mornings: nothing.** The tick task trades 06:25–13:20 PT unattended (unless
Observer mode is on, in which case keep the dashboard open while it trades).

### Placing a manual (discretionary) trade yourself

The bot's automated trading stays gated behind the audition. But placing a
trade *by hand* is your call — that's separate from strategy code auto-firing.
The command (run it in your own terminal; **prod = real money** and forces you
to type `SEND` to confirm — nothing automated can reach this):

```powershell
cd Swing-Pro-Trading\backtest
py webull_trade.py --env prod --buy AAPL --qty 6 --limit 315
#   ^ real account   ^ symbol    ^ shares  ^ limit price (omit for MARKET)
```

It prints the order, you type `SEND`, and it goes to your real Webull account.
Use `--sell` to exit. Leave off `--env prod` (or use `--env paper`) to rehearse
on the simulated account first. Sizing reality: with ~$2,018 buying power, ~6
shares of AAPL (~$314) is your ceiling on the real account.

**After close (~13:25 PT), 2 minutes:** open `cockpit.html` (regenerates
itself at 13:22, or `py cockpit.py --open` on demand). One page: all three
tracks vs their benchmarks — win rate, PF, expectancy, trades, net — plus live
equity and a feed-health line showing today's error counts.

**Friday (~13:35 PT), 10 minutes:** read `reports/forward_test.md` and the
weekly review output — real fills by order id, slippage audit, per-basket PF
vs benchmark, daily-track and shadow sections, Monte-Carlo variance context.
This is the referee. You read it; you don't tweak the strategy midweek
(chart eyes propose, harness disposes — new ideas become pre-registered tests,
not live edits).

**Webull paper mirror (manual for now):**
```powershell
py webull_bridge.py --once      # mirror any new bot orders to Webull paper
py webull_bridge.py --status    # what's been mirrored
```
Notes: paper-only by construction; idempotent (safe to run repeatedly);
qty-clamped to the shared venue's $1,000/order cap; occasional 504s from the
test gateway are transient — rerun.

---

## 4. When something looks wrong

**Quick health check:**
```powershell
py forward_trader.py --status
schtasks /query /tn SwingPro_Forward_Test /fo list   # Result 0=ok, 267011=not yet run today
```
- `forward_state.json` mtime = last good tick. `forward_task.log` /
  `daily_task.log` / `cockpit_task.log` = per-task health.
- **"Last Result: 0" does NOT prove success** — `run_hidden.vbs` swallows exit
  codes. Trust file mtimes and the logs.
- `forward_log.csv` missing = zero events so far, not a failure.

**Known-benign:** isolated SSL/connection `TICK_ERROR`s at wake-from-sleep
(each minute is a fresh launch). A *burst* of them = network problem —
investigate.

**Panic thresholds (pre-registered, from Monte Carlo):** losing streak ≤12 is
normal; a 6-week window down to −$1,030 is normal; 17.5% of windows lose even
when the edge is healthy. Below/beyond those → escalate, don't improvise.

---

## 5. How a strategy earns real money

1. Runs as a paper/shadow track with a pre-registered benchmark.
2. Referee scores it weekly; **judged only at ≥30 closed trades**.
3. Passes (PF ≥ benchmark) → its signal→order bridge may be enabled on
   **Webull paper** first, then small real size with human confirmation.
4. Fails → buried in the validation ledger; the well budget prevents endless
   re-mining.

No step is skippable. A winning streak is what variance produces with or
without an edge — the referee, not the streak, decides.

---

## 6. File map (where things live)

| Path | What |
|---|---|
| `backtest/forward_trader.py` | the bot: ticks, orders, exits, reconcile |
| `backtest/daily_signals.py` | daily-track scanner (queues entries) |
| `backtest/forward_review.py` | Friday referee |
| `backtest/cockpit.py` → `cockpit.html` | the dashboard |
| `backtest/forward_state.json` / `forward_log.csv` | live state / event log |
| `backtest/reports/` | forward_test.md, mr_forward.md, weekly outputs |
| `backtest/cache/` | flow, options, depth, webull order log + bridge state |
| `backtest/webull_{data,trade,bridge}.py` | Webull: data / gated trading / paper mirror |
| `WEBULL_INTEGRATION.md`, `L2_NASDAQ_INTEGRATION.md` | integration docs |
| `*.pine` | TradingView kit (iAPE_v4, MR, XRAY, OrderFlow) |
| `trading-hub.pdf` (repo root) | printable overview (`make_trading_hub.py`) |
