"""us_stock_picks.engine: screen flags, conviction score, sleeves, liquidity gates,
sector-capped selection and the equal-weight portfolio. Hand-computed against
config.WEIGHTS; the end-to-end test writes a tiny synthetic scan workbook."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from us_stock_picks import engine  # noqa: E402


def _row(**kw):
    base = {"Symbol": "AAA", "Name": "Aaa Inc", "Sector": "Tech", "LTP": 50.0,
            "Turnover_USD": 5e6, "Liquidity_Tier": "T1_MOST_LIQUID",
            "Darvas_Signal": "IN_BOX", "Piotroski_Strong": "NO", "Piotroski_Score": 0,
            "CoffeeCan": "FAIL", "MagicFormula": "FAIL", "BullCartel": "FAIL",
            "Quality_Grade": "C", "Quality_Score": 0, "Actionable": False, "Above_EMA50": False,
            "golden_cross": False}
    base.update(kw)
    return base


def _flags(*rows):
    return engine._screen_flags(pd.DataFrame(list(rows)))


def test_scan_as_of_parses_filename():
    assert engine._scan_as_of(Path("us_full_scan_20260724_0930.xlsx")) == "2026-07-24 09:30"
    assert engine._scan_as_of(Path("us_full_scan_20260724.xlsx")) == "2026-07-24 00:00"


def test_boolish():
    s = pd.Series(["YES", "pass", " true ", "1", "NO", "FAIL", None, True])
    assert engine._boolish(s).tolist() == [True, True, True, True, False, False, False, True]


def test_ml_flag_needs_confidence_and_sane_positive_forecast():
    f = _flags(
        _row(ML_Direction="BULLISH", ML_Confidence=0.6, **{"ML_Pred_Ret%": 5}),
        _row(ML_Direction="BULLISH", ML_Confidence=0.5, **{"ML_Pred_Ret%": 5}),     # low confidence
        _row(ML_Direction="BULLISH", ML_Confidence=0.9, **{"ML_Pred_Ret%": 55}),    # absurd forecast
        _row(ML_Direction="BEARISH", ML_Confidence=0.9, **{"ML_Pred_Ret%": 5}),
    )
    assert f["scr_ml"].tolist() == [True, False, False, False]


def test_conviction_score_hand_computed():
    f = _flags(_row(Darvas_Signal="BREAKOUT_BUY", Piotroski_Strong="YES", Piotroski_Score=9,
                    Quality_Grade="A", Quality_Score=50, Above_EMA50=True))
    # breakout 18 + piotroski 16 + quality_ab 8 + above_ema50 3 = 45
    # + Quality_Score 50/100*8 = 4 + F 9/9*6 = 6 + T1 tier 4  -> 59
    assert engine._conviction_score(f).iloc[0] == pytest.approx(59.0)
    assert f["screens_passed"].iloc[0] == 4


def test_conviction_score_clipped_and_illiquid_penalty():
    f = _flags(_row(Liquidity_Tier="T5_MOST_ILLIQUID"))
    assert engine._conviction_score(f).iloc[0] == 0.0          # -2 clipped at 0


@pytest.mark.parametrize("score,n,flags,sleeve", [
    (48, 2, {}, "CORE"),
    (47.9, 5, {"scr_breakout": True}, "MOMENTUM"),
    (34, 1, {"scr_gc": True}, "WATCH"),
    (32, 1, {"scr_coffee": True}, "QUALITY"),
    (25, 1, {}, "WATCH"),
    (24.9, 3, {}, "PASS"),
    (60, 0, {}, "PASS"),
])
def test_sleeve_thresholds(score, n, flags, sleeve):
    row = pd.Series({"conviction_score": score, "screens_passed": n, **flags})
    assert engine._assign_sleeve(row) == sleeve


def test_liquidity_and_breakdown_filters():
    f = _flags(
        _row(Symbol="OK", Above_EMA50=True),
        _row(Symbol="CHEAP", LTP=4.99, Above_EMA50=True),
        _row(Symbol="THIN", Turnover_USD=1e6, Above_EMA50=True),
        _row(Symbol="T4", Liquidity_Tier="T4_ILLIQUID", Above_EMA50=True),
        _row(Symbol="NOTIER", Liquidity_Tier="", Turnover_USD=3e6, Above_EMA50=True),
        _row(Symbol="NOSCREEN"),
        _row(Symbol="BRKDN", Darvas_Signal="BREAKDOWN_SELL", Above_EMA50=True),
        _row(Symbol="BRKDN_Q", Darvas_Signal="BREAKDOWN_SELL", CoffeeCan="PASS"),
    )
    kept = engine.apply_filters(f)["Symbol"].tolist()
    assert kept == ["OK", "NOTIER", "BRKDN_Q"]


def test_diversify_caps_sector_then_fills():
    df = pd.DataFrame({"Symbol": list("ABCDE"), "Sector": ["X", "X", "X", "Y", "X"]})
    out = engine.diversify(df, n=3, max_per_sector=2)
    assert out["Symbol"].tolist() == ["A", "B", "D"] and out["investor_rank"].tolist() == [1, 2, 3]
    out = engine.diversify(df, n=4, max_per_sector=1)          # only 2 sectors -> refill
    assert out["Symbol"].tolist() == ["A", "D", "B", "C"]


def test_equal_weight_portfolio():
    picks = pd.DataFrame({"Symbol": list("ABCD"), "sleeve": ["CORE", "WATCH", "QUALITY", "MOMENTUM"],
                          "LTP": [10.0, 20.0, 25.0, 50.0]})
    port = engine.build_portfolio(picks, size=10)
    assert port["Symbol"].tolist() == ["A", "C", "D"]            # WATCH excluded when others exist
    assert port["weight"].tolist() == [0.3333] * 3
    assert port["shares_per_100k"].tolist() == [3333.0, 1333.2, 666.6]


TECH_COLS = ["Symbol", "Name", "Sector", "LTP", "Turnover_USD", "Liquidity_Tier", "Darvas_Signal",
             "Quality_Grade", "Quality_Score", "Actionable", "Above_EMA50"]


def test_run_picks_end_to_end_on_synthetic_workbook(tmp_path):
    path = tmp_path / "us_full_scan_20260724_0930.xlsx"
    tech = pd.DataFrame([
        _row(Symbol="core", Darvas_Signal="BREAKOUT_BUY", Quality_Grade="A", Quality_Score=80,
             Above_EMA50=True),
        _row(Symbol="ILLQ", Liquidity_Tier="T4_ILLIQUID", Darvas_Signal="BREAKOUT_BUY"),
    ])[TECH_COLS]
    fund = pd.DataFrame([{"Symbol": "CORE", "Piotroski_Strong": "YES", "Piotroski_Score": 8,
                          "CoffeeCan": "PASS", "MagicFormula": "FAIL", "BullCartel": "FAIL"}])
    with pd.ExcelWriter(path) as xw:
        tech.to_excel(xw, sheet_name="All_Stocks", index=False)
        fund.to_excel(xw, sheet_name="All_Fundamentals", index=False)
        pd.DataFrame({"Symbol": ["CORE"]}).to_excel(xw, sheet_name="Golden_Crossover", index=False)
    res = engine.run_picks(scan_path=path)
    assert res.as_of == "2026-07-24 09:30" and res.universe_n == 2 and res.liquid_n == 1
    top = res.investor_picks.iloc[0]
    assert top["Symbol"] == "CORE" and top["sleeve"] == "CORE"
    # breakout, Piotroski, Coffee Can, golden cross, quality A, above EMA50
    assert top["screens_passed"] == 6
    # 18+16+14+10+8+3 = 69 + Quality 80 -> 6.4 + F 8/9*6 = 5.33 + T1 4 = 84.7
    assert top["conviction_score"] == pytest.approx(84.7)
