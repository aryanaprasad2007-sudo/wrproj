---
name: iape-desk
description: Run Ari's iAPE trading desk against the Robinhood Agentic account (••••9208) — scan signals, build the ticket book, pull live quotes, and place confirmed orders. Use whenever he says "run the desk", "what's the system saying", "any signals today", "check the market", "should I buy X", "trade the agentic account", or asks to buy/sell/close anything on Robinhood. Also use for reviewing open agentic positions against their stop and target.
---

# iAPE Desk — Robinhood Agentic

The live trading loop for account **••••9208** (`788099208`, cash, agentic_allowed).
This is real money in a small, deliberately expendable book. Ari has waived the
≥30-closed-trade audition bar **for this account only** — Alpaca/Webull paper
auditions still govern everything else.

## The one rule that does not move

**Never place, cancel, or modify an order without Ari's explicit per-trade
confirmation in this chat.** Show the ticket, run `review_equity_order`, wait for
him to say go. Every time.

- No standing approval. "Yes" to one trade is not "yes" to the next.
- No scheduled or unattended execution through this account, ever. Do not put a
  desk run that places orders behind a cron, `/loop`, or a background task.
- His waiver of the audition bar is about *which evidence gates a strategy*. It
  is not a waiver of per-trade confirmation, and he has not asked for one.
- If he says "just buy whatever the system says" — confirm each ticket anyway,
  one at a time. Say so plainly once; do not re-litigate it.

`rh_desk.py` holds no broker credentials and there is no local code path from
the engine to the account. Keep it that way.

## Running a session

```bash
cd Swing-Pro-Trading/backtest && py rh_desk.py --book <cash> --held <SYMS>
```

1. **Get real state first.** `get_accounts` → confirm `788099208` is
   `agentic_allowed:true`. `get_portfolio` → `buying_power` is the book.
   `get_equity_positions` → the held list.
2. **Scan.** Pass both in: `--book 225.37 --held CVX,JPM`. Without `--held` the
   desk cannot know what the real account owns and may ticket a name he already
   holds.
3. **Read the book** — `cache/rh_desk.json`, or the page at
   `Swing-Pro-Trading/rh_desk.html` (served by the `cockpit` launch config at
   `http://localhost:8791/rh_desk.html`).
4. **Report honestly.** Most days there are zero tickets. Say that. A ~0.4
   trades/week system that fires nothing is working correctly, and "no signal"
   is the most common true answer.

## Placing a confirmed trade

Signals come from completed **daily** bars; the price has moved since. So:

1. `get_equity_quotes` for the live price.
2. `review_equity_order` — always. It returns the broker's own pre-trade alerts
   (buying power, PDT, halts). Surface them verbatim, especially any warning.
3. Show him: symbol, shares, notional, entry ref vs live price, stop, target,
   $ at risk, and anything review flagged.
4. He says go → `place_equity_order`. Then confirm what filled.

**Order-type rules on this book.** Per-position budget is ~$45, so every name is
fractional-only. Fractional orders are `type=market` + `market_hours=regular_hours`
only — no fractional limit orders, no extended-hours fractional fills. If he wants
a limit order, it has to be whole-share, which means the name must cost less than
the per-position budget. Do not quietly convert a limit request into a market
order; tell him why and let him choose.

## Exits

The engine's stop and target are **levels, not resting orders** — nothing is
sitting at the broker. A position is only protected if someone acts. When a
holding is near its stop or target, say so unprompted. Closing is a normal
confirmed sell, same protocol.

## Framing

Give him the read, then the caveat, in that order — not a wall of hedging. The
daily engine is 30y-validated (PF 1.47/2.03/2.45 by decade, 1,090 trades) and
its forward audition is separate and still open. A ticket is what the system
says, not a forecast. Do not talk him into a trade, and do not talk him out of
one he has decided on; he owns the decision, you own the accuracy of the numbers.

## Context

- Runbook and full history: memory `iape-operations`, `iape-validation`.
- The paper tracks (Alpaca/Webull) keep running their own auditions untouched by
  this account. Cross-reference them, never conflate them.
- Research: the news scanner (`iape-news`, port 8790) — check `degraded` in its
  state before quoting any AI judgment; it has run headlines-only for long
  stretches on a dead API key while still logging a clean "SCAN done".
