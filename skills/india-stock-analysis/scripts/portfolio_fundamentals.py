"""Pull authoritative fundamental data via yfinance for a list of NSE tickers.

Used as the documented free fallback when no broker MCP (Groww / Zerodha Kite) is connected.
Outputs a markdown table summarizing key metrics + a JSON dump with full detail.

Usage:
    python3 portfolio_fundamentals.py --tickers RELIANCE,TCS,INFY --output report.md
    python3 portfolio_fundamentals.py --positions positions.json --output report.md
"""

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import yfinance as yf


@dataclass
class Snapshot:
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    cmp: Optional[float] = None
    currency: Optional[str] = None
    market_cap_cr: Optional[float] = None
    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    pb: Optional[float] = None
    roe_pct: Optional[float] = None
    roa_pct: Optional[float] = None
    de_ratio: Optional[float] = None
    debt_to_equity_raw: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    operating_margin_pct: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    eps_ttm: Optional[float] = None
    book_value: Optional[float] = None
    earnings_growth_pct: Optional[float] = None
    revenue_growth_pct: Optional[float] = None
    fifty_two_wk_high: Optional[float] = None
    fifty_two_wk_low: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    fifty_day_avg: Optional[float] = None
    two_hundred_day_avg: Optional[float] = None
    beta: Optional[float] = None
    held_pct_insiders: Optional[float] = None
    held_pct_institutions: Optional[float] = None
    error: Optional[str] = None


def fetch_one(ticker: str) -> Snapshot:
    yf_ticker = ticker if "." in ticker else f"{ticker}.NS"
    snap = Snapshot(ticker=ticker)
    try:
        info = yf.Ticker(yf_ticker).info
        if not info or info.get("regularMarketPrice") is None:
            snap.error = "no data"
            return snap

        snap.name = info.get("longName") or info.get("shortName")
        snap.sector = info.get("sector")
        snap.industry = info.get("industry")
        snap.cmp = info.get("regularMarketPrice") or info.get("currentPrice")
        snap.currency = info.get("currency")
        mc = info.get("marketCap")
        if mc:
            snap.market_cap_cr = round(mc / 1e7, 2)
        snap.pe_trailing = info.get("trailingPE")
        snap.pe_forward = info.get("forwardPE")
        snap.pb = info.get("priceToBook")
        roe = info.get("returnOnEquity")
        if roe is not None:
            snap.roe_pct = round(roe * 100, 2)
        roa = info.get("returnOnAssets")
        if roa is not None:
            snap.roa_pct = round(roa * 100, 2)
        snap.debt_to_equity_raw = info.get("debtToEquity")
        if snap.debt_to_equity_raw is not None:
            snap.de_ratio = round(snap.debt_to_equity_raw / 100, 2)
        pm = info.get("profitMargins")
        if pm is not None:
            snap.profit_margin_pct = round(pm * 100, 2)
        om = info.get("operatingMargins")
        if om is not None:
            snap.operating_margin_pct = round(om * 100, 2)
        dy = info.get("dividendYield")
        if dy is not None:
            snap.dividend_yield_pct = round(dy if dy > 1 else dy * 100, 2)
        snap.eps_ttm = info.get("trailingEps")
        snap.book_value = info.get("bookValue")
        eg = info.get("earningsGrowth")
        if eg is not None:
            snap.earnings_growth_pct = round(eg * 100, 2)
        rg = info.get("revenueGrowth")
        if rg is not None:
            snap.revenue_growth_pct = round(rg * 100, 2)
        snap.fifty_two_wk_high = info.get("fiftyTwoWeekHigh")
        snap.fifty_two_wk_low = info.get("fiftyTwoWeekLow")
        if snap.fifty_two_wk_high and snap.cmp:
            snap.pct_from_52w_high = round(
                (snap.cmp - snap.fifty_two_wk_high) / snap.fifty_two_wk_high * 100, 2
            )
        snap.fifty_day_avg = info.get("fiftyDayAverage")
        snap.two_hundred_day_avg = info.get("twoHundredDayAverage")
        snap.beta = info.get("beta")
        hpi = info.get("heldPercentInsiders")
        if hpi is not None:
            snap.held_pct_insiders = round(hpi * 100, 2)
        hpinst = info.get("heldPercentInstitutions")
        if hpinst is not None:
            snap.held_pct_institutions = round(hpinst * 100, 2)
    except Exception as e:
        snap.error = str(e)[:200]
    return snap


def fmt(v, places=2, suffix=""):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{round(v, places)}{suffix}"
    return f"{v}{suffix}"


def to_markdown_table(snaps: list[Snapshot], positions: dict | None = None) -> str:
    """Build a wide markdown table. If positions provided, add cost/P&L columns."""
    lines = []
    has_pos = positions is not None
    header = [
        "Ticker", "Name", "Sector", "CMP", "MktCap(Cr)", "PE", "PB",
        "ROE%", "D/E", "NetMar%", "DivYld%", "52W H/L", "%fromH",
        "RevGr%", "EarnGr%", "Beta",
    ]
    if has_pos:
        header = ["Ticker", "Qty", "Avg", "CMP", "P&L%"] + header[3:]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    for s in snaps:
        if s.error:
            row = [s.ticker] + ["ERR: " + s.error] + ["—"] * (len(header) - 2)
        else:
            base = [
                fmt(s.cmp),
                fmt(s.market_cap_cr),
                fmt(s.pe_trailing),
                fmt(s.pb),
                fmt(s.roe_pct),
                fmt(s.de_ratio),
                fmt(s.profit_margin_pct),
                fmt(s.dividend_yield_pct),
                f"{fmt(s.fifty_two_wk_high)}/{fmt(s.fifty_two_wk_low)}",
                fmt(s.pct_from_52w_high, suffix="%"),
                fmt(s.revenue_growth_pct),
                fmt(s.earnings_growth_pct),
                fmt(s.beta),
            ]
            if has_pos and s.ticker in positions:
                p = positions[s.ticker]
                avg = p["avg"]
                qty = p["qty"]
                pnl_pct = (s.cmp - avg) / avg * 100 if s.cmp else None
                row = [s.ticker, str(qty), fmt(avg), fmt(s.cmp), fmt(pnl_pct, suffix="%")] + base[1:]
            else:
                name = (s.name or "")[:22]
                sector = (s.sector or "")[:14]
                row = [s.ticker, name, sector] + base
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", help="Comma-separated NSE tickers (e.g. TCS,RELIANCE)")
    p.add_argument("--positions", help="JSON file: {ticker: {qty, avg}}")
    p.add_argument("--output", default="-", help="Markdown output path (- for stdout)")
    p.add_argument("--json", help="Optional JSON dump path for full data")
    args = p.parse_args()

    positions = None
    if args.positions:
        positions = json.loads(Path(args.positions).read_text())
        tickers = list(positions.keys())
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        p.error("--tickers or --positions required")

    print(f"Fetching {len(tickers)} tickers via yfinance...", file=sys.stderr)
    snaps = [fetch_one(t) for t in tickers]
    ok = sum(1 for s in snaps if not s.error)
    print(f"  resolved: {ok}/{len(snaps)}", file=sys.stderr)

    md = to_markdown_table(snaps, positions=positions)
    if args.output == "-":
        print(md)
    else:
        Path(args.output).write_text(md + "\n")
        print(f"Wrote markdown to {args.output}", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(json.dumps([asdict(s) for s in snaps], indent=2, default=str))
        print(f"Wrote JSON to {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
