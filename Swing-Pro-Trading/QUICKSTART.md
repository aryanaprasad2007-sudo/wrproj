# iAPE — Plain-English Quickstart

A no-jargon guide to using your trading system. If you only read one file,
read this one.

---

## What this actually is

Think of it as a **practice trading robot with a dashboard**. It watches the
market, decides when it would buy or sell based on rules that were tested on 30
years of data, and does it with **pretend money** so you can see whether the
rules actually work before risking real money. The dashboard is your window
into what it's doing — and your remote control for it.

Right now it's set to focus on **AAPL (Apple)**.

---

## Starting it up

1. Double-click **`SwingPro-Dashboard.bat`** (in the `Swing-Pro-Trading` folder).
2. A black window opens and your browser pops up with the dashboard.
3. **Leave the black window open** — closing it turns the dashboard off.

That's it. To make it feel like a real app, right-click the `.bat` →
*Send to → Desktop (create shortcut)*, and give the shortcut a nice name.

---

## What you're looking at (top to bottom)

- **AAPL spotlight** — Apple's live price, whether it's up or down today, and
  what the robot's rules currently say ("setup forming," "BUY triggered," or
  "no setup"). This is the robot's opinion on Apple, updated live.
- **Kill switch bar** — the big red button and its friends (explained below).
- **Stat tiles** — your practice account's value, how many positions are open,
  how many things happened today.
- **Bot settings** — the dials you can turn (how much to trade, etc.).
- **Real Webull account** — your *actual* money and positions, read-only. The
  robot cannot touch this; it's just so you can see it in one place.
- **Equity chart** — how the practice account has done over the last month.
- **Positions, tasks, event feed, mirror** — the detailed logs.

---

## The controls you'll actually use

**Bot settings card** — turn a dial, click **Save settings**, and it takes
effect on the next minute. The useful ones:

- **Sizing per position** — how big each trade is, as a % of the account.
- **Daily loss limit** — "if I lose $X today, stop opening new trades." A safety
  net. Leave 0 to turn it off.
- **Symbols to trade** — which stocks the robot is allowed to trade. It says
  **AAPL** now. Clear it to let the robot trade its full list again.
- **Tracks** — checkboxes to turn the fast (5-minute) or slow (daily) engine
  on or off.

**Kill switch bar:**

- **KILL — halt & flatten all** (red) — panic button. One click stops the robot,
  **sells everything**, and shuts it down. Use it if anything feels wrong.
- **Resume** — turns it back on after a kill.
- **Observer mode** — a checkbox that says "only let the robot open new trades
  while I'm watching this dashboard." Walk away or close the dashboard, and it
  stops opening new trades (but still closes existing ones safely). This is your
  "someone must be watching" rule, enforced automatically.
- **Enable desktop alerts** — click once to get a pop-up notification whenever
  the robot places a trade or hits an error, so you don't have to stare at it.

---

## Placing a trade yourself (real money)

The robot's *automatic* trading is practice-only for now. But **you** can place
a real Apple trade by hand whenever you decide to. Open a terminal in the
`backtest` folder and run:

```
py webull_trade.py --env prod --buy AAPL --qty 6 --limit 315
```

- `--buy AAPL` = buy Apple (use `--sell` to sell)
- `--qty 6` = how many shares (with ~$2,000, six shares is about your max)
- `--limit 315` = the most you'll pay per share (leave it off to buy at market)

It shows you the order and waits for you to type **SEND**. Nothing happens until
you do. The trade then shows up in your Webull app and on the dashboard.

**Selling from the dashboard (easier).** In the green "Real Webull Account" card,
each position has a **"Sell all"** button. Click it, confirm the pop-up, and it
places a market order to close that position on your real account. You confirm
before anything sends — so it's still you pulling the trigger, just with a button
instead of a command. (There's no one-click *buy* button on purpose — opening new
real-money risk stays on the confirmed command above.)

---

## The one rule to remember

**The robot trades pretend money until it proves itself.** It needs about 30
completed practice trades that beat its target before it earns the right to
trade real money automatically — and even then, only in small size with your
say-so. A few good days don't count; that's just luck. The whole point of the
practice run is to tell the difference. Placing trades *yourself* is always your
call — that rule is only about the robot acting on its own.

---

## If something looks broken

- **"auth failed (401)" on the real-money card** → close the dashboard's black
  window and relaunch it.
- **Robot seems stuck / weird numbers** → hit **KILL**, then **Resume**.
- **Not sure what it did** → read the **event feed** (bottom left); every action
  is logged there with a timestamp.

When in doubt, the KILL button is always safe. It never costs you anything to
stop and look.
