import json
import runpy
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from us_stock_picks import __main__ as cli
from us_stock_picks import engine as eng
from us_stock_picks import report as rep

from .test_engine import make_scan  # noqa: F401  (shared synthetic workbook)


# ---------- formatting helpers ----------
def test_esc():
    assert rep._esc(None) == "—" and rep._esc(float("nan")) == "—"
    assert rep._esc("<b>&") == "&lt;b&gt;&amp;"
    assert rep._esc(0) == "0" and rep._esc(1.5) == "1.5"


def test_money_pct_intish():
    assert rep._money(1234.5) == "$1,234.50" and rep._money("x") == "—" and rep._money(None) == "—"
    assert rep._pct(1.25) == "+1.2%" and rep._pct(-0.05) == "-0.1%" and rep._pct("x") == "—"
    assert rep._pct(0) == "+0.0%"
    assert rep._intish(8.0) == "8" and rep._intish("7") == "7" and rep._intish(np.nan) == "—"
    assert rep._intish("x") == "—" and rep._intish(None) == "—"


# ---------- fixtures ----------
@pytest.fixture
def result(tmp_path):
    p = make_scan(tmp_path)
    return eng.run_picks(scan_path=p, top=5, max_per_sector=2, portfolio_size=3)


def _empty_result(result):
    e = result.ranked.iloc[0:0]
    return eng.PickResult(as_of="2026-01-02 09:30", scan_path="x", universe_n=0, liquid_n=0, ranked=e,
                          investor_picks=e, portfolio=e, summary={"as_of": "2026-01-02 09:30"})


# ---------- render_html ----------
def test_render_html_content(result):
    h = rep.render_html(result)
    s = result.summary
    assert h.startswith("<!DOCTYPE html>") and "<title>US Stock Picks — 2026-01-02 09:30</title>" in h
    assert f'<div class="k">Universe</div><div class="v">{s["universe_n"]:,}</div>' in h
    assert f'<div class="k">Investor picks</div><div class="v">{len(result.investor_picks)}</div>' in h
    assert f'<div class="v">{s["avg_conviction_top"]:.1f}</div>' in h
    for sym in result.investor_picks["Symbol"]:
        assert f'<div class="sym">{sym}</div>' in h
    assert h.count('<td class="rank">') == len(result.investor_picks)
    assert "Not investment advice" in h and "Equal-weight paper portfolio" in h
    assert "No picks under current filters." not in h and "Empty portfolio." not in h
    assert "price ≥ $5.0" in h and "turnover ≥ $2,000,000/day" in h
    assert "T1_MOST_LIQUID, T2_LIQUID, T3_MID" in h
    assert f"top {min(100, len(result.ranked))} shown" in h
    assert "<strong>Tech</strong> — 2" in h        # sector mix
    assert "Generated 20" in h and " UTC · us-stock-picks" in h
    for k in s["sleeve_counts"]:
        assert f"<strong>{k}</strong>" in h


def test_sleeve_color_palette_is_fixed():
    assert rep.SLEEVE_COLORS == {"CORE": "#0f766e", "QUALITY": "#1d4ed8", "MOMENTUM": "#c2410c", "WATCH": "#6b7280"}


def test_render_html_sleeve_colors(result):
    h = rep.render_html(result)
    sleeves = set(result.investor_picks["sleeve"])
    for sl in sleeves:
        assert f'style="background:{rep.SLEEVE_COLORS[sl]}">{sl}</span>' in h
    pr = result.investor_picks.copy()
    pr.loc[pr.index[0], "sleeve"] = "OTHER"
    r2 = eng.PickResult(**{**result.__dict__, "investor_picks": pr})
    assert 'style="background:#374151">OTHER</span>' in rep.render_html(r2)


def test_render_html_empty(result):
    h = rep.render_html(_empty_result(result))
    assert "No picks under current filters." in h and "Empty portfolio." in h
    assert "<li>n/a</li>" in h and "sleeves in ranked set: —" in h.lower().replace("\n", " ").replace("  ", " ") or "—." in h
    assert '<div class="v">0</div>' in h


