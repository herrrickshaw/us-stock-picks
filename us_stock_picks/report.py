"""HTML investor report + CSV/JSON quant exports."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .engine import PickResult, quant_frame


def _esc(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return html.escape(str(v))


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _pct(v: Any) -> str:
    try:
        return f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _intish(v: Any) -> str:
    try:
        if pd.isna(v):
            return "—"
        return str(int(float(v)))
    except (TypeError, ValueError):
        return "—"


SLEEVE_COLORS = {
    "CORE": "#0f766e",
    "QUALITY": "#1d4ed8",
    "MOMENTUM": "#c2410c",
    "WATCH": "#6b7280",
}


def render_html(result: PickResult) -> str:
    s = result.summary
    picks = result.investor_picks
    port = result.portfolio
    ranked = result.ranked

    sleeve_bits = s.get("sleeve_counts") or {}
    sleeve_html = " · ".join(f"<strong>{k}</strong> {v}" for k, v in sleeve_bits.items()) or "—"

    rows_html = []
    for _, r in picks.iterrows():
        sleeve = str(r.get("sleeve") or "")
        color = SLEEVE_COLORS.get(sleeve, "#374151")
        rows_html.append(
            f"""
            <tr>
              <td class="rank">{_esc(r.get('investor_rank', r.get('rank')))}</td>
              <td>
                <div class="sym">{_esc(r.get('Symbol'))}</div>
                <div class="name">{_esc(r.get('Name') or '')}</div>
              </td>
              <td><span class="badge" style="background:{color}">{_esc(sleeve)}</span></td>
              <td class="num">{_esc(r.get('conviction_score'))}</td>
              <td class="num">{_esc(r.get('screens_passed'))}</td>
              <td>{_esc(r.get('Sector'))}</td>
              <td class="num">{_money(r.get('LTP'))}</td>
              <td class="num">{_pct(r.get('Change%'))}</td>
              <td class="num">{_intish(r.get('Piotroski_Score'))}</td>
              <td>{_esc(r.get('Quality_Grade'))}</td>
              <td class="thesis">{_esc(r.get('thesis'))}</td>
            </tr>
            """
        )

    port_rows = []
    for _, r in port.iterrows():
        port_rows.append(
            f"""
            <tr>
              <td>{_esc(r.get('Symbol'))}</td>
              <td>{_esc(r.get('sleeve'))}</td>
              <td class="num">{_esc(r.get('weight'))}</td>
              <td class="num">{_money(r.get('notional_per_100k'))}</td>
              <td class="num">{_esc(r.get('shares_per_100k'))}</td>
              <td class="num">{_money(r.get('LTP'))}</td>
            </tr>
            """
        )

    # Sector mix of investor picks
    sector_mix = ""
    if not picks.empty and "Sector" in picks.columns:
        counts = picks["Sector"].fillna("Unknown").value_counts()
        sector_mix = "".join(
            f"<li><strong>{_esc(k)}</strong> — {int(v)}</li>" for k, v in counts.items()
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>US Stock Picks — { _esc(s.get('as_of')) }</title>
<style>
  :root {{
    --bg: #0b1220;
    --card: #121a2b;
    --text: #e8eefc;
    --muted: #9aa8c7;
    --line: #243049;
    --accent: #38bdf8;
    --good: #34d399;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1e293b 0%, var(--bg) 55%);
    color: var(--text); line-height: 1.45;
  }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 28px 18px 60px; }}
  h1 {{ font-size: 1.8rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 1.15rem; margin: 28px 0 12px; color: var(--accent); }}
  .sub {{ color: var(--muted); margin-bottom: 18px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
  .card {{
    background: linear-gradient(180deg, #152038, var(--card));
    border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px;
  }}
  .card .k {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card .v {{ font-size: 1.35rem; font-weight: 700; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; }}
  th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .rank {{ font-weight: 700; color: var(--accent); }}
  .sym {{ font-weight: 700; font-size: 1rem; }}
  .name {{ color: var(--muted); font-size: 0.78rem; }}
  .badge {{
    display: inline-block; color: white; font-size: 0.72rem; font-weight: 700;
    padding: 3px 8px; border-radius: 999px; letter-spacing: 0.03em;
  }}
  .thesis {{ color: #c9d4ef; font-size: 0.84rem; max-width: 420px; }}
  .note {{
    background: #172033; border-left: 3px solid var(--accent);
    padding: 12px 14px; border-radius: 8px; color: var(--muted); margin: 16px 0;
  }}
  .warn {{
    background: #2a1a12; border-left: 3px solid #f59e0b;
    padding: 12px 14px; border-radius: 8px; color: #fcd34d; margin: 16px 0;
  }}
  ul {{ margin: 8px 0 0 18px; color: var(--muted); }}
  footer {{ margin-top: 28px; color: var(--muted); font-size: 0.8rem; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; background: var(--card); }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>US Stock Picks</h1>
    <p class="sub">Investor shortlist + quant multi-screen ranking · scan as of <strong>{_esc(s.get('as_of'))}</strong></p>

    <div class="grid">
      <div class="card"><div class="k">Universe</div><div class="v">{s.get('universe_n', 0):,}</div></div>
      <div class="card"><div class="k">Passed liquidity gate</div><div class="v">{s.get('liquid_n', 0):,}</div></div>
      <div class="card"><div class="k">Ranked signals</div><div class="v">{s.get('ranked_n', 0):,}</div></div>
      <div class="card"><div class="k">Investor picks</div><div class="v">{len(picks)}</div></div>
      <div class="card"><div class="k">Avg conviction (top)</div><div class="v">{s.get('avg_conviction_top', 0):.1f}</div></div>
    </div>

    <div class="note">
      <strong>How this works.</strong> We fuse Darvas breakouts, Piotroski quality, Coffee Can,
      Magic Formula, Bull Cartel, golden-cross momentum, breakout-quality grades, and a clipped ML
      bullish flag. Illiquid names are gated out so picks are tradeable. CORE = multi-screen agreement.
      Sleeves in ranked set: {sleeve_html}.
    </div>

    <div class="warn">
      <strong>Not investment advice.</strong> Screens are mechanical filters on historical/public data.
      Past patterns do not guarantee future returns. Size positions for your risk, costs, and taxes.
      Prefer paper-tracking before capital.
    </div>

    <h2>Investor shortlist (sector-capped)</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Ticker</th><th>Sleeve</th><th>Score</th><th>Screens</th>
            <th>Sector</th><th>Price</th><th>Day</th><th>F</th><th>Q</th><th>Thesis</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html) if rows_html else '<tr><td colspan="11">No picks under current filters.</td></tr>'}
        </tbody>
      </table>
    </div>

    <h2>Equal-weight paper portfolio (per $100k)</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Symbol</th><th>Sleeve</th><th>Weight</th><th>Notional</th><th>Shares</th><th>Price</th></tr>
        </thead>
        <tbody>
          {''.join(port_rows) if port_rows else '<tr><td colspan="6">Empty portfolio.</td></tr>'}
        </tbody>
      </table>
    </div>

    <h2>Sector mix (shortlist)</h2>
    <ul>{sector_mix or '<li>n/a</li>'}</ul>

    <h2>Quant notes</h2>
    <ul>
      <li>Full ranked table exported as CSV/JSON for research (top {min(100, len(ranked))} shown in quant files).</li>
      <li>Liquidity filter: price ≥ ${s.get('filters', {}).get('min_price', 5)},
          turnover ≥ ${s.get('filters', {}).get('min_turnover_usd', 0):,.0f}/day,
          tiers {', '.join(s.get('filters', {}).get('allowed_tiers', []))}.</li>
      <li>Source scan: <code>{_esc(s.get('scan_path'))}</code></li>
      <li>ML forecasts with extreme predicted returns are ignored; treat ML as a soft overlay only.</li>
    </ul>

    <footer>Generated {generated} · us-stock-picks</footer>
  </div>
</body>
</html>
"""


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    clean = df.where(pd.notna(df), None)
    # numpy types → python
    records = clean.to_dict(orient="records")
    out: list[dict[str, Any]] = []
    for rec in records:
        row: dict[str, Any] = {}
        for k, v in rec.items():
            if hasattr(v, "item"):
                try:
                    v = v.item()
                except Exception:
                    pass
            row[k] = v
        out.append(row)
    return out


