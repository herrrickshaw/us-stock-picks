import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from us_stock_picks import config as cfg
from us_stock_picks import engine as eng


# ---------- find_latest_scan / as_of ----------
def _touch(p: Path, mtime: float):
    p.write_bytes(b"x")
    os.utime(p, (mtime, mtime))
    return p


def test_find_latest_scan_newest_mtime(tmp_path):
    old = _touch(tmp_path / "us_full_scan_20250101.xlsx", 1000)
    new = _touch(tmp_path / "us_full_scan_20240101.xlsx", 2000)
    assert eng.find_latest_scan(tmp_path) == new
    assert old != new


def test_find_latest_scan_accepts_latest_alias(tmp_path):
    _touch(tmp_path / "us_full_scan_20250101.xlsx", 1000)
    alias = _touch(tmp_path / "us_full_scan_latest.xlsx", 3000)
    assert eng.find_latest_scan(tmp_path) == alias


def test_find_latest_scan_default_dirs_and_missing_dirs(tmp_path, monkeypatch):
    d = tmp_path / "def"
    d.mkdir()
    f = _touch(d / "us_full_scan_1.xlsx", 5)
    monkeypatch.setattr(cfg, "DEFAULT_SCAN_DIRS", [tmp_path / "nope", d])
    assert eng.find_latest_scan(tmp_path / "also-missing") == f


def test_find_latest_scan_raises_with_searched_dirs(tmp_path):
    with pytest.raises(FileNotFoundError) as e:
        eng.find_latest_scan(tmp_path, pattern="zzz_*.xlsx")
    assert "'zzz_*.xlsx'" in str(e.value) and str(tmp_path) in str(e.value)


def test_find_latest_scan_custom_pattern(tmp_path):
    f = _touch(tmp_path / "other_1.xlsx", 1)
    assert eng.find_latest_scan(tmp_path, pattern="other_*.xlsx") == f


@pytest.mark.parametrize(
    "name,expected",
    [
        ("us_full_scan_20260102_0930.xlsx", "2026-01-02 09:30"),
        ("us_full_scan_20260102T0930.xlsx", "2026-01-02 09:30"),
        ("us_full_scan_202601020930.xlsx", "2026-01-02 09:30"),
        ("us_full_scan_20260102.xlsx", "2026-01-02 00:00"),
    ],
)
def test_scan_as_of_from_name(tmp_path, name, expected):
    p = tmp_path / name
    p.write_bytes(b"")
    assert eng._scan_as_of(p) == expected


def test_scan_as_of_falls_back_to_mtime(tmp_path):
    p = tmp_path / "scan.xlsx"
    p.write_bytes(b"")
    ts = time.mktime((2025, 3, 4, 12, 0, 0, 0, 0, -1))
    os.utime(p, (ts, ts))
    assert eng._scan_as_of(p) == "2025-03-04"


# ---------- helpers ----------
def test_boolish_default_and_custom():
    s = pd.Series([" yes ", "Pass", "true", "1", "y", "no", "0", "nan"])
    assert eng._boolish(s).tolist() == [True, True, True, True, True, False, False, False]
    assert eng._boolish(pd.Series(["a", "b"]), {"A"}).tolist() == [True, False]
    assert eng._boolish(None).empty


def test_num_coerces():
    out = eng._num(pd.Series(["1.5", "x", None]))
    assert out.iloc[0] == 1.5 and out.iloc[1:].isna().all()


def _write_xlsx(path, sheets):
    with pd.ExcelWriter(path) as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
    return path


def test_read_sheet_missing_and_empty(tmp_path):
    p = _write_xlsx(tmp_path / "a.xlsx", {"S": pd.DataFrame({"a": [1]}), "E": pd.DataFrame({"a": []})})
    assert eng._read_sheet(p, "S")["a"].tolist() == [1]
    assert eng._read_sheet(p, "missing").empty
    assert eng._read_sheet(p, "E").empty


def test_read_sheet_zero_columns(monkeypatch, tmp_path):
    monkeypatch.setattr(eng.pd, "read_excel", lambda *a, **k: pd.DataFrame(index=[0, 1]))
    assert eng._read_sheet(tmp_path / "x.xlsx", "S").empty
    monkeypatch.setattr(eng.pd, "read_excel", lambda *a, **k: None)
    assert eng._read_sheet(tmp_path / "x.xlsx", "S").empty


