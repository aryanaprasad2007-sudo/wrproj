"""
make_trading_hub.py — regenerates trading-hub.pdf (the one-stop system dashboard).
Rerun after major milestones:  py make_trading_hub.py
Last content update: 2026-07-02 (post-validation, forward test day 1).
"""
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

TEAL = colors.HexColor("#0d9488")
DARK = colors.HexColor("#0f172a")
SLATE = colors.HexColor("#475569")
RED = colors.HexColor("#dc2626")
GREEN = colors.HexColor("#059669")
LIGHT = colors.HexColor("#f1f5f9")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=22, textColor=DARK,
                    spaceAfter=2, alignment=0)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=9.5, textColor=SLATE,
                     spaceAfter=10)
SEC = ParagraphStyle("SEC", parent=ss["Heading2"], fontSize=13, textColor=colors.white,
                     backColor=TEAL, borderPadding=(5, 5, 3, 5), spaceBefore=14,
                     spaceAfter=6)
SECR = ParagraphStyle("SECR", parent=SEC, backColor=RED)
SECD = ParagraphStyle("SECD", parent=SEC, backColor=DARK)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9.5, leading=13,
                      textColor=DARK)
SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=8.5, textColor=SLATE)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.8, leading=11.5)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")


def T(data, widths, header=True, zebra=True):
    rows = [[Paragraph(c, CELLB if (header and i == 0) else CELL) for c in r]
            for i, r in enumerate(data)]
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1"))]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), DARK))
        for c in range(len(data[0])):
            rows[0][c].style = ParagraphStyle("h", parent=CELLB, textColor=colors.white)
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if i % 2 == (0 if header else 1):
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


story = []
W = 7.0 * inch

# ── PAGE 1 — THE SYSTEM, LIVE ─────────────────────────────────────────────────
story += [Paragraph("iAPE Trading Hub", H1),
          Paragraph(f"v2.2 · rebuilt {date.today():%B %d, %Y} · validated on 2 years of "
                    f"full-market data · parity-verified against TradingView (largest "
                    f"win matched within $1) · forward test LIVE on Alpaca paper. "
                    f"Educational use only — not financial advice.", SUB)]

story.append(Paragraph("THE SYSTEM — iAPE v2.2", SEC))
story.append(Paragraph(
    "One strategy, one script, every choice earned by out-of-sample evidence: "
    "<b>long-only</b> momentum-confluence entries on <b>5-minute</b> charts — seven gates "
    "(75-min trend slope, MACD, Impulse, RSI band, ADX, SPY alignment, green entry bar) "
    "must all agree — then <b>pure risk management</b>: structure stop under the recent "
    "swing, 3R profit target, nothing else. No partials, no breakeven creep, no early "
    "exits: testing proved every 'protective' mechanism was taxing the big winners that "
    "pay for everything. <b>Its honest personality: ~37% of trades win — the wins are "
    "~3x the losses. Patience is the strategy.</b>", BODY))
story.append(Spacer(1, 4))
story.append(T([
    ["Benchmark (pre-registered)", "Value"],
    ["Profit factor, 2-yr backtest", "1.30 ($1.30 made per $1 lost)"],
    ["Trade frequency", "~4.2 per week per 5-symbol basket"],
    ["Max drawdown, 2 yrs, flat 10% sizing", "-2.2% (highly capital-efficient)"],
    ["Judgment rule", "no verdict before 30 closed forward trades (4-6 weeks)"],
], [3.1 * inch, 3.9 * inch]))

story.append(Paragraph("LIVE RIGHT NOW — THE AUTONOMOUS MACHINE (6 tasks, all wake the PC)", SEC))
story.append(T([
    ["Task", "When (PT)", "Job"],
    ["Forward trader", "every minute, 6:25-1:20", "Paper-trades v2.2 on Alpaca ($100k, simulated): 5m decisions, 1m-resolution exits. Hardened: state reconciles against the real account every tick."],
    ["Flow capture", "6:28-1:02, streaming", "Live CVD / book imbalance / block prints, all 10 symbols, one row per minute -> building the intraday order-flow dataset money can't buy at $0."],
    ["Options snapshot", "daily 12:45", "Put/call OI + volume ratios, GEX proxy, ATM IV per ticker -> per-ticker options history, testable ~mid-August."],
    ["Daily report", "daily 1:20", "Refreshes reports/forward_test.md (equity, positions, events)."],
    ["Friday referee", "Fridays 1:30", "The report card: real fills vs benchmarks, realized slippage vs the $0.01 assumption, per-basket scores, variance context baked in."],
    ["Silent launcher", "always", "All tasks run windowless (no more cmd pop-ups)."],
], [1.25 * inch, 1.35 * inch, 4.4 * inch]))

