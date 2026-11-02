"""Perfect-foresight benchmarks (milestone M2).

B4: full-horizon LP over the calendar year (terminal SoC >= initial SoC).
B3: rolling MPC on actual prices with a finite horizon (default 24 h), first action executed.

    python -m rbit.eval.perfect_foresight [--years 2022 2023 2024 2025] [--durations 1 2 4]

Writes reports/m2_perfect_foresight.{md,csv}. Prices here are settled actuals: this is an
oracle benchmark and deliberately bypasses InfoSet.
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from rbit.battery import simulate
from rbit.config import INTERVAL_H, BatteryConfig, DataConfig
from rbit.data import store
from rbit.market import settle
from rbit.market.mlf import load_registration, mlf_schedule, mlf_series
from rbit.optim import run_mpc, solve_schedule

INDUSTRY_CLAIM = 217_000  # $/MW/yr, PortfolioEnergy, NSW 2 h, 2025, includes FCAS (PLAN.md section 7)


@dataclass(frozen=True)
class Job:
    benchmark: str  # B3 | B4
    year: int
    duration_h: float
    horizon_h: float = 24.0  # B3 only
    degradation_cost: float = BatteryConfig().degradation_cost
    rte: float = BatteryConfig().rte
    mlf_station: str | None = "RESS1"
    label: str = "base"


def year_prices(data_cfg: DataConfig, year: int,
                lookahead: pd.Timedelta = pd.Timedelta(days=3)) -> tuple[np.ndarray, pd.Series, int]:
    """Actual RRP for intervals starting in ``year`` plus a lookahead tail; returns (rrp, interval_end, n_in_year)."""
    start = pd.Timestamp(year, 1, 1) + pd.Timedelta(minutes=5)  # first interval_end of the year
    end = pd.Timestamp(year + 1, 1, 1) + pd.Timedelta(minutes=5)
    df = store.load(data_cfg, "dispatch_price", start, end + lookahead)
    n = int((df["interval_end"] < end).sum())
    expected = int((end - start) / pd.Timedelta(minutes=5))
    if n != expected:
        raise ValueError(f"{year}: {n} intervals, expected {expected}")
    return df["rrp"].to_numpy(), df["interval_end"], n


def metrics(cfg: BatteryConfig, rrp: np.ndarray, mw: np.ndarray, gen=None, load=None) -> dict[str, float]:
    s = settle(cfg, rrp, mw, gen, load)
    days = len(rrp) * INTERVAL_H / 24
    dis = np.maximum(mw, 0) * INTERVAL_H
    chg = np.maximum(-mw, 0) * INTERVAL_H
    return {
        "revenue_per_mw": s.revenue.sum() / cfg.power_mw,
        "net_per_mw": s.net.sum() / cfg.power_mw,
        "cycles_per_day": dis.sum() / cfg.energy_mwh / days,
        "avg_discharge_price": float((rrp * dis).sum() / dis.sum()) if dis.sum() else np.nan,
        "avg_charge_price": float((rrp * chg).sum() / chg.sum()) if chg.sum() else np.nan,
    }


def run_job(job: Job, data_cfg: DataConfig, mlf_schedules: dict[str, pd.DataFrame]) -> dict:
    cfg = BatteryConfig(duration_h=job.duration_h, degradation_cost=job.degradation_cost, rte=job.rte,
                        mlf_station=job.mlf_station)
    rrp_ext, ends, n = year_prices(data_cfg, job.year)
    rrp = rrp_ext[:n]
    gen_ext = load_ext = None
    mlf_info = {"mlf_gen_mean": cfg.mlf_gen, "mlf_load_mean": cfg.mlf_load, "mlf_backfilled_share": 0.0}
    if cfg.mlf_station is not None:
        m = mlf_series(mlf_schedules[cfg.mlf_station], ends)
        gen_ext, load_ext = m.gen, m.load
        mlf_info = {"mlf_gen_mean": m.gen[:n].mean(), "mlf_load_mean": m.load[:n].mean(),
                    "mlf_backfilled_share": m.backfilled[:n].mean()}
    gen, load = (None, None) if gen_ext is None else (gen_ext[:n], load_ext[:n])
    t0 = time.time()
    if job.benchmark == "B4":
        sched = solve_schedule(cfg, rrp, terminal_min=cfg.e_init, mlf_gen=gen, mlf_load=load)
        mw, _ = simulate(cfg, sched.mw)
        extra = {"lp_objective_per_mw": sched.objective / cfg.power_mw, "n_binary": sched.n_binary}
    else:
        horizon = int(round(job.horizon_h * 12))
        mw, _, extra = run_mpc(cfg, rrp_ext, n, horizon, mlf_gen=gen_ext, mlf_load=load_ext)
    return (asdict(job) | metrics(cfg, rrp, mw, gen, load) | mlf_info | extra
            | {"seconds": round(time.time() - t0, 1)})


def default_jobs(years: list[int], durations: list[float]) -> list[Job]:
    jobs = [Job(b, y, d) for y in years for d in durations for b in ("B4", "B3")]
    last = max(years)
    jobs += [Job(b, last, 2.0, degradation_cost=c, label=f"degradation ${c:g}/MWh")
             for c in (0.0, 30.0) for b in ("B4", "B3")]
    jobs += [Job("B3", last, 2.0, horizon_h=48.0, label="B3 horizon 48 h")]
    jobs += [Job(b, last, 2.0, rte=r, label=f"RTE {r:.0%}") for r in (0.85, 0.88) for b in ("B4", "B3")]
    jobs += [Job("B4", y, 2.0, mlf_station=None, label="MLF 1.0") for y in years]
    return jobs


def _k(x: float) -> str:
    return f"{x / 1000:,.0f}k"


def build_report(df: pd.DataFrame) -> str:
    base = df[df["label"] == "base"]
    piv = base.pivot_table(index=["year", "duration_h"], columns="benchmark",
                           values=["revenue_per_mw", "net_per_mw", "cycles_per_day"]).sort_index()
    rows = []
    for (year, dur), r in piv.iterrows():
        rows.append(f"| {year} | {dur:g} h | {_k(r[('revenue_per_mw', 'B4')])} | {_k(r[('net_per_mw', 'B4')])} | "
                    f"{_k(r[('revenue_per_mw', 'B3')])} | "
                    f"{r[('revenue_per_mw', 'B3')] / r[('revenue_per_mw', 'B4')]:.1%} | "
                    f"{r[('cycles_per_day', 'B4')]:.2f} | {r[('cycles_per_day', 'B3')]:.2f} |")
    sens = df[~df["label"].isin(["base", "MLF 1.0"])].sort_values(["label", "benchmark"])
    srows = [f"| {r.label} | {r.benchmark} | {_k(r.revenue_per_mw)} | {_k(r.net_per_mw)} | {r.cycles_per_day:.2f} |"
             for r in sens.itertuples()]
    last = int(base["year"].max())
    mlf = df[(df["label"] == "base") & (df["benchmark"] == "B4") & (df["duration_h"] == 2.0)].set_index("year")
    unity = df[df["label"] == "MLF 1.0"].set_index("year")["revenue_per_mw"]
    mrows = [f"| {y} | {r.mlf_gen_mean:.4f} | {r.mlf_load_mean:.4f} | {r.mlf_backfilled_share:.0%} | "
             f"{_k(unity.get(y, np.nan))} | {_k(r.revenue_per_mw)} | {r.revenue_per_mw / unity.get(y, np.nan) - 1:+.1%} |"
             for y, r in mlf.iterrows()]
    ref = base[(base["year"] == last) & (base["duration_h"] == 2.0)].set_index("benchmark")["revenue_per_mw"]
    return "\n".join([
        "# M2: perfect-foresight benchmarks (NSW1, energy only)",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.eval.perfect_foresight`.",
        "",
        "Gross energy revenue per MW of rated power per calendar year, settled at actual 5-minute RRP.",
        f"Base asset: 100 MW, SoC 5–95%, RTE {BatteryConfig().rte:.0%}, no fees, degradation A${BatteryConfig().degradation_cost:g}/MWh"
        " discharged (optimised net; gross revenue shown, net in the B4 net column) and Riverina 1 BESS (RESS1)",
        "MLFs by date from AEMO registration data (DUDETAILSUMMARY); see the MLF table below.",
        "B4 = full-year LP (perfect foresight, terminal SoC ≥ initial). B3 = rolling MPC on actual prices,",
        "24 h horizon, re-solved every interval. Both: no discharge at negative prices (see `rbit/optim/lp.py`).",
        "B3 can edge above B4: it may end the year at a lower SoC and plans with prices past 31 Dec,",
        "while B4 must finish at or above its starting SoC.",
        "",
        "## $/MW/yr by year and duration",
        "",
        "| Year | Duration | B4 full-horizon LP | B4 net | B3 rolling MPC (24 h) | B3 / B4 | B4 cycles/day | B3 cycles/day |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        f"## First check against the $217k/MW claim ({last}, 2 h)",
        "",
        f"- B4 {_k(ref['B4'])} and B3 {_k(ref['B3'])} $/MW/yr, energy only, perfect foresight.",
        f"- The claim ({_k(INDUSTRY_CLAIM)}) is energy + FCAS with no foresight, so it is "
        f"{INDUSTRY_CLAIM / ref['B3']:.0%} of B3 and {INDUSTRY_CLAIM / ref['B4']:.0%} of B4 on this basis.",
        "- Gross revenue, as industry figures are. Caveats: price-taker, no network constraints. The energy-only comparator",
        "  comes in M2b.",
        "",
        "## Marginal loss factors (Riverina 1 BESS, RESS1) and their effect, B4 2 h",
        "",
        "Time-weighted mean MLFs over the year. RESS1 was registered on 2023-05-23; earlier intervals use its",
        "first published MLFs (FY2022-23: gen 0.9286, load 0.9311), shown as the back-filled share.",
        "",
        "| Year | Gen MLF | Load MLF | Back-filled | B4 at MLF 1.0 | B4 at RESS1 MLFs | Change |",
        "|---|---|---|---|---|---|---|",
        *mrows,
        "",
        f"## Sensitivities ({last}, 2 h)",
        "",
        "| Case | Benchmark | Revenue $/MW/yr | Net of degradation $/MW/yr | Cycles/day |",
        "|---|---|---|---|---|",
        *srows,
        "",
    ])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024, 2025])
    ap.add_argument("--durations", nargs="+", type=float, default=[1.0, 2.0, 4.0])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=Path("reports") / "m2_perfect_foresight")
    ap.add_argument("--report-only", action="store_true", help="rebuild the .md from an existing .csv")
    args = ap.parse_args(argv)
    if args.report_only:
        args.out.with_suffix(".md").write_text(build_report(pd.read_csv(args.out.with_suffix(".csv"))))
        return
    data_cfg = DataConfig()
    jobs = default_jobs(args.years, args.durations)
    registration = load_registration(data_cfg)
    schedules = {st: mlf_schedule(registration, st) for st in {j.mlf_station for j in jobs} if st}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_job, jobs, [data_cfg] * len(jobs), [schedules] * len(jobs)))
    df = pd.DataFrame(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_suffix(".md").write_text(build_report(df))
    print(f"wrote {args.out.with_suffix('.md')} and .csv")


if __name__ == "__main__":
    main()
