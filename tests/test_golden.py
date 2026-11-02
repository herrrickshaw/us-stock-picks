"""Characterisation test: output of the pre-refactor engine on the synthetic scan."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.scan_fixture import write_scan
from us_stock_picks.engine import run_picks

GOLDEN = json.loads((Path(__file__).parent / "golden" / "expected.json").read_text())


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    path = write_scan(tmp_path_factory.mktemp("scan") / "us_full_scan_20260101_0930.xlsx")
    return run_picks(scan_path=path)


def test_summary(result):
    got = {k: v for k, v in result.summary.items() if k != "scan_path"}
    assert got == GOLDEN["summary"]


def test_investor_picks(result):
    cols = ["Symbol", "sleeve", "conviction_score", "screens_passed", "investor_rank"]
    assert result.investor_picks[cols].to_dict("records") == GOLDEN["investor"]


def test_ranked_order_and_scores(result):
    assert list(result.ranked["Symbol"]) == GOLDEN["ranked_syms"]
    assert [float(x) for x in result.ranked["conviction_score"]] == GOLDEN["ranked_scores"]


def test_portfolio(result):
    cols = ["Symbol", "weight", "notional_per_100k", "shares_per_100k"]
    assert result.portfolio[cols].to_dict("records") == GOLDEN["portfolio"]


def test_theses(result):
    assert list(result.ranked["thesis"].head(5)) == GOLDEN["theses"]