# ---------- load_universe ----------
def _scan(tmp_path, tech=None, fund=None, gc=None, ml=None, name="us_full_scan_20260102_0930.xlsx"):
    sheets = {}
    for n, d in (("All_Stocks", tech), ("All_Fundamentals", fund), ("Golden_Crossover", gc), ("ML_Bullish", ml)):
        if d is not None:
            sheets[n] = d
    return _write_xlsx(tmp_path / name, sheets)


def test_load_universe_merge_dedup_and_coalesce(tmp_path):
    tech = pd.DataFrame({
        "Symbol": [" aapl ", "AAPL", "msft", "tsla"],
        "Name": ["Apple", "Apple dup", None, "Tesla"],
        "LTP": [100.0, 1.0, 200.0, 300.0],
    })
    fund = pd.DataFrame({
        "Symbol": ["msft", "nvda", "msft"],
        "Name": ["Microsoft", "Nvidia", "dup"],
        "Piotroski_Score": [8, 9, 1],
    })
    gc = pd.DataFrame({"Symbol": ["tsla "]})
    p = _scan(tmp_path, tech, fund, gc)
    u = eng.load_universe(p).set_index("Symbol")
    assert set(u.index) == {"AAPL", "MSFT", "TSLA", "NVDA"}
    assert u.loc["AAPL", "LTP"] == 100.0               # first duplicate kept
    assert u.loc["MSFT", "Name"] == "Microsoft"         # tech value missing -> filled from fundamentals
    assert u.loc["AAPL", "Name"] == "Apple"             # tech value wins when present
    assert u.loc["MSFT", "Piotroski_Score"] == 8        # first fund row kept
    assert u["golden_cross"].to_dict() == {"AAPL": False, "MSFT": False, "TSLA": True, "NVDA": False}
    assert (u["as_of"] == "2026-01-02 09:30").all() and (u["scan_path"] == str(p)).all()
    assert not any(c.endswith("_fund") for c in u.columns)


def test_load_universe_ml_sheet_merged_only_when_missing(tmp_path):
    tech = pd.DataFrame({"Symbol": ["A", "B"], "LTP": [1.0, 2.0]})
    ml = pd.DataFrame({"Symbol": ["a"], "ML_Direction": ["BULLISH"], "ML_Confidence": [0.9]})
    u = eng.load_universe(_scan(tmp_path, tech, ml=ml)).set_index("Symbol")
    assert u.loc["A", "ML_Direction"] == "BULLISH" and pd.isna(u.loc["B", "ML_Direction"])
    # when the base frame already has ML_Direction the ML sheet is ignored
    tech2 = tech.assign(ML_Direction=["BEARISH", "BEARISH"])
    u2 = eng.load_universe(_scan(tmp_path, tech2, ml=ml, name="us_full_scan_20260103.xlsx")).set_index("Symbol")
    assert u2["ML_Direction"].tolist() == ["BEARISH", "BEARISH"] and "ML_Confidence" not in u2.columns


def test_load_universe_fund_only_and_errors(tmp_path):
    fund = pd.DataFrame({"Symbol": ["x"], "Piotroski_Score": [7]})
    u = eng.load_universe(_scan(tmp_path, fund=fund))
    assert u["Symbol"].tolist() == ["X"]
    with pytest.raises(ValueError, match="no All_Stocks"):
        eng.load_universe(_scan(tmp_path, gc=pd.DataFrame({"Symbol": ["a"]}), name="us_full_scan_1.xlsx"))
    with pytest.raises(ValueError, match="missing Symbol"):
        eng.load_universe(_scan(tmp_path, tech=pd.DataFrame({"Ticker": ["a"]}), name="us_full_scan_2.xlsx"))


def test_load_universe_golden_sheet_without_symbol_column(tmp_path):
    tech = pd.DataFrame({"Symbol": ["a"]})
    u = eng.load_universe(_scan(tmp_path, tech, gc=pd.DataFrame({"Other": ["a"]})))
    assert u["golden_cross"].tolist() == [False]


# ---------- _screen_flags ----------
def _flags(**cols):
    n = len(next(iter(cols.values())))
    df = pd.DataFrame({"Symbol": [f"S{i}" for i in range(n)], **cols})
    return eng._screen_flags(df)


def test_flags_breakout_and_piotroski_rule():
    f = _flags(Darvas_Signal=["breakout_buy", "BREAKDOWN_SELL", None], Piotroski_Score=[7, 6, np.nan])
    assert f["scr_breakout"].tolist() == [True, False, False]
    assert f["scr_piotroski"].tolist() == [True, False, False]       # >=7 boundary


