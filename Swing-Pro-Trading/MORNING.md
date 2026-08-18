# The iAPE morning — 6:30 to 8:30

One page. You should never need to remember a script name again.

---

## The 60-second version

```bash
cd "C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest" && py -3.12 iape_morning.py --book 75.37
```

Or double-click **`iAPE-Morning.bat`**.

Read the board. If there are tickets, bring them to Claude in chat. Confirm one.
Place it yourself. Done by 6:45.

---

## What each of your pieces does in this routine

Nothing here is new strategy code. Two months of work, each part with a job:

| Piece | Its job in the morning |
|---|---|
| `swing_pro.py` (config_v22) | **Primary signal.** The 30-year flagship. Momentum. |
| `mean_rev.py` (MR-1) | **Second signal.** Fires when momentum doesn't. 64–66% win rate by construction. |
| `switch_shadow.py` classifier | **Which engine today.** SPY vs a rising 50-day. Context, not an order. |
| `universe_scan.py`'s 99 names | **The watchlist.** Validated out-of-sample, PF 2.45, t=13.26. |
| `rh_desk.py` | **Sizing + tickets.** Fractional shares against the real book. |
| `iAPE_v4.pine` / `iAPE_MR.pine` | **Your eyes.** Confirm the setup on the chart before you buy. |
| `watchdog.ps1` logic | **Is the rig alive.** Folded into the board's first line. |
| `news_scanner.py` | **Veto check.** Needs a fresh API key — currently headline-only. |
| `cockpit.py` / `forward_review.py` | **The referee.** Friday, not morning. Is it working? |
| `iape_morning.py` | **The front door.** Runs all of the above in order. |

---

## The routine

### 6:25 — run the board

The board answers five things, in this order:

1. **Is the rig alive?** If it says `RIG DARK`, the scheduled tasks aren't
   running. The live scan below it is still true, but nothing was queued
   overnight and no open position had its stop checked. **A dark rig and a
   quiet market look identical if you don't check** — that's why it's line one.
2. **Which engine does today favour?** Momentum or mean-reversion.
3. **What fired?** Tickets, ranked, with the regime's preferred engine first.
4. **What does it cost and make?** Sized against your actual book, in dollars.
5. **What do I confirm on the chart?** Which Pine script to pull up.

### 6:30–6:40 — confirm on TradingView

For each ticket, load the named script on that symbol's **daily** chart.

You're checking that the chart agrees with the scan. It should — the Python
engine was proven byte-parity with TradingView on 2026-07-02 (TSLA, largest
win matched within **$1**, largest loss within $5). If the chart and the board
*disagree*, that's information: stop and figure out why before trading it.

> Extended hours **off**, same dividend-adjustment setting on every chart, or
> the comparison isn't clean.

### 6:40 — bring it to Claude

Paste the ticket, or just say "run the desk." I will:

- pull the **live** quote (the board's entry is the last *close*, so it's stale
  by one session — the open will differ)
- run `review_equity_order` for the broker's own pre-trade check
- show you the final ticket: shares, dollars, stop, target, exit rule

You say go. **You place it.** I don't place orders — not a technical limit,
a line I hold.

### The stop is not at the broker

Fractional orders are **market orders, regular hours only**. Robinhood won't
hold a fractional stop. So the stop on your ticket is a *level you have to act
on*, not an order sitting somewhere. If you're not going to watch it, size
accordingly or don't take it.

---

## What "working" looks like

- **Most mornings have no ticket.** This engine fires roughly every other week
  per name. A wide universe fixes the frequency, not the per-name rate. An
  empty board is the system working.
- **Losing streaks of 12 are normal.** Your own Monte Carlo, 10,000 shuffles.
  A streak is not evidence it's broken. It's also exactly when people quit a
  system that's fine.
- **17.5% of six-week windows lose** even when the system works. Plan for it
  so it doesn't surprise you into changing things.
- **Judge on Friday, not daily.** `py -3.12 cockpit.py` — win rate, PF,
  expectancy vs the pre-registered benchmark.

---

## When something's wrong

```bash
cd "C:\Users\aware\OneDrive\Desktop\wrproj\Swing-Pro-Trading\backtest" && .\watchdog.cmd
```

**Never use bare `py`.** It resolves to a 3.14 install with none of the
packages — that's what silently killed the machine for 8 days in August. Always
`py -3.12`, always.

The rig only wakes from **sleep**, not from shutdown. On a market night, sleep
the PC — don't shut it down.

---

## The honest part

At a $75 book and 20% sizing, a position is about $15 and a good momentum
ticket has an expected value around **55 cents**. A mean-reversion ticket is
about **5 cents**. Those are your own measured numbers, printed on every
ticket so you never have to wonder.

Returns are a percentage of capital. The system isn't the constraint — the
constraint is that it's compounding $75. That's worth knowing every single
morning, which is why the board prints it rather than hiding it.
