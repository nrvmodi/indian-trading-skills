"""One-shot portfolio analysis: pull yfinance data → score → write a markdown report.

Wraps `portfolio_fundamentals.fetch_one()` with a transparent rule-based scoring
engine and verdict logic, then renders the full report (per-stock detail +
cross-portfolio observations + action plan) in one go.

Designed as the india-stock-analysis skill's offline workflow when no broker MCP
(Groww / Zerodha Kite) is connected. yfinance gives price + ratios + growth +
52W range; the script applies the skill's documented thresholds and emits
HOLD / ADD / TRIM / EXIT verdicts with reasoning.

Usage:
    python3 portfolio_report.py --positions positions.json --output report.md

positions.json format:
    {"HSCL": {"qty": 140, "avg": 412.93}, ...}
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Reuse the snapshot fetcher.
sys.path.insert(0, str(Path(__file__).parent))
from portfolio_fundamentals import Snapshot, fetch_one  # noqa: E402


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _safe(v, default=None):
    return default if v is None else v


def score_fundamentals(s: Snapshot) -> tuple[float, list[str]]:
    """Return (score 0-10, list of reasoning bullets).

    Transparent rule-based scoring. Missing metrics degrade the score slightly
    (we don't penalize as if the metric were bad).
    """
    if s.error:
        return 0.0, [f"Data error: {s.error}"]

    points = 0.0
    bullets: list[str] = []

    # Profitability (ROE) — weight 2.5
    roe = _safe(s.roe_pct)
    if roe is None:
        bullets.append("ROE: n/a (yfinance missing)")
    elif roe >= 20:
        points += 2.5; bullets.append(f"ROE {roe}% → excellent (+2.5)")
    elif roe >= 15:
        points += 2.0; bullets.append(f"ROE {roe}% → strong (+2.0)")
    elif roe >= 10:
        points += 1.2; bullets.append(f"ROE {roe}% → adequate (+1.2)")
    elif roe >= 0:
        points += 0.3; bullets.append(f"ROE {roe}% → weak (+0.3)")
    else:
        points -= 1.0; bullets.append(f"ROE {roe}% → loss-making (-1.0)")

    # Net margin — weight 1.5
    nm = _safe(s.profit_margin_pct)
    if nm is None:
        bullets.append("Net margin: n/a")
    elif nm >= 15:
        points += 1.5; bullets.append(f"Net margin {nm}% → strong (+1.5)")
    elif nm >= 8:
        points += 1.0; bullets.append(f"Net margin {nm}% → ok (+1.0)")
    elif nm >= 0:
        points += 0.3; bullets.append(f"Net margin {nm}% → thin (+0.3)")
    else:
        points -= 1.5; bullets.append(f"Net margin {nm}% → loss (-1.5)")

    # Leverage (D/E) — weight 1.5; financials get a pass on high D/E
    is_financial = (s.sector or "").lower() in {"financial services", "financials"}
    de = _safe(s.de_ratio)
    if de is None:
        bullets.append("D/E: n/a")
    elif is_financial:
        bullets.append(f"D/E {de} (financial — pass)")
        points += 0.5
    elif de <= 0.5:
        points += 1.5; bullets.append(f"D/E {de} → low leverage (+1.5)")
    elif de <= 1.0:
        points += 0.8; bullets.append(f"D/E {de} → moderate (+0.8)")
    elif de <= 2.0:
        points += 0.0; bullets.append(f"D/E {de} → elevated (0)")
    else:
        points -= 1.0; bullets.append(f"D/E {de} → high leverage (-1.0)")

    # Growth — weight 2.5 (split: rev 1.0, earnings 1.5)
    rg = _safe(s.revenue_growth_pct)
    if rg is None:
        bullets.append("Revenue growth: n/a")
    elif rg >= 20:
        points += 1.0; bullets.append(f"Rev growth {rg}% → fast (+1.0)")
    elif rg >= 10:
        points += 0.7; bullets.append(f"Rev growth {rg}% → solid (+0.7)")
    elif rg >= 0:
        points += 0.2; bullets.append(f"Rev growth {rg}% → flat (+0.2)")
    else:
        points -= 0.5; bullets.append(f"Rev growth {rg}% → declining (-0.5)")

    eg = _safe(s.earnings_growth_pct)
    if eg is None:
        bullets.append("Earnings growth: n/a")
    elif eg >= 25:
        points += 1.5; bullets.append(f"Earnings growth {eg}% → fast (+1.5)")
    elif eg >= 10:
        points += 1.0; bullets.append(f"Earnings growth {eg}% → solid (+1.0)")
    elif eg >= 0:
        points += 0.3; bullets.append(f"Earnings growth {eg}% → flat (+0.3)")
    else:
        points -= 1.0; bullets.append(f"Earnings growth {eg}% → declining (-1.0)")

    # Valuation (PE + PB) — weight 2.0
    pe = _safe(s.pe_trailing)
    pb = _safe(s.pb)
    if pe is None:
        bullets.append("PE: n/a (loss-making or missing)")
        # If loss-making, the margin check already penalized
    elif pe < 0:
        points -= 0.5; bullets.append(f"PE {pe} → negative earnings (-0.5)")
    elif pe < 20:
        points += 1.0; bullets.append(f"PE {pe} → cheap (+1.0)")
    elif pe < 35:
        points += 0.6; bullets.append(f"PE {pe} → fair (+0.6)")
    elif pe < 55:
        points += 0.0; bullets.append(f"PE {pe} → rich (0)")
    elif pe < 80:
        points -= 0.5; bullets.append(f"PE {pe} → expensive (-0.5)")
    else:
        points -= 1.0; bullets.append(f"PE {pe} → very expensive (-1.0)")

    if pb is None:
        bullets.append("PB: n/a")
    elif pb < 1.5:
        points += 1.0; bullets.append(f"PB {pb} → discount to book (+1.0)")
    elif pb < 3:
        points += 0.6; bullets.append(f"PB {pb} → fair (+0.6)")
    elif pb < 5:
        points += 0.2; bullets.append(f"PB {pb} → elevated (+0.2)")
    elif pb < 8:
        points -= 0.3; bullets.append(f"PB {pb} → expensive (-0.3)")
    else:
        points -= 0.7; bullets.append(f"PB {pb} → very expensive (-0.7)")

    # Clamp 0..10
    score = max(0.0, min(10.0, points + 5.0))  # baseline 5, can shift ±5
    return round(score, 1), bullets


# ---------------------------------------------------------------------------
# Verdict engine
# ---------------------------------------------------------------------------

def verdict(s: Snapshot, qty: int, avg: float, weight_pct: float) -> tuple[str, str, str]:
    """Return (verdict_label, headline_reason, suggested_action).

    Decision tree combines:
      - Fundamental score (from score_fundamentals)
      - Current P&L vs cost
      - Position weight in portfolio
      - Concentration & "distressed cleanup" rules
    """
    if s.error or s.cmp is None:
        return "DATA-ERR", "No yfinance data available", "Skip / verify symbol"

    pnl_pct = (s.cmp - avg) / avg * 100
    score, _ = score_fundamentals(s)
    nm = _safe(s.profit_margin_pct, default=0)

    # Distressed: loss-making AND price well below cost AND small position → EXIT
    is_distressed = (nm < 0 and pnl_pct < -40)
    is_tiny = weight_pct < 1.0
    if is_distressed and is_tiny:
        return ("EXIT",
                f"Loss-making (NM {nm}%) + P&L {pnl_pct:.0f}% + tiny {weight_pct:.1f}% weight",
                "Sell entire position. Tax-loss harvest.")

    # Distressed but bigger position — TRIM rather than full exit (avoid panic)
    if is_distressed and not is_tiny:
        return ("TRIM-HARD",
                f"Loss-making (NM {nm}%) + P&L {pnl_pct:.0f}%; position size {weight_pct:.1f}%",
                "Reduce 50%; review remaining after next quarterly results.")

    # Big winner with stretched valuation — TRIM to lock gains
    pe = _safe(s.pe_trailing, default=0)
    pb = _safe(s.pb, default=0)
    if pnl_pct > 100 and (pe > 50 or pb > 6):
        return ("TRIM",
                f"P&L +{pnl_pct:.0f}% + valuation rich (PE {pe}, PB {pb})",
                "Trim 30-40% to recover cost + lock profit. Trail-stop the rest.")

    if pnl_pct > 50 and (pe > 60 or pb > 7):
        return ("TRIM",
                f"P&L +{pnl_pct:.0f}% + very rich valuation",
                "Trim 25-30% to recover cost.")

    # Strong fundamentals (score >= 7.5) → HOLD / ADD
    if score >= 7.5:
        if pnl_pct < -10:
            return ("ADD",
                    f"Score {score}/10 fundamentals + price down {pnl_pct:.0f}% from cost",
                    "Average down — quality at a discount.")
        return ("HOLD",
                f"Score {score}/10 fundamentals; ride it",
                "Hold. Add only on 5-10% pullbacks.")

    # Good fundamentals (6.0-7.4)
    if score >= 6.0:
        if pnl_pct < -20:
            return ("HOLD",
                    f"Score {score}/10; price overshoot, fundamentals OK",
                    "Hold; no fresh capital until thesis confirmed at next results.")
        return ("HOLD",
                f"Score {score}/10 — solid but not exceptional",
                "Hold current size.")

    # Mediocre (4.0-5.9)
    if score >= 4.0:
        if pnl_pct > 20:
            return ("TRIM",
                    f"Score {score}/10 mediocre, but sitting on +{pnl_pct:.0f}%",
                    "Trim 25%. Don't fall in love with luck.")
        return ("HOLD",
                f"Score {score}/10 mediocre; small or negative P&L",
                "Hold; review at next results — stop if no improvement.")

    # Poor (<4.0)
    if is_tiny:
        return ("EXIT",
                f"Score {score}/10 poor + tiny position",
                "Sell; cleanup.")
    if pnl_pct > 0:
        return ("TRIM",
                f"Score {score}/10 poor; lucky to be in profit",
                "Trim 50%. Take the gift.")
    return ("EXIT-PARTIAL",
            f"Score {score}/10 poor + P&L {pnl_pct:.0f}%",
            "Reduce 50%, plan full exit on any bounce.")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def fmt(v, places=2, suffix=""):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{round(v, places)}{suffix}"
    return f"{v}{suffix}"


def render_report(snaps: list[Snapshot], positions: dict) -> str:
    rows = []
    total_invested = 0.0
    total_current = 0.0

    for s in snaps:
        p = positions.get(s.ticker, {})
        qty = p.get("qty", 0)
        avg = p.get("avg", 0)
        invested = qty * avg
        current = qty * (s.cmp or 0)
        total_invested += invested
        total_current += current
        rows.append({"snap": s, "qty": qty, "avg": avg, "invested": invested, "current": current})

    pnl = total_current - total_invested
    pnl_pct = pnl / total_invested * 100 if total_invested else 0

    # Compute weights then verdicts
    for r in rows:
        r["weight_pct"] = (r["invested"] / total_invested * 100) if total_invested else 0
        s = r["snap"]
        if s.error or s.cmp is None:
            r["pnl_pct"] = None
            r["score"] = 0.0
            r["score_bullets"] = ["Data error"]
            r["verdict"] = ("DATA-ERR", "No data", "Verify symbol")
        else:
            r["pnl_pct"] = (s.cmp - r["avg"]) / r["avg"] * 100
            r["score"], r["score_bullets"] = score_fundamentals(s)
            r["verdict"] = verdict(s, r["qty"], r["avg"], r["weight_pct"])

    rows.sort(key=lambda r: -r["weight_pct"])

    # --- Header ---
    out = []
    out.append("# Portfolio Analysis — yfinance-sourced\n")
    out.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out.append(f"**Holdings:** {len(rows)}")
    out.append(f"**Data source:** yfinance (Yahoo Finance) — live snapshot\n")
    out.append("## Portfolio Summary\n")
    out.append("| | Amount |")
    out.append("|---|---|")
    out.append(f"| Total invested | Rs. {total_invested:,.0f} |")
    out.append(f"| Current value | Rs. {total_current:,.0f} |")
    sign = "+" if pnl >= 0 else ""
    out.append(f"| P&L | **{sign}Rs. {pnl:,.0f} ({sign}{pnl_pct:.2f}%)** |")
    out.append("")

    # --- Verdict table ---
    out.append("## Verdict Summary\n")
    out.append("| # | Stock | Qty | Avg | CMP | P&L% | Wgt% | Score | Verdict | Action |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        s = r["snap"]
        v_lbl, _, v_action = r["verdict"]
        out.append(
            f"| {i} | {s.ticker} | {r['qty']} | {fmt(r['avg'])} | {fmt(s.cmp)} | "
            f"{fmt(r['pnl_pct'], suffix='%')} | {fmt(r['weight_pct'], places=1, suffix='%')} | "
            f"{r['score']} | **{v_lbl}** | {v_action} |"
        )
    out.append("")

    # --- Per-stock detail ---
    out.append("## Detailed Per-Stock Analysis\n")
    for r in rows:
        s = r["snap"]
        v_lbl, v_reason, v_action = r["verdict"]
        out.append(f"### {s.ticker} — {s.name or 'unknown'}")
        if s.error:
            out.append(f"_Error: {s.error}_\n")
            continue
        out.append(f"_{s.sector or ''} | {s.industry or ''}_\n")
        out.append(f"**Verdict: {v_lbl}** — {v_reason}")
        out.append(f"**Action:** {v_action}\n")
        # Position table
        out.append("| Position | Value |")
        out.append("|---|---|")
        out.append(f"| Quantity | {r['qty']} |")
        out.append(f"| Avg cost | Rs. {r['avg']:.2f} |")
        out.append(f"| CMP | Rs. {s.cmp:.2f} |")
        out.append(f"| Invested | Rs. {r['invested']:,.0f} |")
        out.append(f"| Current | Rs. {r['current']:,.0f} |")
        pnl_abs = r['current'] - r['invested']
        out.append(f"| P&L | {'+' if pnl_abs>=0 else ''}Rs. {pnl_abs:,.0f} "
                   f"({'+' if r['pnl_pct']>=0 else ''}{r['pnl_pct']:.2f}%) |")
        out.append(f"| Portfolio weight | {r['weight_pct']:.2f}% |")
        out.append("")
        # Fundamentals table
        out.append("| Fundamental | Value |")
        out.append("|---|---|")
        out.append(f"| Market cap (Cr) | {fmt(s.market_cap_cr)} |")
        out.append(f"| PE (TTM) | {fmt(s.pe_trailing)} |")
        out.append(f"| PE (forward) | {fmt(s.pe_forward)} |")
        out.append(f"| PB | {fmt(s.pb)} |")
        out.append(f"| ROE % | {fmt(s.roe_pct)} |")
        out.append(f"| ROA % | {fmt(s.roa_pct)} |")
        out.append(f"| D/E | {fmt(s.de_ratio)} |")
        out.append(f"| Net margin % | {fmt(s.profit_margin_pct)} |")
        out.append(f"| Operating margin % | {fmt(s.operating_margin_pct)} |")
        out.append(f"| Revenue growth (YoY) % | {fmt(s.revenue_growth_pct)} |")
        out.append(f"| Earnings growth (YoY) % | {fmt(s.earnings_growth_pct)} |")
        out.append(f"| Dividend yield % | {fmt(s.dividend_yield_pct)} |")
        out.append(f"| 52W high / low | Rs. {fmt(s.fifty_two_wk_high)} / Rs. {fmt(s.fifty_two_wk_low)} |")
        out.append(f"| % from 52W high | {fmt(s.pct_from_52w_high, suffix='%')} |")
        out.append(f"| 50DMA / 200DMA | Rs. {fmt(s.fifty_day_avg)} / Rs. {fmt(s.two_hundred_day_avg)} |")
        out.append(f"| Beta | {fmt(s.beta)} |")
        out.append(f"| Institutional holding % | {fmt(s.held_pct_institutions)} |")
        out.append("")
        # Score breakdown
        out.append(f"**Fundamental score: {r['score']}/10**\n")
        out.append("Score components:")
        for b in r["score_bullets"]:
            out.append(f"- {b}")
        out.append("")

    # --- Cross-portfolio observations ---
    out.append("## Cross-Portfolio Observations\n")

    # Concentration
    out.append("### Top concentrations (>10% weight)")
    big = [r for r in rows if r["weight_pct"] > 10]
    if big:
        for r in big:
            out.append(f"- **{r['snap'].ticker}** — {r['weight_pct']:.1f}% "
                       f"(Rs. {r['invested']:,.0f}); verdict: {r['verdict'][0]}")
    else:
        out.append("- Portfolio is well-diversified (no single position > 10%).")
    out.append("")

    # Sector mix
    out.append("### Sector mix")
    sectors: dict[str, float] = {}
    for r in rows:
        sec = (r["snap"].sector or "Unknown")
        sectors[sec] = sectors.get(sec, 0) + r["invested"]
    out.append("| Sector | Invested (Rs.) | % of Portfolio |")
    out.append("|---|---|---|")
    for sec, inv in sorted(sectors.items(), key=lambda x: -x[1]):
        out.append(f"| {sec} | {inv:,.0f} | {inv/total_invested*100:.1f}% |")
    out.append("")

    # Action plan
    out.append("### Recommended action plan (by priority)\n")
    exits = [r for r in rows if r["verdict"][0] == "EXIT"]
    trims = [r for r in rows if r["verdict"][0] in {"TRIM", "TRIM-HARD", "EXIT-PARTIAL"}]
    adds = [r for r in rows if r["verdict"][0] == "ADD"]

    if exits:
        out.append("**Immediate exits (cleanup):**")
        for r in exits:
            recoverable = r["current"]
            loss = r["invested"] - r["current"]
            out.append(f"- Sell **{r['snap'].ticker}** ({r['qty']} sh) → "
                       f"realize Rs. {recoverable:,.0f}, book loss Rs. {loss:,.0f}")
        out.append("")

    if trims:
        out.append("**Trim / partial exits (book gains or reduce risk):**")
        for r in trims:
            out.append(f"- **{r['snap'].ticker}** — {r['verdict'][2]}")
        out.append("")

    if adds:
        out.append("**Average down candidates (quality at a discount):**")
        for r in adds:
            out.append(f"- **{r['snap'].ticker}** — {r['verdict'][1]}")
        out.append("")

    # Disclaimer
    out.append("---\n")
    out.append("## Disclaimer\n")
    out.append("Not investment advice. Educational analysis only. yfinance data may be delayed "
               "or incomplete (especially for smallcaps); cross-check with NSE/BSE filings. Author "
               "is not SEBI-registered. Verdict logic is transparent rule-based (see "
               "`score_fundamentals` and `verdict` in `portfolio_report.py`) — adjust thresholds "
               "to your own framework. yfinance does not provide promoter pledge %, shareholding "
               "pattern, or sector-specific ratios — those need a broker MCP (Groww/Zerodha Kite) "
               "or manual lookup.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--positions", required=True, help="JSON file: {ticker: {qty, avg}}")
    p.add_argument("--output", default="report.md", help="Markdown output path")
    p.add_argument("--json", help="Optional JSON dump of raw yfinance snapshots")
    args = p.parse_args()

    positions = json.loads(Path(args.positions).read_text())
    tickers = list(positions.keys())

    print(f"Fetching {len(tickers)} tickers via yfinance...", file=sys.stderr)
    snaps = [fetch_one(t) for t in tickers]
    ok = sum(1 for s in snaps if not s.error)
    print(f"  resolved: {ok}/{len(snaps)}", file=sys.stderr)

    md = render_report(snaps, positions)
    Path(args.output).write_text(md + "\n")
    print(f"Wrote report to {args.output}", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps([asdict(s) for s in snaps], indent=2, default=str))
        print(f"Wrote JSON to {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