story.append(Paragraph("THE TWO-BASKET DUEL (settled by reality, not backtests)", SEC))
story.append(T([
    ["Basket", "Symbols", "Benchmark PF", "Note"],
    ["Current", "AAPL NVDA TSLA MSFT META", "1.30", "the original Big Tech five"],
    ["Candidate", "MSTR ORCL NFLX AVGO CRWD", "1.40", "universe-scan winner (50 symbols ranked); MSTR flagged as the likely landmine - watch it fail on purpose"],
    ["Bench (v3 seeds)", "ARM MU WMT PLTR KLAC INTC", "-", "consistent in BOTH data halves; candidates for the next basket if the duel validates the method"],
], [1.0 * inch, 2.1 * inch, 1.0 * inch, 2.9 * inch]))
story.append(PageBreak())

# ── PAGE 2 — THE EVIDENCE LEDGER ─────────────────────────────────────────────
story += [Paragraph("THE EVIDENCE LEDGER", H1),
          Paragraph("Two days, ~14 pre-registered experiments, 2 years of 5m/1m full-market "
                    "data, one discipline: derive on the first year, validate untouched on the "
                    "second, adopt only what wins BOTH. The graveyard is the point — every "
                    "rejection below is why the survivor deserves trust.", SUB)]

story.append(Paragraph("SURVIVED VALIDATION (in the live system)", SEC))
story.append(T([
    ["Finding", "Evidence"],
    ["Pure stop + 3R target exits", "PF 1.08 -> 1.30; consistent in both halves (exit sweep, 64 configs)"],
    ["Long-only", "shorts lost ~$10.8k/2yr, PF 0.65, in EVERY configuration tested"],
    ["1m-resolution execution (variant B)", "best config of the MTF test: PF 1.10, 4/5 symbols, +$2.3k vs 5m fills"],
    ["Slope, SPY-alignment + candle filters", "removing any one cost $500-$1,800 (ablation)"],
    ["Flat 10% sizing", "beat equal-risk, caps and day-stops on MAR across 18 rules"],
    ["Engine parity", "Python harness matches TradingView trade-for-trade (largest win within $1)"],
], [2.55 * inch, 4.45 * inch]))

story.append(Paragraph("TESTED AND BURIED (do not resurrect without new data)", SECR))
story.append(T([
    ["Idea", "Cause of death"],
    ["Volume gate, price-vs-trend gate", "dead weight: halved trades / changed nothing (ablation)"],
    ["MACD-flip, trend-line, partial + breakeven exits", "each one clipped the 3R winners that carry the system"],
    ["1m-trigger entries (tight 1m stops)", "0/5 symbols profitable, 1,513 trades - noise + 3x cost drag"],
    ["Extension veto / anti-chase", "the 'chasing' entries ARE the profitable ones - it's a momentum system"],
    ["Pullback-only entries, loss cooldowns", "worse or no effect on both sides"],
    ["1-hour timeframe port", "PF 1.52 was all year-one; year two lost money (regime mirage)"],
    ["Regime gates (50-day SMA etc.)", "SIGN-FLIPPED out of sample: blocked the best trades of year two"],
    ["Daily dark-pool / gamma data (DIX, GEX, FINRA)", "direction held but ~1-sigma - not tradable at daily granularity"],
    ["Limit entries, time-stops", "97% fill rate means savings = missed winners; a wash both ways"],
    ["Equal-risk sizing, position caps, daily loss stop", "more return only via more risk; worse per unit of pain"],
], [2.55 * inch, 4.45 * inch]))

story.append(Paragraph("PANIC THRESHOLDS (Monte Carlo, 10,000 shuffles - read before any losing week)", SECD))
story.append(T([
    ["For a WORKING v2.2, this is NORMAL", "Threshold"],
    ["Losing streak", "up to 12 in a row"],
    ["Worst 6-week stretch", "down to -$1,030"],
    ["Chance a healthy system still loses a 6-week window", "17.5% - one in six report cards looks bad and means nothing"],
], [4.4 * inch, 2.6 * inch]))
story.append(PageBreak())