def test_render_html_escapes_untrusted_text(result):
    pr = result.investor_picks.copy()
    pr["Name"] = "<script>alert(1)</script>"
    r2 = eng.PickResult(**{**result.__dict__, "investor_picks": pr})
    h = rep.render_html(r2)
    assert "<script>alert(1)</script>" not in h and "&lt;script&gt;" in h


def test_render_html_prefers_investor_rank_over_rank(result):
    pr = result.investor_picks.copy()
    pr["investor_rank"] = 77
    r2 = eng.PickResult(**{**result.__dict__, "investor_picks": pr})
    assert '<td class="rank">77</td>' in rep.render_html(r2)
    pr2 = result.investor_picks.drop(columns=["investor_rank"])
    r3 = eng.PickResult(**{**result.__dict__, "investor_picks": pr2})
    assert f'<td class="rank">{int(pr2["rank"].iloc[0])}</td>' in rep.render_html(r3)


# ---------- _df_records ----------
def test_df_records_converts_values():
    assert rep._df_records(pd.DataFrame()) == []
    recs = rep._df_records(pd.DataFrame({"a": [np.int64(1), 2], "c": ["x", "y"]}))
    assert recs == [{"a": 1, "c": "x"}, {"a": 2, "c": "y"}]
    assert type(recs[0]["a"]) is int
    json.dumps(recs)


def test_df_records_unwraps_numpy_scalars_and_tolerates_bad_item(monkeypatch):
    class Bad:
        def item(self):
            raise RuntimeError

    bad = Bad()
    monkeypatch.setattr(pd.DataFrame, "to_dict", lambda self, orient: [{"a": np.float64(2.5), "b": bad}])
    rec = rep._df_records(pd.DataFrame({"a": [1]}))[0]
    assert rec["a"] == 2.5 and type(rec["a"]) is float and rec["b"] is bad


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="report.py _df_records: df.where(notna, None) leaves float NaN as NaN, so the JSON export "
                          "contains the non-standard literal NaN instead of null")
def test_df_records_nan_becomes_none():
    recs = rep._df_records(pd.DataFrame({"b": [np.nan, 1.5]}))
    assert recs == [{"b": None}, {"b": 1.5}]
    assert "NaN" not in json.dumps(recs)


# ---------- write_outputs ----------
def test_write_outputs_files(result, tmp_path):
    out = tmp_path / "o" / "nested"
    paths = rep.write_outputs(result, out)
    assert set(paths) == {"html", "html_latest", "csv", "picks_csv", "portfolio_csv", "json"}
    stamp = "2026-01-02_09"          # as_of is cut to 13 chars: hour granularity
    assert paths["html"].name == f"us_investor_picks_{stamp}.html"
    assert paths["csv"].name == f"us_quant_ranked_{stamp}.csv"
    assert paths["picks_csv"].name == f"us_investor_picks_{stamp}.csv"
    assert paths["portfolio_csv"].name == f"us_paper_portfolio_{stamp}.csv"
    assert paths["json"].name == f"us_picks_{stamp}.json"
    for name in ("us_investor_picks_latest.html", "us_quant_ranked_latest.csv", "us_investor_picks_latest.csv",
                 "us_paper_portfolio_latest.csv", "us_picks_latest.json"):
        assert (out / name).exists(), name
    assert (out / "us_investor_picks_latest.html").read_text(encoding="utf-8") == paths["html"].read_text(encoding="utf-8")
    q = pd.read_csv(paths["csv"])
    assert q["Symbol"].tolist() == result.ranked["Symbol"].tolist()
    assert "rank" in q.columns and "thesis" in q.columns
    inv = pd.read_csv(paths["picks_csv"])
    assert inv["investor_rank"].tolist() == list(range(1, len(result.investor_picks) + 1))
    assert "weight" not in inv.columns
    port = pd.read_csv(paths["portfolio_csv"])
    assert len(port) == len(result.portfolio) and "weight" in port.columns


