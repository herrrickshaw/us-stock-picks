# US Stock Picks

Ranks the US equity universe from a daily full-market scan workbook (`us_full_scan_*.xlsx`) into two products: an
**investor shortlist** (sector-capped, plain-English thesis, equal-weight paper portfolio, HTML report) and a
**quant ranking** (multi-screen conviction scores as CSV/JSON). It consumes a workbook produced upstream by
`full_us_market_scan.py` in the `market-pipeline` repo; no market data is downloaded by this repo unless you pass `--refresh`.

> Status: active. Mechanical screen output for research and education only; **not investment advice**.
> Tracked files in `outputs/` are example runs.

New here? See [How to use this repo with AI](HOW_TO_USE_WITH_AI.md).

**Data freshness note**: the "as of" date in reports is parsed from the scan workbook's filename (falling back to
its modified time), not from the trading session actually contained in the data. If a scan file was renamed, copied
or regenerated late, check the underlying data before treating the label as authoritative.

## What it does
- Loads the newest `us_full_scan_*.xlsx` and merges its technical, fundamental, golden-cross and ML sheets per symbol.
- Applies a liquidity gate: price >= $5, median turnover >= $2M/day, liquidity tiers T1-T3 only.
- Flags ten screens: Darvas breakout, Piotroski strong, Coffee Can, Magic Formula, Bull Cartel, golden cross,
  breakout quality A/B, actionable setup, clipped ML-bullish, above EMA50.
- Computes a 0-100 conviction score (weighted screens plus quality, F-score and liquidity boosts) and assigns a sleeve:
  `CORE` (multi-screen agreement), `QUALITY`, `MOMENTUM`, `WATCH`.
- Builds a shortlist of the top N with at most 3 names per sector, and an equal-weight paper portfolio (top 10 CORE/QUALITY/MOMENTUM, notionals per $100k).

## Quick start
```bash
git clone https://github.com/herrrickshaw/us-stock-picks.git
cd us-stock-picks
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m us_stock_picks              # newest scan workbook -> outputs/
```
Needs a scan workbook (see Configuration). Open `outputs/us_investor_picks_latest.html`.

CLI options (`python -m us_stock_picks --help`; `python run_us_picks.py` is an equivalent launcher):
```bash
python -m us_stock_picks --min-turnover 5e6 --top 20 --max-per-sector 2
python -m us_stock_picks --scan path/to/us_full_scan_20260724_0043.xlsx
python -m us_stock_picks --refresh --refresh-top 500   # run the upstream scan first (slow, network)
python run_us_picks.py --open                           # macOS: open the HTML afterwards
```

## How it works
```text
full_us_market_scan.py (market-pipeline) -> us_full_scan_YYYYMMDD_HHMM.xlsx
   -> engine.load_universe   merge sheets per symbol
   -> engine._screen_flags   10 boolean screens
   -> engine.apply_filters   liquidity / price gate
   -> engine.rank_picks      conviction score, sleeve, thesis
   -> engine.diversify       sector-capped shortlist
   -> engine.build_portfolio equal-weight paper portfolio
   -> report.write_outputs   HTML + CSV + JSON
```
Screen names, labels and weights live in one table (`engine.SCREENS` and `config.WEIGHTS`); thresholds are in `config.py`.

## Repository layout
| Path | Purpose |
|---|---|
| `us_stock_picks/engine.py` | scan loading, screens, scoring, sleeves, diversification, portfolio |
| `us_stock_picks/report.py` | HTML report and CSV/JSON writers |
| `us_stock_picks/config.py` | scan directories, gates, weights, thresholds |
| `us_stock_picks/__main__.py`, `run_us_picks.py` | CLI |
| `tests/` | pytest suite on a synthetic scan workbook (`scan_fixture.py`) with golden values |
| `outputs/` | example generated reports (regenerated on each run) |
| `graphify-out/` | generated knowledge-graph cache |

## Outputs
| File | Audience |
|---|---|
| `us_investor_picks_latest.html` / `.csv` | decision-ready shortlist + portfolio |
| `us_paper_portfolio_latest.csv` | equal-weight weights and shares per $100k |
| `us_quant_ranked_latest.csv` | ranked liquid universe (top 100 rows) for research |
| `us_picks_latest.json` | summary, shortlist, portfolio and quant rows |

Each file is also written with a dated stamp (`..._YYYY-MM-DD_HH.*`).

## Data sources
| Source | What is taken | Access route | Licence / caveat |
|---|---|---|---|
| `us_full_scan_*.xlsx` from `market-pipeline` | per-symbol screens, prices, fundamentals, ML forecasts | local file; produced by `full_us_market_scan.py` (yfinance-based upstream) | upstream data terms apply; not redistributed here beyond the example outputs |

## Configuration
No environment variables or secrets. Scan workbooks are searched in `--scan-dir`, then
`~/market-pipeline/code/python_files/us_full_scan`, `~/market-pipeline/data/us_full_scan`,
`~/nse_screener_reference/scan_results` (see `config.DEFAULT_SCAN_DIRS`). `--refresh` expects
`~/market-pipeline/code/python_files/full_us_market_scan.py`.

## Testing
```bash
pip install pytest ruff
pytest -q
ruff check .
```

## Limitations and known issues
- Screens are mechanical and can fail in regime changes; liquidity filters reduce but do not eliminate execution risk. Paper-track before using capital.
- ML forecasts are a soft overlay: low-confidence or extreme (>40%) predictions are ignored.
- The "as of" label comes from the filename (see the freshness note above).
- Sector can be blank for some symbols; they are grouped under "Unknown" for the sector cap.

## Related repositories
- `market-pipeline` (upstream scan that writes the workbook).

## Licence
No licence file yet — all rights reserved.