def test_flags_piotroski_strong_column_overrides_score():
    f = _flags(Piotroski_Strong=["YES", "NO"], Piotroski_Score=[1, 9])
    assert f["scr_piotroski"].tolist() == [True, False]


def test_flags_missing_columns_all_false():
    f = _flags(LTP=[1.0, 2.0])
    for c in ("scr_breakout", "scr_piotroski", "scr_coffee", "scr_magic", "scr_bull", "scr_gc",
              "scr_quality_ab", "scr_actionable", "scr_ml", "scr_above_ema50"):
        assert not f[c].any(), c
    assert f["screens_passed"].tolist() == [0, 0] and f["screens_list"].tolist() == ["", ""]


def test_flags_coffee_magic_bull_gc_quality():
    f = _flags(CoffeeCan=["PASS", "x"], MagicFormula=["Y", "x"], BullCartel=["TRUE", "x"],
               golden_cross=[True, False], Quality_Grade=["a", "C"])
    assert f["scr_coffee"].tolist() == [True, False]
    assert f["scr_magic"].tolist() == [True, False]
    assert f["scr_bull"].tolist() == [True, False]
    assert f["scr_gc"].tolist() == [True, False]
    assert f["scr_quality_ab"].tolist() == [True, False]
    assert f["screens_passed"].tolist() == [5, 0]
    assert f["screens_list"].iloc[0] == "Coffee Can; Magic Formula; Bull Cartel; Golden cross; Quality A/B"


def test_flags_actionable_and_ema_object_and_bool_dtypes():
    f = _flags(Actionable=pd.Series(["1.0", "True", "no", "YES"], dtype=object),
               Above_EMA50=pd.Series(["TRUE", "1.0", "0", "nope"], dtype=object))
    assert f["scr_actionable"].tolist() == [True, True, False, True]
    assert f["scr_above_ema50"].tolist() == [True, True, False, False]
    g = _flags(Actionable=[True, False], Above_EMA50=[False, True])
    assert g["scr_actionable"].tolist() == [True, False]
    assert g["scr_above_ema50"].tolist() == [False, True]


@pytest.mark.xfail(
    int(pd.__version__.split(".")[0]) >= 3,
    strict=True,
    reason="pandas>=3 infers the 'str' dtype, so `act.dtype == object` is False and the text branch of "
           "_screen_flags is skipped: any non-empty string such as 'no' becomes True (engine.py Actionable/Above_EMA50)",
)
def test_flags_text_flags_with_inferred_string_dtype():
    f = _flags(Actionable=["1.0", "True", "no", "YES"], Above_EMA50=["TRUE", "1.0", "0", "nope"])
    assert f["scr_actionable"].tolist() == [True, True, False, True]
    assert f["scr_above_ema50"].tolist() == [True, True, False, False]


def test_flags_ml_boundaries():
    f = _flags(
        ML_Direction=["BULLISH"] * 6 + ["bearish"],
        ML_Confidence=[0.55, 0.549, 0.9, 0.9, 0.9, np.nan, 0.9],
        **{"ML_Pred_Ret%": [10, 10, 40.0, 40.1, 0.0, 10, 10]},
    )
    assert f["scr_ml"].tolist() == [True, False, True, False, False, False, False]


def test_flags_ml_without_numeric_columns_is_false():
    assert not _flags(ML_Direction=["BULLISH"])["scr_ml"].any()


# ---------- scoring ----------
def _full(**over):
    base = dict(scr_breakout=False, scr_piotroski=False, scr_coffee=False, scr_magic=False, scr_bull=False,
                scr_gc=False, scr_quality_ab=False, scr_actionable=False, scr_ml=False, scr_above_ema50=False)
    base.update(over)
    return pd.DataFrame({k: [v] if not isinstance(v, list) else v for k, v in base.items()})


def test_conviction_each_weight():
    w = cfg.WEIGHTS
    pairs = [("scr_breakout", "breakout"), ("scr_piotroski", "piotroski_strong"), ("scr_coffee", "coffee_can"),
             ("scr_magic", "magic_formula"), ("scr_bull", "bull_cartel"), ("scr_gc", "golden_cross"),
             ("scr_quality_ab", "quality_ab"), ("scr_actionable", "actionable"), ("scr_ml", "ml_bullish"),
             ("scr_above_ema50", "above_ema50")]
    for col, key in pairs:
        assert eng._conviction_score(_full(**{col: True})).iloc[0] == float(w[key]), col


