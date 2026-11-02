"""Unit tests for pure helpers and CLI smoke tests (no network)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.scan_fixture import write_scan
from us_stock_picks import config as cfg
from us_stock_picks import engine
from us_stock_picks.__main__ import main
from us_stock_picks.report import _df_records, write_outputs


def test_scan_as_of_from_filename():
    assert engine._scan_as_of(Path("us_full_scan_20260724_0043.xlsx")) == "2026-07-24 00:43"


def test_screens_table_matches_weights():
    assert set(w for _, _, w in engine.SCREENS) == set(cfg.WEIGHTS)
    assert len(engine.FLAG_COLS) == len(set(engine.FLAG_COLS)) == 10


def test_boolish():
    s = pd.Series(["yes", "NO", " Pass ", "1", "x"])
    assert engine._boolish(s).tolist() == [True, False, True, True, False]


def test_assign_sleeve_thresholds():
    core = pd.Series({"conviction_score": 60, "screens_passed": 3})
    assert engine._assign_sleeve(core) == "CORE"
    mom = pd.Series({"conviction_score": 40, "screens_passed": 1, "scr_breakout": True})
    assert engine._assign_sleeve(mom) == "MOMENTUM"
    assert engine._assign_sleeve(pd.Series({"conviction_score": 10, "screens_passed": 1})) == "PASS"


def test_diversify_caps_sector():
    df = pd.DataFrame({"Symbol": list("ABCDE"), "Sector": ["X", "X", "X", "Y", "Z"]})
    out = engine.diversify(df, n=4, max_per_sector=2)
    assert out["Symbol"].tolist() == ["A", "B", "D", "E"]
    assert out["investor_rank"].tolist() == [1, 2, 3, 4]


def test_build_portfolio_equal_weight():
    picks = pd.DataFrame({"Symbol": ["A", "B"], "sleeve": ["CORE", "WATCH"], "LTP": [10.0, 20.0]})
    port = engine.build_portfolio(picks, size=10)
    assert port["Symbol"].tolist() == ["A"]
    assert port["weight"].iloc[0] == 1.0 and port["shares_per_100k"].iloc[0] == 10000.0


def test_find_latest_scan_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DEFAULT_SCAN_DIRS", [])
    with pytest.raises(FileNotFoundError):
        engine.find_latest_scan(tmp_path)


def test_df_records_nan_to_none():
    recs = _df_records(pd.DataFrame({"a": pd.Series([1, None], dtype=object)}))
    assert recs == [{"a": 1}, {"a": None}]


def test_write_outputs_files(tmp_path):
    res = engine.run_picks(scan_path=write_scan(tmp_path / "us_full_scan_20260101_0930.xlsx"))
    paths = write_outputs(res, tmp_path / "out")
    for name in ("us_investor_picks_latest.html", "us_quant_ranked_latest.csv", "us_picks_latest.json"):
        assert (tmp_path / "out" / name).exists()
    assert json.loads(paths["json"].read_text())["summary"]["as_of"] == "2026-01-01 09:30"


def test_cli_smoke(tmp_path, capsys):
    scan = write_scan(tmp_path / "us_full_scan_20260101_0930.xlsx")
    assert main(["--scan", str(scan), "--out", str(tmp_path / "o"), "--top", "5"]) == 0
    assert "Investor shortlist:" in capsys.readouterr().out


def test_cli_missing_scan_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DEFAULT_SCAN_DIRS", [])
    assert main(["--scan-dir", str(tmp_path), "--out", str(tmp_path / "o")]) == 1
