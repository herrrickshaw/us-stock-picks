"""Defaults for the US stock-picks product."""
from __future__ import annotations

from pathlib import Path

# Prefer the market-pipeline scan archive (daily full US workbook).
DEFAULT_SCAN_DIRS = [
    Path.home() / "market-pipeline" / "code" / "python_files" / "us_full_scan",
    Path.home() / "market-pipeline" / "data" / "us_full_scan",
    Path.home() / "nse_screener_reference" / "scan_results",
]

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

# Investor-safe liquidity / price gates (USD).
MIN_PRICE = 5.0
MIN_TURNOVER_USD = 2_000_000.0
ALLOWED_LIQUIDITY_TIERS = ("T1_MOST_LIQUID", "T2_LIQUID", "T3_MID")

# ML is noisy on microcaps; only trust moderate predictions with decent confidence.
ML_MIN_CONFIDENCE = 0.55
ML_MAX_PRED_RET_PCT = 40.0  # ignore absurd ridge forecasts

# Ranking / portfolio
TOP_INVESTOR_PICKS = 15
TOP_QUANT_ROWS = 100
MAX_PER_SECTOR = 3
EQUAL_WEIGHT_PORTFOLIO_SIZE = 10

# Conviction weights (sum ~100 when fully hit)
WEIGHTS = {
    "breakout": 18,
    "piotroski_strong": 16,
    "coffee_can": 14,
    "magic_formula": 10,
    "bull_cartel": 10,
    "golden_cross": 10,
    "quality_ab": 8,
    "actionable": 6,
    "ml_bullish": 5,
    "above_ema50": 3,
}

# Sleeve thresholds
CORE_MIN_SCORE = 48
CORE_MIN_SCREENS = 2
MOMENTUM_MIN_SCORE = 35
QUALITY_MIN_SCORE = 32
