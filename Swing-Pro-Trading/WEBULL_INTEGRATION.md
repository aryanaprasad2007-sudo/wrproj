# Webull OpenAPI integration plan

**Status (2026-07-08 evening): PAPER TRADING LIVE.** Full order round-trip
verified on Webull's UAT/paper venue (place→SUBMITTED→cancel→CANCELLED), and
the bot bridge mirrored its first real order end-to-end: the daily track's
DAILY_BUY UNH — bot signal → forward_log.csv → `webull_bridge.py` → Webull
paper **FILLED** (qty clamped 23→2, see §2a cap). Everything below §0 is the
original 2026-07-06 plan, kept for context; §2a/§3 carry the live findings.

**Status (2026-07-06):** approved scope = **Trading + Market Data + Connect**
(Broker API skipped — it's platform infrastructure for firms building a
brokerage, not for an individual). Market Data (incl. L2) and Connect (read-only)
proceed at full speed; the **Trading API is built and tested on Webull's paper/
test environment first, with automated live execution gated OFF** until a
strategy clears its ≥30-trade audition. This doc is the architecture + the
credential steps only Ari can do.

---

## 0. The record, stated plainly (why the gate stays)

As of 2026-07-06 the tracked paper forward test shows **0 closed trades and
$100,000.00 equity, unchanged** across all three tracks (5m, daily SP-D, MR-1
shadow), and the walk-forward was **negative out-of-sample**. Any profitable
trades to date were **discretionary/manual**, not the validated system's record.
Real-money *automation* stays keyed to the referee (≥30 closed trades ≥ the
pre-registered benchmark), not to a winning streak — because a streak is exactly
what variance produces with or without an edge (montecarlo_2026-07-02.md).
Manual trading through the API is Ari's own call; auto-firing from strategy code
is not enabled here.

---

## 1. The four APIs (approved scope in bold)

| API | Purpose | Money risk | Decision |
|---|---|---|---|
| **Market Data API** | REST **snapshot + OHLCV bars** (verified live 2026-07-06 via `webull_data.py`). L2 **order-book depth is Advanced-tier, MQTT-streaming only — NOT REST** | read-only | **snapshot/bars DONE; depth = streaming build, entitlement-gated (see §5)** |
| **Connect API** | OAuth to authorize the app against the Webull account; read positions/balances | read-only | Build — but needs Ari's OAuth grant (separate from app-key auth) |
| **Trading API** | Create/modify/cancel **real orders** (stocks/options/futures/crypto) | ⚠️ real money | **Build + paper-test; auto-exec gated OFF** |
| Broker API | Full-stack infra for trading *platforms* (RIAs/firms) | n/a | **Skip — not for an individual** |

> **Reality check (2026-07-06):** the pip SDK is unusable on py3.12 and its
> endpoint paths are stale, so `webull_data.py` hand-rolls the (verified-identical)
> HMAC-SHA1 signing with stdlib. Working host+routes: `api.webull.com` +
> `/market-data/snapshot` and `/market-data/bars`. Every REST depth route
> (`/market-data/{depth,order-book,book,tick}`) 404s — **depth is MQTT streaming +
> the paid Advanced entitlement, a separate build.** So Webull does NOT trivially
> obviate the IBKR depth path in `L2_NASDAQ_INTEGRATION.md`; the two are now
> comparable-effort options for L2, decide once the Advanced entitlement is confirmed.

SDK (reference only — not used at runtime): `webull-openapi-python-sdk`.
Protocols: HTTP (trading, account, snapshots/bars), MQTT (streaming depth/tick),
gRPC (order-status push).
US region host = webull.com. Auth = **App Key + App Secret**, HMAC request
signing (`x-app-key`, `x-signature`, `x-timestamp` headers; secret never sent).
Test + production environments exist — we use **test/paper first**.

Docs: https://developer.webull.com/apis/docs/ · SDK: https://github.com/webull-inc/webull-openapi-python-sdk