def test_conviction_boosts_and_clip():
    df = _full(scr_breakout=True, scr_piotroski=True)
    df["Quality_Score"] = [50]
    df["Piotroski_Score"] = [8]
    df["Liquidity_Tier"] = ["T1_MOST_LIQUID"]
    assert eng._conviction_score(df).iloc[0] == 47.3
    df["Quality_Score"] = [500]        # clipped to 100 -> +8
    df["Piotroski_Score"] = [99]       # clipped to 9 -> +6
    assert eng._conviction_score(df).iloc[0] == 34 + 8 + 6 + 4
    big = _full(**{c: True for c in _full().columns})
    big["Quality_Score"], big["Piotroski_Score"], big["Liquidity_Tier"] = 100, 9, "T1_MOST_LIQUID"
    assert eng._conviction_score(big).iloc[0] == 100.0


@pytest.mark.parametrize("tier,delta", [("T1_MOST_LIQUID", 4.0), ("T2_LIQUID", 3.0), ("T3_MID", 1.5),
                                         ("T4_ILLIQUID", 0.0), ("T5_MOST_ILLIQUID", -2.0), ("weird", 0.0)])
def test_conviction_tier_adjustment(tier, delta):
    df = _full(scr_breakout=True)
    df["Liquidity_Tier"] = tier
    assert eng._conviction_score(df).iloc[0] == 18 + delta


def test_conviction_floor_zero():
    df = _full()
    df["Liquidity_Tier"] = "T5_MOST_ILLIQUID"
    assert eng._conviction_score(df).iloc[0] == 0.0


@pytest.mark.parametrize(
    "row,expected",
    [
        (dict(conviction_score=48, screens_passed=2), "CORE"),
        (dict(conviction_score=47.9, screens_passed=2), "WATCH"),
        (dict(conviction_score=60, screens_passed=1), "WATCH"),
        (dict(conviction_score=60, screens_passed=1, scr_breakout=True), "MOMENTUM"),
        (dict(conviction_score=35, screens_passed=1, scr_gc=True), "MOMENTUM"),
        (dict(conviction_score=34.9, screens_passed=1, scr_actionable=True), "WATCH"),
        (dict(conviction_score=32, screens_passed=1, scr_piotroski=True), "QUALITY"),
        (dict(conviction_score=32, screens_passed=1, scr_coffee=True), "QUALITY"),
        (dict(conviction_score=32, screens_passed=1, scr_magic=True), "QUALITY"),
        (dict(conviction_score=31.9, screens_passed=1, scr_magic=True), "WATCH"),
        (dict(conviction_score=25, screens_passed=1), "WATCH"),
        (dict(conviction_score=24.9, screens_passed=1), "PASS"),
        (dict(conviction_score=25, screens_passed=0), "PASS"),
        (dict(), "PASS"),
        (dict(conviction_score=np.nan, screens_passed=np.nan), "PASS"),
    ],
)
def test_assign_sleeve(row, expected):
    if "conviction_score" in row and pd.isna(row["conviction_score"]):
        row = {"conviction_score": None, "screens_passed": None}
    assert eng._assign_sleeve(pd.Series(row)) == expected


def test_assign_sleeve_momentum_beats_quality_when_both():
    r = pd.Series(dict(conviction_score=40, screens_passed=1, scr_breakout=True, scr_piotroski=True))
    assert eng._assign_sleeve(r) == "MOMENTUM"


# ---------- thesis ----------
def test_thesis_full_row():
    r = pd.Series(dict(Name="Apple", Sector="Tech", screens_list="Darvas breakout", LTP=100.0, **{"Change%": 1.234},
                       Piotroski_Score=8.0, **{"ROE_avg_%": 15.55}, Quality_Grade="A", Quality_Score=82.0,
                       Liquidity_Tier="T1_MOST_LIQUID", Turnover_USD=5_000_000.0, sleeve="CORE"))
    t = eng._thesis(r)
    assert t == ("Apple (Tech). Hits: Darvas breakout. Price $100.00, +1.2% day. Piotroski F=8. Avg ROE 15.6%. "
                 "Breakout quality A (82). Liquidity T1_MOST_LIQUID · ~$5,000,000/day. "
                 "Multi-screen agreement → highest conviction sleeve.")


