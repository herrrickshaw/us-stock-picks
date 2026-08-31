"""
US stock-picks engine.

Loads the latest full US market scan workbook (Darvas / Piotroski / Coffee Can /
Magic Formula / Bull Cartel / Golden Cross / ML), applies investor-safe
liquidity gates, scores multi-screen conviction, and assigns portfolio sleeves.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import config as cfg


def find_latest_scan(scan_dir: Path | None = None, pattern: str = "us_full_scan_*.xlsx") -> Path:
    """Return newest US full-scan workbook, or raise FileNotFoundError."""
    dirs: list[Path] = []
    if scan_dir is not None:
        dirs.append(Path(scan_dir))
    dirs.extend(cfg.DEFAULT_SCAN_DIRS)

    candidates: list[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        candidates.extend(d.glob(pattern))
        # also accept a single "latest" alias
        latest_alias = d / "us_full_scan_latest.xlsx"
        if latest_alias.exists():
            candidates.append(latest_alias)

    if not candidates:
        searched = ", ".join(str(d) for d in dirs)
        raise FileNotFoundError(
            f"No US scan workbooks matching {pattern!r}. Searched: {searched}\n"
            "Run: python market-pipeline/code/python_files/full_us_market_scan.py"
        )

    candidates = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _scan_as_of(path: Path) -> str:
    m = re.search(r"(\d{8})[_T]?(\d{4})?", path.stem)
    if not m:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    d = m.group(1)
    t = m.group(2) or "0000"
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:]}"


def _read_sheet(path: Path, name: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name=name)
    except ValueError:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    # drop fully empty workbooks (openpyxl sometimes yields 0-col sheets)
    if df.shape[1] == 0:
        return pd.DataFrame()
    return df


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _boolish(series: pd.Series, true_vals: set[str] | None = None) -> pd.Series:
    true_vals = true_vals or {"YES", "PASS", "TRUE", "1", "Y"}
    if series is None:
        return pd.Series(dtype=bool)
    s = series.astype(str).str.strip().str.upper()
    return s.isin(true_vals)


def load_universe(scan_path: Path) -> pd.DataFrame:
    """Merge technical + fundamental + ML sheets into one symbol-level frame."""
    tech = _read_sheet(scan_path, "All_Stocks")
    fund = _read_sheet(scan_path, "All_Fundamentals")
    ml_bull = _read_sheet(scan_path, "ML_Bullish")
    gc = _read_sheet(scan_path, "Golden_Crossover")

    if tech.empty and fund.empty:
        raise ValueError(f"Scan workbook has no All_Stocks / All_Fundamentals: {scan_path}")

    if tech.empty:
        base = fund.copy()
    else:
        base = tech.copy()

    if "Symbol" not in base.columns:
        raise ValueError("Scan sheet missing Symbol column")

    base["Symbol"] = base["Symbol"].astype(str).str.strip().str.upper()
    base = base.drop_duplicates(subset=["Symbol"], keep="first")

    if not fund.empty:
        fund = fund.copy()
        fund["Symbol"] = fund["Symbol"].astype(str).str.strip().str.upper()
        fund = fund.drop_duplicates(subset=["Symbol"], keep="first")
        # Prefer fund name/sector/price when present; keep tech quality fields.
        overlap = [c for c in fund.columns if c in base.columns and c != "Symbol"]
        fund_renamed = fund.rename(columns={c: f"{c}_fund" for c in overlap})
        base = base.merge(fund_renamed, on="Symbol", how="outer")
        # Coalesce overlapping numeric/text fields
        for c in overlap:
            left, right = c, f"{c}_fund"
            if right in base.columns:
                base[c] = base[c].combine_first(base[right])
                base.drop(columns=[right], inplace=True)

    # Golden cross set
    gc_syms: set[str] = set()
    if not gc.empty and "Symbol" in gc.columns:
        gc_syms = set(gc["Symbol"].astype(str).str.strip().str.upper())
    base["golden_cross"] = base["Symbol"].isin(gc_syms)

    # ML from fund sheet if present; else ML_Bullish sheet
    if "ML_Direction" not in base.columns and not ml_bull.empty:
        ml_bull = ml_bull.copy()
        ml_bull["Symbol"] = ml_bull["Symbol"].astype(str).str.strip().str.upper()
        base = base.merge(ml_bull, on="Symbol", how="left")

    base["scan_path"] = str(scan_path)
    base["as_of"] = _scan_as_of(scan_path)
    return base


def _screen_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    darvas = out.get("Darvas_Signal", pd.Series(index=out.index, dtype=object)).astype(str).str.upper()
    out["scr_breakout"] = darvas.eq("BREAKOUT_BUY")

    if "Piotroski_Strong" in out.columns:
        out["scr_piotroski"] = _boolish(out["Piotroski_Strong"])
    else:
        p = _num(out["Piotroski_Score"]) if "Piotroski_Score" in out.columns else pd.Series(0, index=out.index)
        out["scr_piotroski"] = p.fillna(0) >= 7

    out["scr_coffee"] = (
        _boolish(out["CoffeeCan"]) if "CoffeeCan" in out.columns else pd.Series(False, index=out.index)
    )
    out["scr_magic"] = (
        _boolish(out["MagicFormula"]) if "MagicFormula" in out.columns else pd.Series(False, index=out.index)
    )
    out["scr_bull"] = (
        _boolish(out["BullCartel"]) if "BullCartel" in out.columns else pd.Series(False, index=out.index)
    )
    out["scr_gc"] = out.get("golden_cross", pd.Series(False, index=out.index)).astype(bool)

    qg = out.get("Quality_Grade", pd.Series(index=out.index, dtype=object)).astype(str).str.upper()
    out["scr_quality_ab"] = qg.isin(["A", "B"])

    act = out.get("Actionable", pd.Series(False, index=out.index))
    if act.dtype == object:
        out["scr_actionable"] = _boolish(act) | act.astype(str).isin(["1", "1.0", "True", "true"])
    else:
        out["scr_actionable"] = act.fillna(False).astype(bool)

    above = out.get("Above_EMA50", pd.Series(False, index=out.index))
    if above.dtype == object:
        out["scr_above_ema50"] = _boolish(above) | above.astype(str).str.upper().isin(["TRUE", "1", "1.0"])
    else:
        out["scr_above_ema50"] = above.fillna(False).astype(bool)

    ml_dir = out.get("ML_Direction", pd.Series(index=out.index, dtype=object)).astype(str).str.upper()
    ml_conf = _num(out["ML_Confidence"]) if "ML_Confidence" in out.columns else pd.Series(0.0, index=out.index)
    ml_pred = _num(out["ML_Pred_Ret%"]) if "ML_Pred_Ret%" in out.columns else pd.Series(0.0, index=out.index)
    out["scr_ml"] = (
        ml_dir.eq("BULLISH")
        & (ml_conf.fillna(0) >= cfg.ML_MIN_CONFIDENCE)
        & (ml_pred.fillna(0).abs() <= cfg.ML_MAX_PRED_RET_PCT)
        & (ml_pred.fillna(0) > 0)
    )

    flag_cols = [
        "scr_breakout",
        "scr_piotroski",
        "scr_coffee",
        "scr_magic",
        "scr_bull",
        "scr_gc",
        "scr_quality_ab",
        "scr_actionable",
        "scr_ml",
        "scr_above_ema50",
    ]
    out["screens_passed"] = out[flag_cols].sum(axis=1).astype(int)

    # Human-readable screen list
    labels = {
        "scr_breakout": "Darvas breakout",
        "scr_piotroski": "Piotroski strong",
        "scr_coffee": "Coffee Can",
        "scr_magic": "Magic Formula",
        "scr_bull": "Bull Cartel",
        "scr_gc": "Golden cross",
        "scr_quality_ab": "Quality A/B",
        "scr_actionable": "Actionable setup",
        "scr_ml": "ML bullish",
        "scr_above_ema50": "Above EMA50",
    }

    def _list_screens(row: pd.Series) -> str:
        hits = [lab for col, lab in labels.items() if bool(row.get(col))]
        return "; ".join(hits)

    out["screens_list"] = out.apply(_list_screens, axis=1)
    return out


def _conviction_score(df: pd.DataFrame) -> pd.Series:
    w = cfg.WEIGHTS
    score = (
        df["scr_breakout"].astype(int) * w["breakout"]
        + df["scr_piotroski"].astype(int) * w["piotroski_strong"]
        + df["scr_coffee"].astype(int) * w["coffee_can"]
        + df["scr_magic"].astype(int) * w["magic_formula"]
        + df["scr_bull"].astype(int) * w["bull_cartel"]
        + df["scr_gc"].astype(int) * w["golden_cross"]
        + df["scr_quality_ab"].astype(int) * w["quality_ab"]
        + df["scr_actionable"].astype(int) * w["actionable"]
        + df["scr_ml"].astype(int) * w["ml_bullish"]
        + df["scr_above_ema50"].astype(int) * w["above_ema50"]
    ).astype(float)

    # Continuous boosts from quality / F-score / liquidity
    qs = _num(df["Quality_Score"]) if "Quality_Score" in df.columns else pd.Series(0.0, index=df.index)
    score = score + (qs.fillna(0).clip(0, 100) / 100.0) * 8.0

    ps = _num(df["Piotroski_Score"]) if "Piotroski_Score" in df.columns else pd.Series(0.0, index=df.index)
    score = score + (ps.fillna(0).clip(0, 9) / 9.0) * 6.0

    tier = df.get("Liquidity_Tier", pd.Series("", index=df.index)).astype(str)
    score = score + tier.map(
        {
            "T1_MOST_LIQUID": 4.0,
            "T2_LIQUID": 3.0,
            "T3_MID": 1.5,
            "T4_ILLIQUID": 0.0,
            "T5_MOST_ILLIQUID": -2.0,
        }
    ).fillna(0.0)

    return score.clip(0, 100).round(1)


def _assign_sleeve(row: pd.Series) -> str:
    score = float(row.get("conviction_score") or 0)
    n = int(row.get("screens_passed") or 0)
    if score >= cfg.CORE_MIN_SCORE and n >= cfg.CORE_MIN_SCREENS:
        return "CORE"
    if row.get("scr_breakout") or row.get("scr_gc") or row.get("scr_actionable"):
        if score >= cfg.MOMENTUM_MIN_SCORE:
            return "MOMENTUM"
    if row.get("scr_piotroski") or row.get("scr_coffee") or row.get("scr_magic"):
        if score >= cfg.QUALITY_MIN_SCORE:
            return "QUALITY"
    if score >= 25 and n >= 1:
        return "WATCH"
    return "PASS"


def _thesis(row: pd.Series) -> str:
    bits: list[str] = []
    name = row.get("Name") or row.get("Symbol")
    sector = row.get("Sector") or "Unknown sector"
    bits.append(f"{name} ({sector}).")

    screens = row.get("screens_list") or ""
    if screens:
        bits.append(f"Hits: {screens}.")

    ltp = row.get("LTP")
    chg = row.get("Change%")
    if pd.notna(ltp):
        chg_s = f", {float(chg):+.1f}% day" if pd.notna(chg) else ""
        bits.append(f"Price ${float(ltp):.2f}{chg_s}.")

    ps = row.get("Piotroski_Score")
    if pd.notna(ps):
        bits.append(f"Piotroski F={int(ps)}.")

    roe = row.get("ROE_avg_%")
    if pd.notna(roe):
        bits.append(f"Avg ROE {float(roe):.1f}%.")

    qg = row.get("Quality_Grade")
    qs = row.get("Quality_Score")
    if pd.notna(qg) and str(qg) not in ("", "nan", "None"):
        qs_s = f" ({float(qs):.0f})" if pd.notna(qs) else ""
        bits.append(f"Breakout quality {qg}{qs_s}.")

    tier = row.get("Liquidity_Tier")
    to = row.get("Turnover_USD")
    if pd.notna(to):
        bits.append(f"Liquidity {tier or '?'} · ~${float(to):,.0f}/day.")

    sleeve = row.get("sleeve")
    if sleeve == "CORE":
        bits.append("Multi-screen agreement → highest conviction sleeve.")
    elif sleeve == "MOMENTUM":
        bits.append("Technical momentum sleeve — prefer strength + volume confirmation.")
    elif sleeve == "QUALITY":
        bits.append("Fundamental quality/value sleeve — suitable for longer hold.")
    elif sleeve == "WATCH":
        bits.append("Watchlist only — needs confirmation before size.")

    return " ".join(bits)


def apply_filters(
    df: pd.DataFrame,
    *,
    min_price: float = cfg.MIN_PRICE,
    min_turnover: float = cfg.MIN_TURNOVER_USD,
    allowed_tiers: tuple[str, ...] = cfg.ALLOWED_LIQUIDITY_TIERS,
    require_screen: bool = True,
) -> pd.DataFrame:
    out = df.copy()
    price = _num(out["LTP"]) if "LTP" in out.columns else pd.Series(float("nan"), index=out.index)
    turn = _num(out["Turnover_USD"]) if "Turnover_USD" in out.columns else pd.Series(float("nan"), index=out.index)
    tier = out.get("Liquidity_Tier", pd.Series("", index=out.index)).astype(str)

    mask = price.fillna(0) >= min_price
    # If turnover missing, fall back to tier only
    has_turn = turn.notna()
    mask &= (~has_turn) | (turn >= min_turnover)
    if allowed_tiers:
        # Keep rows with known good tiers; also keep UNKNOWN if liquid by turnover
        good_tier = tier.isin(list(allowed_tiers))
        unknown = ~tier.isin(
            ["T1_MOST_LIQUID", "T2_LIQUID", "T3_MID", "T4_ILLIQUID", "T5_MOST_ILLIQUID"]
        )
        mask &= good_tier | (unknown & (turn.fillna(0) >= min_turnover))

    if require_screen:
        mask &= out["screens_passed"].fillna(0) >= 1

    # Drop pure breakdowns unless they still have strong fundamental screens
    darvas = out.get("Darvas_Signal", pd.Series("", index=out.index)).astype(str).str.upper()
    breakdown = darvas.eq("BREAKDOWN_SELL")
    fund_ok = out["scr_piotroski"] | out["scr_coffee"] | out["scr_magic"]
    mask &= ~breakdown | fund_ok

    return out.loc[mask].copy()


def rank_picks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["conviction_score"] = _conviction_score(out)
    out["sleeve"] = out.apply(_assign_sleeve, axis=1)
    out = out[out["sleeve"] != "PASS"].copy()
    out["thesis"] = out.apply(_thesis, axis=1)

    # Sort: CORE first, then score, then screens, then turnover
    sleeve_rank = {"CORE": 0, "QUALITY": 1, "MOMENTUM": 2, "WATCH": 3}
    out["_sr"] = out["sleeve"].map(sleeve_rank).fillna(9)
    turn = _num(out["Turnover_USD"]) if "Turnover_USD" in out.columns else pd.Series(0, index=out.index)
    out["_to"] = turn.fillna(0)
    out = out.sort_values(
        ["_sr", "conviction_score", "screens_passed", "_to"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    out["rank"] = out.index + 1
    out.drop(columns=["_sr", "_to"], inplace=True)
    return out


def diversify(
    df: pd.DataFrame,
    n: int = cfg.TOP_INVESTOR_PICKS,
    max_per_sector: int = cfg.MAX_PER_SECTOR,
) -> pd.DataFrame:
    """Greedy sector-capped selection preserving conviction order."""
    if df.empty:
        return df
    picked: list[int] = []
    sector_count: dict[str, int] = {}
    for idx, row in df.iterrows():
        sector = str(row.get("Sector") or "Unknown")
        if sector_count.get(sector, 0) >= max_per_sector:
            continue
        picked.append(idx)
        sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(picked) >= n:
            break
    # If sector cap left us short, fill from remainder
    if len(picked) < n:
        for idx in df.index:
            if idx in picked:
                continue
            picked.append(idx)
            if len(picked) >= n:
                break
    out = df.loc[picked].copy().reset_index(drop=True)
    out["investor_rank"] = out.index + 1
    return out


def build_portfolio(picks: pd.DataFrame, size: int = cfg.EQUAL_WEIGHT_PORTFOLIO_SIZE) -> pd.DataFrame:
    """Equal-weight paper portfolio from top diversified CORE/QUALITY/MOMENTUM picks."""
    if picks.empty:
        return picks
    prefer = picks[picks["sleeve"].isin(["CORE", "QUALITY", "MOMENTUM"])]
    if prefer.empty:
        prefer = picks
    port = prefer.head(size).copy()
    if port.empty:
        return port
    w = 1.0 / len(port)
    port["weight"] = round(w, 4)
    port["notional_per_100k"] = (port["weight"] * 100_000).round(2)
    if "LTP" in port.columns:
        port["shares_per_100k"] = (port["notional_per_100k"] / _num(port["LTP"])).round(2)
    return port


@dataclass
class PickResult:
    as_of: str
    scan_path: str
    universe_n: int
    liquid_n: int
    ranked: pd.DataFrame
    investor_picks: pd.DataFrame
    portfolio: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)


def run_picks(
    scan_path: Path | None = None,
    scan_dir: Path | None = None,
    *,
    min_price: float = cfg.MIN_PRICE,
    min_turnover: float = cfg.MIN_TURNOVER_USD,
    top: int = cfg.TOP_INVESTOR_PICKS,
    max_per_sector: int = cfg.MAX_PER_SECTOR,
    portfolio_size: int = cfg.EQUAL_WEIGHT_PORTFOLIO_SIZE,
) -> PickResult:
    path = Path(scan_path) if scan_path else find_latest_scan(scan_dir)
    raw = load_universe(path)
    scored = _screen_flags(raw)
    liquid = apply_filters(
        scored,
        min_price=min_price,
        min_turnover=min_turnover,
    )
    ranked = rank_picks(liquid)
    investor = diversify(ranked, n=top, max_per_sector=max_per_sector)
    portfolio = build_portfolio(investor, size=portfolio_size)

    as_of = str(raw["as_of"].iloc[0]) if len(raw) else _scan_as_of(path)
    summary = {
        "as_of": as_of,
        "scan_path": str(path),
        "universe_n": int(len(raw)),
        "liquid_n": int(len(liquid)),
        "ranked_n": int(len(ranked)),
        "sleeve_counts": ranked["sleeve"].value_counts().to_dict() if len(ranked) else {},
        "avg_conviction_top": float(investor["conviction_score"].mean()) if len(investor) else 0.0,
        "filters": {
            "min_price": min_price,
            "min_turnover_usd": min_turnover,
            "allowed_tiers": list(cfg.ALLOWED_LIQUIDITY_TIERS),
        },
    }
    return PickResult(
        as_of=as_of,
        scan_path=str(path),
        universe_n=int(len(raw)),
        liquid_n=int(len(liquid)),
        ranked=ranked,
        investor_picks=investor,
        portfolio=portfolio,
        summary=summary,
    )


# Columns exported for quant consumers
QUANT_COLUMNS = [
    "rank",
    "Symbol",
    "Name",
    "Sector",
    "sleeve",
    "conviction_score",
    "screens_passed",
    "screens_list",
    "LTP",
    "Change%",
    "Turnover_USD",
    "Liquidity_Tier",
    "Quality_Score",
    "Quality_Grade",
    "Darvas_Signal",
    "GC_Signal",
    "Piotroski_Score",
    "Piotroski_Strong",
    "CoffeeCan",
    "CC_Score",
    "MagicFormula",
    "ROIC_%",
    "Earnings_Yield_%",
    "BullCartel",
    "ROE_avg_%",
    "Revenue_CAGR_%",
    "Sales_Growth_YoY_%",
    "Profit_Growth_YoY_%",
    "Above_EMA50",
    "Actionable",
    "ML_Direction",
    "ML_Pred_Ret%",
    "ML_Confidence",
    "thesis",
]


def quant_frame(ranked: pd.DataFrame, n: int | None = cfg.TOP_QUANT_ROWS) -> pd.DataFrame:
    cols = [c for c in QUANT_COLUMNS if c in ranked.columns]
    out = ranked[cols].copy()
    if n is not None:
        out = out.head(n)
    return out