def test_write_outputs_json_payload(result, tmp_path):
    paths = rep.write_outputs(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["summary"]["universe_n"] == result.universe_n
    assert len(payload["investor_picks"]) == len(result.investor_picks)
    assert len(payload["portfolio"]) == len(result.portfolio)
    assert len(payload["quant_ranked"]) == len(result.ranked)
    assert "Not investment advice" in payload["disclaimer"]
    assert json.loads((tmp_path / "us_picks_latest.json").read_text(encoding="utf-8")) == payload
    for f in (paths["json"], tmp_path / "us_picks_latest.json"):
        assert f.read_text(encoding="utf-8").startswith('{\n  "summary": {\n    "as_of"')   # indent=2


def test_write_outputs_empty_portfolio_skips_portfolio_csv(result, tmp_path):
    paths = rep.write_outputs(_empty_result(result), tmp_path)
    assert "portfolio_csv" not in paths and not list(tmp_path.glob("us_paper_portfolio_*"))


def test_write_outputs_stamp_sanitised(result, tmp_path):
    r2 = eng.PickResult(**{**result.__dict__, "as_of": "2026-01-02 09:30:15"})
    assert rep.write_outputs(r2, tmp_path)["html"].name == "us_investor_picks_2026-01-02_09.html"


# ---------- CLI ----------
def test_parser_defaults():
    a = cli.build_parser().parse_args([])
    assert (a.scan, a.scan_dir, a.top, a.max_per_sector, a.portfolio_size) == (None, None, 15, 3, 10)
    assert (a.min_price, a.min_turnover, a.workers) == (5.0, 2_000_000.0, 8)
    assert a.refresh is False and a.refresh_top is None and a.open is False
    assert a.out == cli.cfg.DEFAULT_OUTPUT_DIR
    b = cli.build_parser().parse_args(["--top", "3", "--refresh", "--refresh-top", "50", "--open", "--workers", "2",
                                       "--scan", "x.xlsx", "--min-price", "1.5"])
    assert (b.top, b.refresh, b.refresh_top, b.open, b.workers, b.scan, b.min_price) == (
        3, True, 50, True, 2, Path("x.xlsx"), 1.5)


def test_main_success_prints_and_writes(tmp_path, capsys):
    p = make_scan(tmp_path)
    out = tmp_path / "out"
    rc = cli.main(["--scan", str(p), "--out", str(out), "--top", "4", "--max-per-sector", "2",
                   "--portfolio-size", "2"])
    text = capsys.readouterr().out
    assert rc == 0
    assert "US Stock Picks" in text and "  as of:     2026-01-02 09:30" in text
    assert "  universe:  14" in text and "  liquid:    13" in text
    assert "Investor shortlist:" in text and "investor_rank" in text and "Outputs:" in text
    assert (out / "us_picks_latest.json").exists()
    inv = json.loads((out / "us_picks_latest.json").read_text())["investor_picks"]
    assert len(inv) == 4 and len(json.loads((out / "us_picks_latest.json").read_text())["portfolio"]) == 2


def test_main_missing_scan_returns_1(tmp_path, capsys):
    rc = cli.main(["--scan-dir", str(tmp_path), "--out", str(tmp_path / "o")])
    cap = capsys.readouterr()
    assert rc == 1 and cap.err.startswith("ERROR: No US scan workbooks") and cap.out == ""


def test_main_other_error_returns_2(tmp_path, capsys):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not an excel file")
    rc = cli.main(["--scan", str(bad), "--out", str(tmp_path / "o")])
    assert rc == 2 and capsys.readouterr().err.startswith("ERROR: ")
    assert not (tmp_path / "o").exists()


def test_main_empty_shortlist_message(tmp_path, capsys, monkeypatch, result):
    empty = _empty_result(result)
    monkeypatch.setattr(cli, "run_picks", lambda **kw: empty)
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {})
    assert cli.main([]) == 0
    assert "(none — relax filters or refresh scan)" in capsys.readouterr().out


def test_main_open_flag(tmp_path, monkeypatch, result):
    calls = []
    monkeypatch.setattr(cli, "run_picks", lambda **kw: result)
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {"html_latest": Path("/x/latest.html")})
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    cli.main(["--open"])
    assert calls == [(["open", "/x/latest.html"], False)]
    calls.clear()
    cli.main([])
    assert calls == []
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {})
    cli.main(["--open"])
    assert calls == []          # no html_latest -> nothing to open


