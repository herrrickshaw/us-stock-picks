# US Stock Picks — Investor + Quant Product

Turn the existing **full US market scan** (Darvas, Piotroski, Coffee Can, Magic Formula, Bull Cartel, golden cross, breakout quality, ML overlay) into:

1. **Investor product** — sector-capped shortlist, plain-English thesis, equal-weight paper portfolio, HTML report  
2. **Quant product** — multi-screen conviction scores, full ranked CSV/JSON for research

No new market download is required if a recent `us_full_scan_*.xlsx` exists (your daily pipeline already writes these).

**Data freshness note**: the "as of" date shown in reports is parsed from the scan workbook's filename (falling back to its file-modified time if the name doesn't match), not from the trading session actually contained in the data. If a scan file gets renamed, copied, or regenerated late, double-check the underlying data before treating the label as authoritative.

---

## Quick start

```bash
cd ~/us-stock-picks
pip install -r requirements.txt

# Rank latest US scan → HTML + CSV + JSON
python -m us_stock_picks
# or
python run_us_picks.py --open
```

Open:

```text
outputs/us_investor_picks_latest.html
outputs/us_quant_ranked_latest.csv
outputs/us_picks_latest.json
```

---

## What it does

| Layer | Behaviour |
|---|---|
| **Data** | Loads newest `us_full_scan_*.xlsx` from `market-pipeline/.../us_full_scan/` |
| **Liquidity gate** | Price ≥ $5, turnover ≥ $2M/day, tiers T1–T3 only |
| **Screens** | Breakout · Piotroski strong · Coffee Can · Magic Formula · Bull Cartel · Golden cross · Quality A/B · Actionable · ML bullish (clipped) · Above EMA50 |
| **Conviction score** | Weighted multi-screen score 0–100 + quality/F-score/liquidity boosts |
| **Sleeves** | `CORE` multi-agree · `QUALITY` fundamentals · `MOMENTUM` technical · `WATCH` weaker |
| **Investor shortlist** | Top N with max 3 names per sector |
| **Paper portfolio** | Equal-weight top 10 CORE/QUALITY/MOMENTUM, notionals per $100k |

---

## CLI options

```bash
python -m us_stock_picks --help

# Custom filters
python -m us_stock_picks --min-turnover 5e6 --top 20 --max-per-sector 2

# Point at a specific scan workbook
python -m us_stock_picks --scan ~/market-pipeline/code/python_files/us_full_scan/us_full_scan_20260724_0043.xlsx

# Refresh market data first (slow; calls full_us_market_scan.py)
python -m us_stock_picks --refresh --refresh-top 500   # smoke
python -m us_stock_picks --refresh                     # full universe
```

---

## Outputs

| File | Audience |
|---|---|
| `us_investor_picks_latest.html` | Decision-ready shortlist + portfolio |
| `us_investor_picks_latest.csv` | Same shortlist tabular |
| `us_paper_portfolio_latest.csv` | Equal-weight weights / shares per $100k |
| `us_quant_ranked_latest.csv` | Full ranked liquid universe (research) |
| `us_picks_latest.json` | API-friendly payload |

---

## How this fits your stack

```text
full_us_market_scan.py  ──►  us_full_scan_YYYYMMDD.xlsx
                                      │
                                      ▼
                            us-stock-picks (this product)
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              Investor HTML     Quant CSV/JSON    Paper portfolio
```

Upstream scan lives in `market-pipeline/code/python_files/full_us_market_scan.py` and is already scheduled via the daily pipeline.

---

## Disclaimer

Mechanical screen output for research and education only. **Not investment advice.** Screens can and do fail in regime changes; liquidity filters reduce but do not eliminate execution risk. Paper-track before using capital.

---

## Dependencies

- `pandas`, `openpyxl`, `numpy`
- Existing scan workbook (or yfinance stack if you use `--refresh`)