def write_outputs(result: PickResult, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = result.as_of.replace(":", "").replace(" ", "_")[:13]
    paths: dict[str, Path] = {}

    html_path = out_dir / f"us_investor_picks_{stamp}.html"
    html_path.write_text(render_html(result), encoding="utf-8")
    paths["html"] = html_path
    # stable alias
    latest_html = out_dir / "us_investor_picks_latest.html"
    latest_html.write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")
    paths["html_latest"] = latest_html

    q = quant_frame(result.ranked)
    csv_path = out_dir / f"us_quant_ranked_{stamp}.csv"
    q.to_csv(csv_path, index=False)
    paths["csv"] = csv_path
    q.to_csv(out_dir / "us_quant_ranked_latest.csv", index=False)

    picks_csv = out_dir / f"us_investor_picks_{stamp}.csv"
    inv_cols = [c for c in q.columns if c in result.investor_picks.columns] + [
        c for c in ("investor_rank", "thesis", "weight", "notional_per_100k", "shares_per_100k")
        if c in result.investor_picks.columns
    ]
    # unique preserve order
    seen = set()
    inv_cols = [c for c in inv_cols if not (c in seen or seen.add(c))]
    inv = result.investor_picks[[c for c in inv_cols if c in result.investor_picks.columns]]
    inv.to_csv(picks_csv, index=False)
    paths["picks_csv"] = picks_csv
    inv.to_csv(out_dir / "us_investor_picks_latest.csv", index=False)

    if not result.portfolio.empty:
        port_path = out_dir / f"us_paper_portfolio_{stamp}.csv"
        result.portfolio.to_csv(port_path, index=False)
        paths["portfolio_csv"] = port_path
        result.portfolio.to_csv(out_dir / "us_paper_portfolio_latest.csv", index=False)

    payload = {
        "summary": result.summary,
        "investor_picks": _df_records(result.investor_picks),
        "portfolio": _df_records(result.portfolio),
        "quant_ranked": _df_records(q),
        "disclaimer": (
            "Mechanical screen output for research only. Not investment advice. "
            "Past performance does not guarantee future results."
        ),
    }
    json_path = out_dir / f"us_picks_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    paths["json"] = json_path
    (out_dir / "us_picks_latest.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return paths