def test_main_open_swallows_errors(monkeypatch, result):
    monkeypatch.setattr(cli, "run_picks", lambda **kw: result)
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {"html_latest": Path("x")})

    def boom(cmd, check):
        raise OSError

    monkeypatch.setattr(cli.subprocess, "run", boom)
    assert cli.main(["--open"]) == 0


def test_main_passes_arguments_through(monkeypatch, result):
    seen = {}
    monkeypatch.setattr(cli, "run_picks", lambda **kw: (seen.update(kw), result)[1])
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {})
    cli.main(["--top", "7", "--max-per-sector", "1", "--portfolio-size", "4", "--min-price", "9",
              "--min-turnover", "123", "--scan-dir", "d"])
    assert seen == {"scan_path": None, "scan_dir": Path("d"), "min_price": 9.0, "min_turnover": 123.0,
                    "top": 7, "max_per_sector": 1, "portfolio_size": 4}


# ---------- refresh ----------
def test_maybe_refresh_script_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    assert cli._maybe_refresh(None, 8) is None
    assert "Refresh skipped — scan script not found" in capsys.readouterr().err


def _fake_home(tmp_path, monkeypatch):
    sd = tmp_path / "market-pipeline" / "code" / "python_files"
    sd.mkdir(parents=True)
    (sd / "full_us_market_scan.py").write_text("")
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    return sd


def test_maybe_refresh_runs_script_and_finds_workbook(tmp_path, monkeypatch, capsys):
    sd = _fake_home(tmp_path, monkeypatch)
    wb = sd / "us_full_scan" / "us_full_scan_20260102.xlsx"
    wb.parent.mkdir()
    wb.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd, check: calls.append((cmd, cwd, check)))
    assert cli._maybe_refresh(500, 3) == wb
    cmd, cwd, check = calls[0]
    assert cmd == [sys.executable, str(sd / "full_us_market_scan.py"), "--workers", "3", "--top", "500"]
    assert cwd == str(sd) and check is False
    calls.clear()
    cli._maybe_refresh(None, 8)
    assert "--top" not in calls[0][0]


def test_maybe_refresh_no_workbook_after_run(tmp_path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    assert cli._maybe_refresh(None, 1) is None


def test_main_refresh_overrides_scan_path(tmp_path, monkeypatch, result):
    seen = {}
    monkeypatch.setattr(cli, "_maybe_refresh", lambda top, workers: (seen.update(top=top, w=workers), Path("new.xlsx"))[1])
    monkeypatch.setattr(cli, "run_picks", lambda **kw: (seen.update(scan=kw["scan_path"]), result)[1])
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {})
    cli.main(["--refresh", "--refresh-top", "9", "--workers", "5", "--scan", "old.xlsx"])
    assert seen == {"top": 9, "w": 5, "scan": Path("new.xlsx")}
    seen.clear()
    monkeypatch.setattr(cli, "_maybe_refresh", lambda top, workers: None)
    cli.main(["--refresh", "--scan", "old.xlsx"])
    assert seen["scan"] == Path("old.xlsx")        # failed refresh keeps the user's --scan


def test_main_no_refresh_does_not_call_it(monkeypatch, result):
    monkeypatch.setattr(cli, "_maybe_refresh", lambda *a: pytest.fail("refresh called"))
    monkeypatch.setattr(cli, "run_picks", lambda **kw: result)
    monkeypatch.setattr(cli, "write_outputs", lambda r, o: {})
    cli.main([])


# ---------- entry points ----------
def test_run_us_picks_launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["run_us_picks.py", "--scan-dir", str(tmp_path), "--out", str(tmp_path / "o")])
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(root / "run_us_picks.py"), run_name="__main__")
    assert e.value.code == 1


def test_module_main_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["x", "--scan-dir", str(tmp_path), "--out", str(tmp_path / "o")])
    sys.modules.pop("us_stock_picks.__main__", None)
    with pytest.raises(SystemExit) as e:
        runpy.run_module("us_stock_picks", run_name="__main__")
    assert e.value.code == 1


def test_package_exports():
    import us_stock_picks
    assert us_stock_picks.__version__ == "1.0.0"
    assert set(us_stock_picks.__all__) == {"PickResult", "find_latest_scan", "run_picks"}
