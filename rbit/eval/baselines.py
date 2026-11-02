"""Baseline benchmarks B1 and B2 (milestone M3), reported against B3/B4 from M2.

    python -m rbit.eval.baselines [--years 2022 2023 2024 2025]

B1 is tuned on the training years (2022-2023, PLAN.md section 4), so its 2022-2023 figures are in-sample.
Writes reports/m3_baselines.{md,csv}.
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from rbit.baselines import B2_HORIZON, run_predispatch_mpc, simulate, tod_schedule, tune_tod
from rbit.config import BatteryConfig, DataConfig
from rbit.data.infoset import InfoSet
from rbit.eval.perfect_foresight import metrics, year_prices
from rbit.market.mlf import load_registration, mlf_schedule, mlf_series

TRAIN_YEARS = [2022, 2023]


def _year(data_cfg: DataConfig, schedule: pd.DataFrame, year: int):
    rrp, ends, n = year_prices(data_cfg, year)
    m = mlf_series(schedule, ends)
    return rrp, pd.DatetimeIndex(ends), n, m.gen, m.load


def run_b2(year: int, data_cfg: DataConfig, schedule: pd.DataFrame) -> dict:
    cfg = BatteryConfig()
    rrp, ends, n, gen, load = _year(data_cfg, schedule, year)
    info = InfoSet.from_store(data_cfg, ends[0], ends[-1])
    t0 = time.time()
    mw, stats = run_predispatch_mpc(cfg, info, ends[:n], gen, load, B2_HORIZON)
    return ({"benchmark": "B2", "year": year} | metrics(cfg, rrp[:n], mw, gen[:n], load[:n]) | stats
            | {"seconds": round(time.time() - t0, 1)})


def _k(x: float) -> str:
    return f"{x / 1000:,.0f}k"


def build_report(df: pd.DataFrame, tod: tuple[int, int]) -> str:
    rev = df.pivot(index="year", columns="benchmark", values="revenue_per_mw")
    cyc = df.pivot(index="year", columns="benchmark", values="cycles_per_day")
    pad = df[df["benchmark"] == "B2"].set_index("year")["n_padded"]
    rows = [f"| {y} | {_k(r.B1)} | {_k(r.B2)} | {_k(r.B3)} | {_k(r.B4)} | {r.B1 / r.B3:.0%} | **{r.B2 / r.B3:.0%}** | "
            f"{cyc.loc[y, 'B1']:.2f} | {cyc.loc[y, 'B2']:.2f} | {int(pad.loc[y]):,} |" for y, r in rev.iterrows()]
    return "\n".join([
        "# M3: baselines (NSW1, 2 h, energy only, Riverina 1 MLFs)",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.eval.baselines`. Gross energy revenue,",
        "$/MW/yr, same asset and settlement as M2 (`BatteryConfig()` defaults).",
        "",
        f"- **B1** time-of-day rule: charge from {tod[0]:02d}:00 and discharge from {tod[1]:02d}:00 for",
        f"  {BatteryConfig().duration_h:g} h at full power; tuned on {TRAIN_YEARS[0]}–{TRAIN_YEARS[-1]} (in-sample there).",
        f"- **B2** pre-dispatch MPC: {B2_HORIZON * 5 / 60:g} h rolling LP on P5MIN then PREDISPATCH prices as published,",
        "  read through InfoSet (decision 1 min before the dispatch run), first action executed, settled at actual RRP.",
        "- **B3 / B4** from `reports/m2_perfect_foresight.csv` (perfect foresight).",
        "",
        "| Year | B1 | B2 | B3 | B4 | B1 / B3 | B2 / B3 | B1 cycles/day | B2 cycles/day | B2 padded steps |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Padded steps: decisions where pre-dispatch did not cover the horizon and the last price was held",
        "(archive gap: PREDISPATCH 2022-10).",
        "",
    ])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024, 2025])
    ap.add_argument("--perfect-foresight", type=Path, default=Path("reports") / "m2_perfect_foresight.csv")
    ap.add_argument("--out", type=Path, default=Path("reports") / "m3_baselines")
    args = ap.parse_args(argv)
    data_cfg, cfg = DataConfig(), BatteryConfig()
    schedule = mlf_schedule(load_registration(data_cfg), cfg.mlf_station)

    with ProcessPoolExecutor(max_workers=len(args.years)) as pool:
        b2 = pool.map(run_b2, args.years, [data_cfg] * len(args.years), [schedule] * len(args.years))
        years = {y: _year(data_cfg, schedule, y) for y in sorted(set(args.years) | set(TRAIN_YEARS))}
        tod = tune_tod(cfg, [(r[:n], e[:n], g[:n], ld[:n]) for r, e, n, g, ld in (years[y] for y in TRAIN_YEARS)])
        rows = []
        for y in args.years:
            rrp, ends, n, gen, load = years[y]
            mw, _ = simulate(cfg, tod_schedule(cfg, ends[:n], *tod))
            rows.append({"benchmark": "B1", "year": y} | metrics(cfg, rrp[:n], mw, gen[:n], load[:n]))
        rows += list(b2)

    pf = pd.read_csv(args.perfect_foresight)
    pf = pf[(pf["label"] == "base") & (pf["duration_h"] == cfg.duration_h) & pf["year"].isin(args.years)]
    df = pd.concat([pd.DataFrame(rows), pf[["benchmark", "year", "revenue_per_mw", "net_per_mw", "cycles_per_day"]]],
                   ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_suffix(".md").write_text(build_report(df, tod))
    print(f"wrote {args.out.with_suffix('.md')} (B1 charge {tod[0]}h, discharge {tod[1]}h)")


if __name__ == "__main__":
    main()
