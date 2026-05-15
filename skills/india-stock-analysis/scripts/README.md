# india-stock-analysis — Scripts

Free-fallback data tools used by the `india-stock-analysis` skill when no broker MCP (Groww / Zerodha Kite) is connected. The skill prefers broker MCP data when available; these scripts are the documented yfinance fallback.

## Two scripts

| Script | What it does |
|---|---|
| `portfolio_fundamentals.py` | Low-level: pull yfinance snapshot → markdown table (and/or JSON dump). Use when you just want a data extract. |
| `portfolio_report.py` | High-level: pull → score → verdict → full markdown report. Use when you want analysis, not just data. |

## portfolio_report.py (recommended)

One-shot: pulls yfinance data for every ticker in your positions file, scores each on a transparent rule-based framework (profitability, leverage, growth, valuation), assigns a verdict (HOLD / ADD / TRIM / TRIM-HARD / EXIT / EXIT-PARTIAL / DATA-ERR), and writes a full markdown report with per-stock detail + cross-portfolio observations (concentration, sector mix, action plan).

```bash
python3 portfolio_report.py \
  --positions positions.sample.json \
  --output portfolio_report.md \
  --json portfolio_raw.json   # optional: dump raw yfinance data
```

### Verdict logic (transparent — see source for thresholds)

| Situation | Verdict |
|---|---|
| Loss-making (NM<0) + P&L < -40% + position < 1% | **EXIT** (cleanup) |
| Loss-making (NM<0) + P&L < -40% + larger pos | **TRIM-HARD** (reduce 50%) |
| P&L > +100% + valuation rich (PE>50 or PB>6) | **TRIM** (book 30-40%) |
| P&L > +50% + very rich (PE>60 or PB>7) | **TRIM** (book 25-30%) |
| Score ≥ 7.5 + P&L < -10% | **ADD** (average down) |
| Score ≥ 7.5 + flat | **HOLD** (add on pullbacks only) |
| Score 6.0-7.4 | **HOLD** |
| Score 4.0-5.9 + big gain | **TRIM** (luck protection) |
| Score < 4.0 + tiny position | **EXIT** |
| Score < 4.0 + larger | **EXIT-PARTIAL** (50% now, rest on bounce) |

Each verdict comes with a one-line reason and a suggested action.

## portfolio_fundamentals.py

Pulls live snapshot data from Yahoo Finance for a list of NSE tickers and renders a markdown table with key fundamentals. Supports a positions JSON to layer your cost basis on top.

### Setup

```bash
pip install yfinance pandas
# or from repo root:
pip install -e .
```

### Usage

**By ticker list:**
```bash
python3 portfolio_fundamentals.py \
  --tickers RELIANCE,TCS,HSCL,HDFCBANK \
  --output snapshot.md
```

**By positions JSON (adds qty / avg / P&L columns):**
```bash
python3 portfolio_fundamentals.py \
  --positions positions.json \
  --output portfolio.md \
  --json portfolio_raw.json
```

`positions.json` format:
```json
{
  "HSCL":      {"qty": 140, "avg": 412.93},
  "TATAPOWER": {"qty": 511, "avg": 238.13}
}
```

Tickers are NSE symbols; `.NS` is appended automatically. To target BSE explicitly, pass `RELIANCE.BO`.

### Output columns

| Column | Source field | Notes |
|---|---|---|
| CMP | `regularMarketPrice` / `currentPrice` | INR |
| MktCap(Cr) | `marketCap` / 1e7 | Crores |
| PE | `trailingPE` | Trailing 12M |
| PB | `priceToBook` | — |
| ROE% | `returnOnEquity` x 100 | — |
| D/E | `debtToEquity` / 100 | Yahoo reports as raw ratio x 100 |
| NetMar% | `profitMargins` x 100 | TTM net margin |
| DivYld% | `dividendYield` | — |
| 52W H/L | `fiftyTwoWeekHigh/Low` | — |
| %fromH | (CMP - 52WH) / 52WH | Negative = below high |
| RevGr% | `revenueGrowth` x 100 | YoY |
| EarnGr% | `earningsGrowth` x 100 | YoY |
| Beta | `beta` | — |

### Network requirement

Yahoo Finance endpoints (`query1.finance.yahoo.com`, `finance.yahoo.com`) must be reachable from the host running the script. This works on a normal laptop / VPS but **does not work inside Claude Code's web sandbox**, which restricts outbound network access to a curated allowlist. To run the analysis end-to-end with live data, execute the script locally:

```bash
git clone <this-repo>
cd indian-trading-skills
pip install -e .
python3 skills/india-stock-analysis/scripts/portfolio_fundamentals.py \
  --positions my_positions.json --output report.md
```

### Limitations vs broker MCP

yfinance gives you the snapshot view (price, key ratios, growth). What it does **not** give that broker MCPs do:

- Shareholding pattern (promoter %, FII/DII, mutual fund holders, **promoter pledge %**)
- Live OI / market depth / Greeks
- Quarterly results detail with management commentary
- Indian-style ratios like sector premium, industry PE benchmark

For a comprehensive fundamental analysis (Analysis Type 2 in the skill), pair yfinance output with web search for shareholding + analyst commentary, or connect a broker MCP.
