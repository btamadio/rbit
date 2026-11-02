"""Data-quality report for the cleaned tables.

    python -m rbit.data.quality [--out reports/data_quality_NSW1.md]
"""

import argparse
from pathlib import Path

import pandas as pd

from rbit.config import DataConfig
from rbit.data import store
from rbit.data.normalise import nominal_publish_time

INTERVALS_PER_DAY = 288
P5MIN_STEPS = 12
PREDISPATCH_RUNS_PER_DAY = 48
REVISION_LAG = pd.Timedelta(minutes=10)
MIN_COVERAGE = 0.999


def _month_of(interval_end: pd.Series) -> pd.Series:
    # an interval ending at 00:00 on the 1st belongs to the previous month
    return (interval_end - pd.Timedelta(minutes=5)).dt.to_period("M")


def dispatch_summary(price: pd.DataFrame) -> pd.DataFrame:
    p = price.assign(month=_month_of(price["interval_end"]))
    g = p.groupby("month")
    out = pd.DataFrame({
        "intervals": g.size(),
        "expected": [m.days_in_month * INTERVALS_PER_DAY for m in g.size().index],
        "intervention": g["intervention_flag"].sum(),
        "apc": g["apc_flag"].apply(lambda s: (s != 0).sum()),
        "suspended": g["market_suspended"].apply(lambda s: (s != 0).sum()),
        "not_firm": g["price_status"].apply(lambda s: (s != "FIRM").sum()),
        "rrp_min": g["rrp"].min(),
        "rrp_mean": g["rrp"].mean(),
        "rrp_max": g["rrp"].max(),
        "n_neg": g["rrp"].apply(lambda s: (s < 0).sum()),
        "n_gt300": g["rrp"].apply(lambda s: (s > 300).sum()),
        "n_gt5000": g["rrp"].apply(lambda s: (s > 5000).sum()),
        "n_ge10000": g["rrp"].apply(lambda s: (s >= 10000).sum()),
    })
    out["coverage"] = out["intervals"] / out["expected"]
    return out


def missing_intervals(price: pd.DataFrame) -> pd.DatetimeIndex:
    t = price["interval_end"]
    full = pd.date_range(t.min(), t.max(), freq="5min")
    return full.difference(pd.DatetimeIndex(t))


def p5min_summary(p5: pd.DataFrame) -> pd.DataFrame:
    runs = p5.groupby("run_datetime").agg(steps=("interval_end", "size"))
    runs["month"] = _month_of(runs.index.to_series())
    g = runs.groupby("month")
    out = pd.DataFrame({
        "runs": g.size(),
        "expected": [m.days_in_month * INTERVALS_PER_DAY for m in g.size().index],
        "short_runs": g["steps"].apply(lambda s: (s < P5MIN_STEPS).sum()),
    })
    out["coverage"] = out["runs"] / out["expected"]
    return out


def predispatch_summary(pdp: pd.DataFrame) -> pd.DataFrame:
    runs = pdp.groupby(["seqno", "runno"]).agg(run_datetime=("run_datetime", "first"), steps=("interval_end", "size"))
    runs["month"] = runs["run_datetime"].dt.to_period("M")
    g = runs.groupby("month")
    out = pd.DataFrame({
        "runs": g.size(),
        "expected": [m.days_in_month * PREDISPATCH_RUNS_PER_DAY for m in g.size().index],
        "min_steps": g["steps"].min(),
        "median_steps": g["steps"].median(),
    })
    out["coverage"] = out["runs"] / out["expected"]
    return out


def publish_lags(df: pd.DataFrame, table: str) -> tuple[pd.Series, pd.DataFrame]:
    """LASTCHANGED lag percentiles (seconds) and rows stamped long after nominal publication."""
    stamp = df["lastchanged"] if "run_datetime" not in df.columns else df["available_at"]
    lag = stamp - nominal_publish_time(df, table)
    q = (lag.dt.total_seconds().quantile([0.0, 0.5, 0.9, 0.99, 0.999, 1.0])).rename(table)
    late = df.loc[lag > REVISION_LAG].assign(lag=lag[lag > REVISION_LAG])
    return q, late


