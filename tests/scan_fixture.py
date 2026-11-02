"""Deterministic synthetic US scan workbook used by the tests (no real market data)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SECTORS = ["Energy", "Industrials", "Healthcare", "Technology", "Financial Services"]
TIERS = ["T1_MOST_LIQUID", "T2_LIQUID", "T3_MID", "T4_ILLIQUID", "T5_MOST_ILLIQUID"]


def build_frames(n: int = 80, seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    sym = [f"TST{i:03d}" for i in range(n)]
    tech = pd.DataFrame(
        {
            "Symbol": sym,
            "LTP": rng.uniform(2, 400, n).round(2),
            "Change%": rng.normal(0, 2, n).round(2),
            "Turnover_USD": rng.uniform(2e5, 5e7, n).round(0),
            "Liquidity_Tier": [TIERS[i % 5] for i in range(n)],
            "Above_EMA50": rng.random(n) > 0.4,
            "Quality_Score": rng.uniform(0, 100, n).round(1),
            "Quality_Grade": rng.choice(["A", "B", "C", "D"], n),
            "Actionable": rng.random(n) > 0.6,
            "Darvas_Signal": rng.choice(["BREAKOUT_BUY", "BREAKDOWN_SELL", "NEUTRAL"], n),
            "GC_Signal": rng.choice(["GOLDEN", ""], n),
            "ML_Direction": rng.choice(["BULLISH", "BEARISH"], n),
            "ML_Pred_Ret%": rng.uniform(-10, 60, n).round(1),
            "ML_Confidence": rng.uniform(0.3, 0.9, n).round(2),
        }
    )
    yn = lambda p: np.where(rng.random(n) < p, "YES", "NO")  # noqa: E731
    fund = pd.DataFrame(
        {
            "Symbol": sym[: n - 5] + ["EXTRA1", "EXTRA2", "EXTRA3", "EXTRA4", "EXTRA5"],
            "Name": [f"Test Co {i}" for i in range(n)],
            "Sector": [SECTORS[i % 5] if i % 11 else None for i in range(n)],
            "Piotroski_Score": rng.integers(0, 10, n),
            "Piotroski_Strong": yn(0.3),
            "CoffeeCan": yn(0.25),
            "MagicFormula": yn(0.25),
            "BullCartel": yn(0.2),
            "ROE_avg_%": rng.uniform(-5, 30, n).round(1),
        }
    )
    gc = pd.DataFrame({"Symbol": sym[::4]})
    return {"All_Stocks": tech, "All_Fundamentals": fund, "Golden_Crossover": gc}


def write_scan(path: Path, **kw: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path) as xw:
        for name, df in build_frames(**kw).items():
            df.to_excel(xw, sheet_name=name, index=False)
    return path