def test_thesis_minimal_and_sleeve_variants():
    r = pd.Series(dict(Symbol="XYZ"))
    assert eng._thesis(r) == "XYZ (Unknown sector)."
    for sleeve, frag in (("MOMENTUM", "Technical momentum"), ("QUALITY", "quality/value sleeve"),
                         ("WATCH", "Watchlist only"), ("PASS", None)):
        t = eng._thesis(pd.Series(dict(Symbol="X", sleeve=sleeve)))
        assert (frag in t) if frag else t == "X (Unknown sector)."


def test_thesis_optional_pieces():
    r = pd.Series(dict(Symbol="X", LTP=10.0, Quality_Grade="nan", Turnover_USD=1e6))
    t = eng._thesis(r)
    assert "Price $10.00." in t and "% day" not in t and "Breakout quality" not in t
    assert "Liquidity ? · ~$1,000,000/day." in t
    r2 = pd.Series(dict(Symbol="X", Quality_Grade="B"))
    assert "Breakout quality B." in eng._thesis(r2)
    r3 = pd.Series(dict(Symbol="X", Quality_Grade="None"))
    assert "Breakout quality" not in eng._thesis(r3)
    r4 = pd.Series(dict(Symbol="X", Quality_Grade=""))
    assert "Breakout quality" not in eng._thesis(r4)


# ---------- filters ----------
def _universe():
    return pd.DataFrame({
        "Symbol": list("ABCDEFGH"),
        "LTP": [10, 4.99, 5.0, 10, 10, 10, 10, 10],
        "Turnover_USD": [3e6, 3e6, 3e6, 1.99e6, np.nan, 3e6, 2e6, 3e6],
        "Liquidity_Tier": ["T1_MOST_LIQUID", "T1_MOST_LIQUID", "T2_LIQUID", "T1_MOST_LIQUID", "T3_MID",
                           "T4_ILLIQUID", "mystery", "T1_MOST_LIQUID"],
        "screens_passed": [1, 1, 1, 1, 1, 1, 1, 0],
        "scr_piotroski": False, "scr_coffee": False, "scr_magic": False,
    })


def test_apply_filters_matrix():
    out = eng.apply_filters(_universe())
    # B price<5; D turnover below; F illiquid tier; H no screens
    assert out["Symbol"].tolist() == ["A", "C", "E", "G"]


def test_apply_filters_unknown_tier_needs_turnover():
    u = _universe()
    u.loc[u.Symbol == "G", "Turnover_USD"] = 1.99e6
    assert "G" not in eng.apply_filters(u)["Symbol"].tolist()
    u.loc[u.Symbol == "G", "Turnover_USD"] = np.nan
    assert "G" not in eng.apply_filters(u)["Symbol"].tolist()   # missing turnover is not 'liquid by turnover'


def test_apply_filters_options():
    u = _universe()
    assert "H" in eng.apply_filters(u, require_screen=False)["Symbol"].tolist()
    assert "F" in eng.apply_filters(u, allowed_tiers=())["Symbol"].tolist()
    assert "B" in eng.apply_filters(u, min_price=4.0)["Symbol"].tolist()
    assert "D" in eng.apply_filters(u, min_turnover=1e6)["Symbol"].tolist()


def test_apply_filters_missing_columns():
    df = pd.DataFrame({"Symbol": ["A"], "screens_passed": [1], "scr_piotroski": [False], "scr_coffee": [False],
                       "scr_magic": [False]})
    assert eng.apply_filters(df).empty            # no price -> fails the price gate


def test_apply_filters_breakdown_rule():
    u = _universe().iloc[:1].copy()
    u["Darvas_Signal"] = "breakdown_sell"
    assert eng.apply_filters(u).empty
    for col in ("scr_piotroski", "scr_coffee", "scr_magic"):
        v = u.copy()
        v[col] = True
        assert len(eng.apply_filters(v)) == 1, col


# ---------- rank / diversify / portfolio ----------
def _ranked_input():
    cols = dict(Symbol=list("ABCDE"),
                scr_breakout=[True, True, False, False, False],
                scr_piotroski=[True, False, True, False, False],
                scr_coffee=[True, False, False, False, False],
                scr_magic=[False, False, True, False, False],
                scr_bull=[False, False, True, False, False],
                scr_gc=[False, True, False, False, False],
                scr_quality_ab=False, scr_actionable=False,
                scr_ml=[False, True, False, False, False],
                scr_above_ema50=[False, True, False, False, False],
                screens_passed=[3, 1, 1, 0, 0],
                Turnover_USD=[1e6, 5e6, 2e6, 9e9, 1e6],
                Sector=["Tech", "Tech", "Fin", "Fin", "Fin"])
    return pd.DataFrame(cols)