def _md(df: pd.DataFrame, floatfmt: str = "{:,.2f}") -> str:
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: floatfmt.format(v) if pd.notna(v) else "")
    d = d.reset_index()
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "|" + "---|" * len(d.columns)
    rows = ["| " + " | ".join(map(str, r)) + " |" for r in d.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def build_report(cfg: DataConfig) -> str:
    t = {name: store.load(cfg, name) for name in
         ["dispatch_price", "dispatch_regionsum", "p5min_region", "predispatch_price", "predispatch_regionsum"]}
    disp = dispatch_summary(t["dispatch_price"])
    p5 = p5min_summary(t["p5min_region"])
    pdp = predispatch_summary(t["predispatch_price"])
    missing = missing_intervals(t["dispatch_price"])
    lag_rows, late = [], {}
    for name, df in t.items():
        q, l = publish_lags(df, name)
        lag_rows.append(q)
        late[name] = l
    lags = pd.DataFrame(lag_rows)
    lags.columns = [f"p{c * 100:g}" for c in lags.columns]
    lags.index.name = "table"

    gaps = {k: v for k, v in store.missing_months(cfg).items() if v}
    # coverage checks only for months in the configured range that are not known archive gaps
    in_range = pd.period_range(cfg.start, cfg.end, freq="M")
    gap_months = {pd.Period(f"{m[:4]}-{m[4:]}", "M") for v in gaps.values() for m in v}
    pdp = pdp[pdp.index.isin(in_range) & ~pdp.index.isin(list(gap_months))]
    checks = {
        f"dispatch coverage >= {MIN_COVERAGE:.1%} every month": bool((disp["coverage"] >= MIN_COVERAGE).all()),
        f"P5MIN run coverage >= {MIN_COVERAGE:.1%} every month": bool((p5["coverage"] >= MIN_COVERAGE).all()),
        "PREDISPATCH run coverage >= 99% every month (excl. archive gaps)": bool((pdp["coverage"] >= 0.99).all()),
        "no negative publish lags (dispatch)": bool(lags.loc["dispatch_price", "p0"] >= 0),
        "dispatch_regionsum interval count matches dispatch_price":
            len(t["dispatch_regionsum"]) == len(t["dispatch_price"]),
    }
    checks["no table-months missing from the AEMO archive"] = not gaps
    first, last = t["dispatch_price"]["interval_end"].agg(["min", "max"])

    lines = [
        f"# Data-quality report: {cfg.region}",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.data.quality`. "
        f"Dispatch data from {first} to {last} (interval end, NEM time UTC+10).",
        "",
        "## Checks",
        "",
        *[f"- {'PASS' if ok else 'WARN'}: {name}" for name, ok in checks.items()],
        "",
        "## Table-months missing from the AEMO archive",
        "",
        *([f"- **{k}**: {', '.join(v)}" for k, v in gaps.items()] or ["- none"]),
        "",
        "InfoSet returns an empty path when the latest run is older than `max_p5min_age` /"
        " `max_predispatch_age`, so gaps are never filled with stale runs.",
        "",
        "## Notes",
        "",
        "- Five-minute settlement (5MS) started 1 Oct 2021; all data here is 5MS.",
        "- P5MIN/PREDISPATCH: `available_at` = max `LASTCHANGED` over the run (late runs are genuinely late).",
        "- Dispatch tables: `available_at` = min(`LASTCHANGED`, interval start + 60 s). The archive re-stamps"
        " `LASTCHANGED` on many dispatch rows without changing RRP (verified against real-time DispatchIS"
        " for 2026-03-24: 184 re-stamped NSW1 rows, 0 RRP differences). Such rows are flagged `restamped`."
        " Genuine revisions (e.g. June 2022 market suspension) are among the rows listed below and are"
        " treated as published on time: a small, known leak of revised past prices into history features.",
        "- Intervention: the INTERVENTION=0 (pricing run) row is kept; `intervention` counts intervals"
        " that also had an intervention run.",
        "- Market price cap differs by financial year, so spikes are summarised by fixed thresholds"
        " (> $300, > $5,000, >= $10,000/MWh).",
        "",
        "## Publish lag: LASTCHANGED minus nominal publish time (seconds)",
        "",
        "Nominal: dispatch = interval start; P5MIN = RUN_DATETIME - 5 min; PREDISPATCH = run time from"
        " PREDISPATCHSEQNO.",
        "",
        _md(lags, "{:,.0f}"),
        "",
        f"### Rows stamped more than {int(REVISION_LAG.total_seconds() // 60)} min after nominal (re-stamps or revisions)",
        "",
    ]
    for name, l in late.items():
        lines.append(f"- **{name}**: {len(l):,} rows")
        if len(l):
            ex = l.sort_values("lag", ascending=False).head(5)
            cols = [c for c in ["run_datetime", "interval_end", "available_at", "lag"] if c in ex.columns]
            lines += ["", _md(ex[cols].set_index(cols[0])), ""]
    lines += [
        "",
        "## Dispatch prices by month",
        "",
        _md(disp),
        "",
        f"### Missing dispatch intervals: {len(missing)}",
        "",
    ]
    if len(missing):
        lines += [f"- {ts}" for ts in missing[:50]] + (["- ..."] if len(missing) > 50 else [])
    lines += [
        "",
        "## P5MIN runs by month",
        "",
        _md(p5),
        "",
        "## PREDISPATCH runs by month",
        "",
        _md(pdp),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    cfg = DataConfig()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("reports") / f"data_quality_{cfg.region}.md")
    args = ap.parse_args(argv)
    report = build_report(cfg)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
