# india-stock-analysis — Scripts

Free-fallback data tools used by the `india-stock-analysis` skill when no broker MCP (Groww / Zerodha Kite) is connected. The skill prefers broker MCP data when available; these scripts are the documented yfinance fallback.

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