---

## 2. Credential steps — only Ari can do these (I can't provision them here)

1. **developer.webull.com** (US) → create an app → generate **App Key + App Secret**.
2. Subscribe to the **Advanced Market Data** entitlement (the L2 add-on; paid).
3. Complete **Connect (OAuth)** authorization for the account.
4. Set env vars (I read them via the same registry-fallback as the Alpaca keys —
   **never paste secrets into chat**):
   - `WEBULL_APP_KEY`, `WEBULL_APP_SECRET`
   - (region defaults to US)
5. Tell me they're set → I live-verify each API against the **test environment**
   before anything touches production.

### 2a. RESOLVED (2026-07-08 evening): UAT credentials + venue facts

- **The shared test credentials are PUBLIC, published in the docs** (SDK/tools
  page) — three shared UAT accounts, each with its own app key/secret. Pair #1
  is installed as `WEBULL_UAT_APP_KEY/SECRET` (User env; fine to store — they
  are public by design). Its paper account: `J6HA4EBQRQFJD2J6NQH0F7M649`
  (acct# CUS1L6P4, ~$100T simulated cash). **It is a SHARED PUBLIC account** —
  other developers' orders/positions appear in it; put nothing meaningful there.
- **⚠ Key-rotation incident:** while hunting portal credentials, Ari's [Reset
  Key] rotated the PROD App Secret — the old secret started 401ing mid-session.
  Diagnosed by fingerprint (the "UAT secret" he saved authenticated on prod);
  fixed registry-to-registry, secrets never displayed. GOTCHA: long-lived
  shells keep the STALE secret in `os.environ`, which `data._env` prefers over
  the registry — after any rotation, restart the shell/app or clear the env var.
- **Venue rules measured live:** per-order notional cap **$1,000**
  (`ORDER_RISK_RULE_NOTIONAL`: $1,020 rejected / $680 accepted) — the bridge
  clamps mirror qty to fit (`MAX_MIRROR_NOTIONAL`). A dedicated (non-shared)
  test account from Webull support would lift this. The UAT gateway throws
  intermittent **504 GATEWAY_TIMEOUT** (both reads and writes) — treat as
  transient and retry; a 504'd place may or may not have landed, so check
  open-orders before re-placing (the bridge's idempotent state handles this).
- Simulated fills run after-hours: the UNH mirror (MARKET, 6pm PT) filled
  immediately.

---

## 3. Status of the build

Mirrors the existing codebase idioms (`data._env` registry auth, `cache/` CSV,
the `capture_depth.py` adapter seam):

- **`webull_data.py`** — ✅ **DONE & verified live (2026-07-06).** `snapshot()`
  and `bars()` over the stdlib HMAC-SHA1 signer. Read-only. This is a working
  equity data source (an alternative/complement to Alpaca).
- **L2 depth** — ⛔ NOT a REST drop-in. It's MQTT-streaming + the paid Advanced
  entitlement, so `WebullDepthBook` in `capture_depth.py` stays a stub; filling
  it means a streaming (MQTT) capture, gated on the entitlement being active.
  §5 has the path. IBKR (`L2_NASDAQ_INTEGRATION.md`) remains an equal-or-simpler
  depth option — pick once the entitlement is confirmed.
- **`webull_connect.py`** — read-only account/positions/balance. **Blocked:**
  the Connect API uses OAuth (authorization-code → access token), a separate
  interactive grant Ari must perform; app-key signing alone doesn't cover it.
- **`webull_trade.py`** — ✅ **BUILT & live-verified 2026-07-08** (read-only on
  prod; mutation gates dry-run-proven). The gate design shipped as planned:
  `EXECUTION_ENABLED=False` module default (place/replace/cancel DRY-RUN and
  log to `cache/webull_orders.csv`), prod mutations additionally demand a typed
  interactive confirmation — scheduled/automated contexts physically cannot
  send real orders. **Live findings that override the SDK/docs:**
  - The US gateway serves the SDK's **v1 route family** — every `/openapi/...`
    v2/v3 route from the docs 404s on BOTH hosts. Working: GET
    `/app/subscriptions/list`, `/account/{profile,balance,positions}`,
    `/trade/orders/list-{open,today}`, `/trade/order/detail`; POST
    `/trade/order/{place,replace,cancel}`.
  - v1 order schema ≠ docs' v3: `instrument_id` (NOT symbol), `qty`, `tif` in a
    `stock_order` object. `instrument_id` comes free from
    `webull_data.snapshot()` (`instrumentId` field).
  - The 2FA trade-token flow (`/openapi/auth/token/*`) 404s on this gateway —
    not required; app-key HMAC-SHA1 alone authenticates (same signer as
    `webull_data.py`, POST bodies fold in as uppercase-MD5 of compact JSON).
  - **The prod-linked account is Ari's REAL CASH account** (`ROG00LK0...`,
    acct# CVV9VVC5, ~$2,009 NLV / $129.96 cash, verified via
    `/account/balance`). There is NO paper account behind the prod keys — the
    paper venue is the UAT host, which needs its own credentials (§2a).