# ── PAGE 3 — TOOLKIT, FILES, ROADMAP ─────────────────────────────────────────
story += [Paragraph("Toolkit + Roadmap", H1), Spacer(1, 2)]

story.append(Paragraph("TRADINGVIEW KIT (paste from Swing-Pro-Trading/)", SEC))
story.append(T([
    ["Script", "What it does"],
    ["SWING_PRO_v2.pine (v2.2)", "THE strategy: signals + alerts + live stop/target lines + plain-English dashboard with an honest verdict row. Premium? set use_bar_magnifier=true (= validated 1m fills)."],
    ["iAPE_XRAY.pine", "Idea engine: 7 gate heat-rows, 0-7 confluence score, near-miss diamonds (6/7), live 'why no trade' table naming the exact blocker. Mine the diamonds for hypotheses."],
    ["iAPE_Backflow.pine (rev 2)", "CVD / divergences / blocks / absorption pane. Fixed: plan-safe minute intrabars (the old seconds request crashed on non-Premium). Wires into v2.2 group 7."],
], [1.9 * inch, 5.1 * inch]))
story.append(Paragraph("Watchlist: AAPL, NVDA, TSLA, MSFT, META, MSTR, ORCL, NFLX, AVGO, "
                       "CRWD, ARM, MU, WMT, PLTR, KLAC, INTC", SMALL))

story.append(Paragraph("PYTHON HARNESS (Swing-Pro-Trading/backtest/)", SEC))
story.append(T([
    ["File", "Role"],
    ["swing_pro.py / indicators.py / mtf_engine.py", "the Pine-exact engine (parity-verified) + all indicator math"],
    ["data.py / free_data.py", "Alpaca SIP loader (2yr 5m + 1m cached) - DIX/GEX + FINRA short-volume"],
    ["forward_trader.py / forward_review.py", "the live paper trader + the Friday referee"],
    ["capture_flow.py / options_snapshot.py", "the two dataset accumulators"],
    ["run_*.py (ablation, walkforward, exit sweep, universe scan, risk layer, montecarlo...)", "every experiment, rerunnable; all reports in backtest/reports/"],
], [2.9 * inch, 4.1 * inch]))

story.append(Paragraph("THE PLAN IN PLAIN ENGLISH", SEC))
story.append(T([
    ["Step", "Status"],
    ["1. Rehearse against history - keep only what survives honest validation", "DONE (v2.2 is what survived)"],
    ["2. Audition with live prices, fake money - 4-6 weeks on the Alpaca paper account, graded every Friday vs PF 1.30", "RUNNING - started July 2, 2026"],
    ["3. Real money conversation - only if step 2 passes, only small", "LOCKED until step 2 verdict"],
], [4.6 * inch, 2.4 * inch]))

story.append(Paragraph("NEXT MILESTONES", SECD))
story.append(T([
    ["When", "What"],
    ["Every Friday 1:30 PM", "one-page report card: read it, resist judging before 30 closed trades"],
    ["~Mid-August 2026", "options dataset mature -> test per-ticker P/C + GEX gates against REAL forward trades (fresh data, not the retired well)"],
    ["Flow dataset mature", "test CVD-confirmation entries the honest way"],
    ["Next build (agreed)", "Strategy #2: a mean-reversion system, anti-correlated with v2.2 - the portfolio answer to a thin single edge"],
], [1.7 * inch, 5.3 * inch]))
story.append(Spacer(1, 8))
story.append(Paragraph(
    "House rules: the 2-yr H1/H2 dataset is RETIRED (~14 tests is its limit - further mining "
    "manufactures confidence, not edge). Chart eyes generate hypotheses; only the harness "
    "convicts or acquits. Nothing trades real money until reality itself has voted. "
    "Not financial advice.", SMALL))

doc = SimpleDocTemplate("trading-hub.pdf", pagesize=letter,
                        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                        title="iAPE Trading Hub v2.2",
                        author="Ari Allred / Claude")
doc.build(story)
print("trading-hub.pdf rebuilt")
