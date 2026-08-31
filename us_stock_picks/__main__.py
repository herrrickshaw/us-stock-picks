"""CLI: python -m us_stock_picks"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import config as cfg
from .engine import find_latest_scan, run_picks
from .report import write_outputs


def _maybe_refresh(top: int | None, workers: int) -> Path | None:
    """Optionally run full_us_market_scan.py and return newest workbook path."""
    scan_script = Path.home() / "market-pipeline" / "code" / "python_files" / "full_us_market_scan.py"
    if not scan_script.exists():
        print(f"Refresh skipped — scan script not found: {scan_script}", file=sys.stderr)
        return None

    cmd = [sys.executable, str(scan_script), "--workers", str(workers)]
    if top:
        cmd.extend(["--top", str(top)])
    print("Refreshing US market scan (this can take a long time)…")
    print(" ", " ".join(cmd))
    subprocess.run(cmd, cwd=str(scan_script.parent), check=False)
    try:
        return find_latest_scan(scan_script.parent / "us_full_scan")
    except FileNotFoundError:
        return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="us_stock_picks",
        description=(
            "US stock picks product: multi-screen conviction ranking "
            "(Darvas / Piotroski / Coffee Can / Magic Formula / momentum / ML) "
            "with investor HTML shortlist and quant CSV/JSON exports."
        ),
    )
    p.add_argument("--scan", type=Path, help="path to us_full_scan_*.xlsx (default: latest)")
    p.add_argument("--scan-dir", type=Path, help="directory to search for scan workbooks")
    p.add_argument(
        "--out",
        type=Path,
        default=cfg.DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {cfg.DEFAULT_OUTPUT_DIR})",
    )
    p.add_argument("--top", type=int, default=cfg.TOP_INVESTOR_PICKS, help="investor shortlist size")
    p.add_argument(
        "--max-per-sector",
        type=int,
        default=cfg.MAX_PER_SECTOR,
        help="sector cap for investor shortlist",
    )
    p.add_argument(
        "--portfolio-size",
        type=int,
        default=cfg.EQUAL_WEIGHT_PORTFOLIO_SIZE,
        help="equal-weight paper portfolio size",
    )
    p.add_argument("--min-price", type=float, default=cfg.MIN_PRICE)
    p.add_argument(
        "--min-turnover",
        type=float,
        default=cfg.MIN_TURNOVER_USD,
        help="minimum median daily turnover in USD",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="run full_us_market_scan.py first (slow; network)",
    )
    p.add_argument(
        "--refresh-top",
        type=int,
        default=None,
        help="with --refresh, limit universe size (e.g. 500 for a smoke run)",
    )
    p.add_argument("--workers", type=int, default=8, help="workers for --refresh fundamentals")
    p.add_argument("--open", action="store_true", help="open HTML report after build (macOS)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    scan_path = args.scan
    if args.refresh:
        refreshed = _maybe_refresh(args.refresh_top, args.workers)
        if refreshed is not None:
            scan_path = refreshed

    try:
        result = run_picks(
            scan_path=scan_path,
            scan_dir=args.scan_dir,
            min_price=args.min_price,
            min_turnover=args.min_turnover,
            top=args.top,
            max_per_sector=args.max_per_sector,
            portfolio_size=args.portfolio_size,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    paths = write_outputs(result, args.out)

    print("US Stock Picks")
    print(f"  as of:     {result.as_of}")
    print(f"  scan:      {result.scan_path}")
    print(f"  universe:  {result.universe_n:,}")
    print(f"  liquid:    {result.liquid_n:,}")
    print(f"  ranked:    {len(result.ranked):,}")
    print(f"  sleeves:   {result.summary.get('sleeve_counts')}")
    print()
    print("Investor shortlist:")
    show = result.investor_picks
    cols = [c for c in ("investor_rank", "Symbol", "sleeve", "conviction_score", "screens_passed", "Sector", "LTP") if c in show.columns]
    if not show.empty:
        print(show[cols].to_string(index=False))
    else:
        print("  (none — relax filters or refresh scan)")
    print()
    print("Outputs:")
    for k, path in paths.items():
        print(f"  {k:14s} {path}")

    if args.open and "html_latest" in paths:
        try:
            subprocess.run(["open", str(paths["html_latest"])], check=False)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