def test_rank_picks_order_and_pass_drop():
    r = eng.rank_picks(_ranked_input())
    assert r["Symbol"].tolist() == ["A", "C", "B"]          # D, E are PASS; QUALITY ranks before MOMENTUM
    assert r["sleeve"].tolist() == ["CORE", "QUALITY", "MOMENTUM"]
    assert r["rank"].tolist() == [1, 2, 3] and r["conviction_score"].tolist() == [48.0, 36.0, 36.0]
    assert "_sr" not in r.columns and "_to" not in r.columns and (r["thesis"].str.len() > 0).all()


def test_rank_picks_tiebreaks_screens_then_turnover():
    d = pd.DataFrame(dict(Symbol=list("XYZ"), scr_breakout=True, scr_piotroski=False, scr_coffee=False,
                          scr_magic=False, scr_bull=False, scr_gc=True, scr_quality_ab=False,
                          scr_actionable=False, scr_ml=True, scr_above_ema50=True,
                          screens_passed=[1, 2, 2], Turnover_USD=[9.0, 1.0, 5.0]))
    d["conviction_score"] = 0   # overwritten by rank_picks
    assert eng.rank_picks(d)["Symbol"].tolist() == ["Z", "Y", "X"]


def test_rank_picks_without_turnover_column():
    d = _ranked_input().drop(columns=["Turnover_USD"])
    assert eng.rank_picks(d)["Symbol"].tolist() == ["A", "C", "B"]


def _picks(sectors):
    return pd.DataFrame({"Symbol": [f"S{i}" for i in range(len(sectors))], "Sector": sectors})


def test_diversify_caps_and_preserves_order():
    out = eng.diversify(_picks(["A", "A", "A", "A", "B", "C"]), n=4, max_per_sector=2)
    assert out["Symbol"].tolist() == ["S0", "S1", "S4", "S5"]
    assert out["investor_rank"].tolist() == [1, 2, 3, 4]


def test_diversify_fills_from_remainder_when_short():
    out = eng.diversify(_picks(["A", "A", "A", "A"]), n=3, max_per_sector=1)
    assert out["Symbol"].tolist() == ["S0", "S1", "S2"]


def test_diversify_n_boundary_and_empty_and_unknown_sector():
    out = eng.diversify(_picks(["A", "B", "C"]), n=2, max_per_sector=3)
    assert len(out) == 2
    assert eng.diversify(pd.DataFrame(), n=3).empty
    unk = eng.diversify(pd.DataFrame({"Symbol": ["a", "b"], "Sector": [None, None]}), n=5, max_per_sector=1)
    assert len(unk) == 2        # second None-sector row comes back via the remainder fill


def test_diversify_returns_all_when_fewer_than_n():
    assert len(eng.diversify(_picks(["A", "B"]), n=10, max_per_sector=1)) == 2


def test_build_portfolio_weights_and_preference():
    p = pd.DataFrame({"Symbol": list("ABCD"), "sleeve": ["WATCH", "CORE", "QUALITY", "MOMENTUM"],
                      "LTP": [10.0, 50.0, 25.0, 100.0]})
    port = eng.build_portfolio(p, size=2)
    assert port["Symbol"].tolist() == ["B", "C"]
    assert port["weight"].tolist() == [0.5, 0.5]
    assert port["notional_per_100k"].tolist() == [50000.0, 50000.0]
    assert port["shares_per_100k"].tolist() == [1000.0, 2000.0]


def test_build_portfolio_rounds_weight_and_fallbacks():
    p = pd.DataFrame({"Symbol": list("ABC"), "sleeve": ["CORE"] * 3, "LTP": [3.0] * 3})
    port = eng.build_portfolio(p, size=10)
    assert port["weight"].tolist() == [0.3333] * 3
    assert port["notional_per_100k"].tolist() == [33330.0] * 3
    only_watch = pd.DataFrame({"Symbol": ["A"], "sleeve": ["WATCH"], "LTP": [10.0]})
    assert eng.build_portfolio(only_watch)["Symbol"].tolist() == ["A"]
    assert eng.build_portfolio(only_watch.iloc[0:0]).empty
    no_ltp = pd.DataFrame({"Symbol": ["A"], "sleeve": ["CORE"]})
    assert "shares_per_100k" not in eng.build_portfolio(no_ltp).columns