- **`webull_bridge.py`** — ✅ **BUILT & dry-run-proven 2026-07-08.** One-way,
  **paper-only-by-construction** mirror: tails `forward_log.csv` (read-only —
  the live Alpaca forward test is untouched) and replays each order-bearing
  event (BUY/DAILY_BUY/SELL_*/DAILY_*/TP1_PARTIAL) as a Webull paper MARKET
  order, keyed idempotently off the Alpaca order id in
  `cache/webull_bridge_state.json`. No prod mode exists in the file. Proven
  end-to-end on the real 2026-07-08 `DAILY_BUY UNH x23`: picked up, dry-logged,
  state-marked `DRY` (auto re-mirrors live once UAT creds exist). Fills will
  differ from Alpaca's (mirror-time market orders) — the performance referee
  remains the Alpaca track; the bridge proves execution plumbing
  (promotion-path step 2).

---

## 4. Promotion path (signals → real orders)

1. Data + Connect live and verified on test env. ✅ (once keys set)
2. `webull_trade` proven on **Webull paper** (place/modify/cancel round-trips).
3. A strategy clears its **paper audition** (≥30 closed, PF ≥ benchmark) in the
   forward test / cockpit.
4. *Then* its signal→order bridge is enabled — starting `WEBULL_ENV="paper"` on
   Webull, small size, human-confirmed — before any production sizing.
5. Cockpit gains a live-account column beside the paper one; `forward_review`
   scores real Webull fills the same way it scores Alpaca paper fills.

Nothing skips a step. The API access changes the *venue*, not the *bar*.

---

## 5. L2 depth via MQTT streaming (only if pursued)

Depth is not REST. To get Webull order-book depth:
1. **Confirm the Advanced Market Data entitlement is active** on the app (paid).
   Without it, streaming depth won't authorize regardless of code.
2. Obtain a **streaming grant/token** (the SDK's `/market-data/streaming/token`
   route is stale/404 — the live route must come from the current Data Streaming
   API docs).
3. Connect an **MQTT client** (`paho-mqtt`) with that token; subscribe to the
   depth/order-book sub-type for the target symbols.
4. On each book update, normalize to `(bids, asks)` = `[(price, size), …]` and
   feed the **existing** `capture_depth.book_features()` — same features, same
   `cache/depth/` storage. Only the transport is new (streaming, not the REST
   poller), so `WebullDepthBook` becomes a small MQTT loop rather than a
   `snapshot()` call.

Decision gate: this is a real streaming build + a paid entitlement. Compare
against IBKR TotalView (`L2_NASDAQ_INTEGRATION.md`, ~$0.50/mo, REST-ish
`reqMktDepth`) before committing — and either way, no depth work matters until a
*strategy that needs depth* exists and clears the discipline gate.