def test_build_portfolio_size_zero_returns_empty():
    p = pd.DataFrame({"Symbol": ["A"], "sleeve": ["CORE"], "LTP": [1.0]})
    assert eng.build_portfolio(p, size=0).empty


def test_quant_frame_columns_and_limit():
    r = pd.DataFrame({"rank": range(1, 6), "Symbol": list("ABCDE"), "extra": 1, "thesis": "t"})
    q = eng.quant_frame(r, n=3)
    assert q.columns.tolist() == ["rank", "Symbol", "thesis"] and len(q) == 3
    assert len(eng.quant_frame(r, n=None)) == 5
    assert len(eng.quant_frame(r)) == 5      # default TOP_QUANT_ROWS=100


# ---------- run_picks ----------
def make_scan(tmp_path, name="us_full_scan_20260102_0930.xlsx"):
    syms = [f"S{i:02d}" for i in range(14)]
    tech = pd.DataFrame({
        "Symbol": syms,
        "Name": [f"Name {s}" for s in syms],
        "Sector": ["Tech"] * 6 + ["Fin"] * 4 + ["Health"] * 4,
        "LTP": [50.0] * 13 + [2.0],
        "Change%": [1.0] * 14,
        "Turnover_USD": [5e6] * 13 + [5e6],
        "Liquidity_Tier": ["T1_MOST_LIQUID"] * 14,
        "Darvas_Signal": ["BREAKOUT_BUY"] * 8 + ["NONE"] * 6,
        "Quality_Grade": ["A"] * 14,
        "Quality_Score": [80.0] * 14,
        "Above_EMA50": [True] * 14,
        "Actionable": [True] * 14,
    })
    fund = pd.DataFrame({"Symbol": syms, "Piotroski_Score": [8] * 14, "Piotroski_Strong": ["YES"] * 14,
                         "CoffeeCan": ["YES"] * 5 + ["NO"] * 9})
    return _scan(tmp_path, tech, fund, pd.DataFrame({"Symbol": syms[:3]}), name=name)


def test_run_picks_end_to_end(tmp_path):
    p = make_scan(tmp_path)
    res = eng.run_picks(scan_path=p, top=5, max_per_sector=2, portfolio_size=3)
    assert res.as_of == "2026-01-02 09:30" and res.scan_path == str(p)
    assert res.universe_n == 14 and res.liquid_n == 13          # S13 priced $2 gated out
    assert res.summary["liquid_n"] == 13 and res.summary["ranked_n"] == len(res.ranked)
    assert res.summary["filters"] == {"min_price": 5.0, "min_turnover_usd": 2_000_000.0,
                                      "allowed_tiers": list(cfg.ALLOWED_LIQUIDITY_TIERS)}
    assert len(res.investor_picks) == 5 and len(res.portfolio) == 3
    assert res.investor_picks["Sector"].value_counts().max() <= 2
    assert res.summary["sleeve_counts"] == res.ranked["sleeve"].value_counts().to_dict()
    assert res.summary["avg_conviction_top"] == float(res.investor_picks["conviction_score"].mean())
    assert res.portfolio["weight"].tolist() == [0.3333] * 3
    assert "S13" not in res.ranked["Symbol"].tolist()


def test_run_picks_uses_scan_dir_and_filters(tmp_path):
    make_scan(tmp_path)
    res = eng.run_picks(scan_dir=tmp_path, min_price=1.0, top=20)
    assert res.liquid_n == 14


@pytest.mark.xfail(strict=True, raises=ValueError,
                   reason="engine.py rank_picks: DataFrame.apply(axis=1) on an empty frame returns a DataFrame, "
                          "so assigning it to out['sleeve'] raises; run_picks crashes when no row passes the liquidity gate")
def test_run_picks_when_nothing_passes_filters(tmp_path):
    make_scan(tmp_path)
    res = eng.run_picks(scan_dir=tmp_path, min_turnover=6e6)
    assert res.liquid_n == 0 and res.investor_picks.empty and res.summary["sleeve_counts"] == {}
    assert res.summary["avg_conviction_top"] == 0.0 and res.portfolio.empty


def test_run_picks_no_scan_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        eng.run_picks(scan_dir=tmp_path)
