"""M3b (first stage): is correcting pre-dispatch worth money? Gap model F4 vs raw pre-dispatch (B2).

    python -m rbit.eval.forecast

Trains on 2022-2023 issue times (every 30 min), evaluates forecast accuracy on CY2024 and runs B2 and
B2-F4 (same MPC, corrected path) on CY2024. Writes reports/m3b_forecast.{md,csv}.

shortcut: the model is retrained on every run (a few minutes); persist it if later stages reuse it.
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from rbit.baselines import B2_HORIZON, run_predispatch_mpc
from rbit.config import BatteryConfig, DataConfig
from rbit.data import store
from rbit.data.infoset import InfoSet
from rbit.eval.perfect_foresight import metrics, year_prices
from rbit.forecast import FEATURES, GapCorrector, fit, issue_times, training_rows
from rbit.market.mlf import load_registration, mlf_schedule, mlf_series

TRAIN = ("2022-01-01", "2024-01-01")
EVAL_YEAR = 2024
BUCKETS = [(0, 12, "0–1 h"), (12, 48, "1–4 h"), (48, B2_HORIZON, f"4–{B2_HORIZON // 12} h")]


def _actual(cfg: DataConfig, start, end) -> pd.Series:
    d = store.load(cfg, "dispatch_price", start, end)
    return d.set_index("interval_end")["rrp"]


def run_mpc(label: str, model, data_cfg: DataConfig, schedule: pd.DataFrame) -> dict:
    cfg = BatteryConfig()
    rrp, ends, n = year_prices(data_cfg, EVAL_YEAR)
    m = mlf_series(schedule, ends)
    ends = pd.DatetimeIndex(ends)
    info = InfoSet.from_store(data_cfg, ends[0], ends[-1])
    t0 = time.time()
    mw, stats = run_predispatch_mpc(cfg, info, ends[:n], m.gen, m.load, B2_HORIZON,
                                    adjust=GapCorrector(model) if model is not None else None)
    return ({"strategy": label, "year": EVAL_YEAR} | metrics(cfg, rrp[:n], mw, m.gen[:n], m.load[:n]) | stats
            | {"seconds": round(time.time() - t0, 1)})


def accuracy(rows: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    out = []
    for lo, hi, name in BUCKETS:
        r = rows["h"].between(lo, hi - 1).to_numpy()
        err_raw = rows["target"].to_numpy()[r]  # actual - raw
        err_f4 = err_raw - pred[r]
        out.append({"horizon": name, "rows": int(r.sum()),
                    "mae_raw": np.abs(err_raw).mean(), "mae_f4": np.abs(err_f4).mean(),
                    "rmse_raw": np.sqrt((err_raw ** 2).mean()), "rmse_f4": np.sqrt((err_f4 ** 2).mean()),
                    "bias_raw": err_raw.mean(), "bias_f4": err_f4.mean()})
    return pd.DataFrame(out)


def _k(x: float) -> str:
    return f"{x / 1000:,.0f}k"


def build_report(acc: pd.DataFrame, res: pd.DataFrame, n_train: int) -> str:
    acc_rows = [f"| {r.horizon} | {r.mae_raw:,.1f} | {r.mae_f4:,.1f} | {r.rmse_raw:,.0f} | {r.rmse_f4:,.0f} | "
                f"{r.bias_raw:+,.1f} | {r.bias_f4:+,.1f} |" for r in acc.itertuples()]
    r = res.set_index("strategy")
    b2, f4 = r.loc["B2"], r.loc["B2-F4"]
    return "\n".join([
        f"# M3b stage 1: pre-dispatch gap model (F4), CY{EVAL_YEAR}",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.eval.forecast`. Gradient-boosted",
        f"model of (actual RRP − pre-dispatch path price), trained on {TRAIN[0][:4]}–{int(TRAIN[1][:4]) - 1} issue",
        f"times every 30 min ({n_train:,} rows, every 3rd step), features: {', '.join(FEATURES)}.",
        "Evaluation year never seen in training. Errors in $/MWh against the price that settled.",
        "",
        "## Forecast accuracy (path built from P5MIN then PREDISPATCH)",
        "",
        "| Horizon | MAE raw | MAE F4 | RMSE raw | RMSE F4 | Bias raw | Bias F4 |",
        "|---|---|---|---|---|---|---|",
        *acc_rows,
        "",
        "## Value in the MPC (2 h, Riverina 1 MLFs, `BatteryConfig()` defaults)",
        "",
        "| Strategy | Gross $/MW/yr | Net $/MW/yr | Cycles/day |",
        "|---|---|---|---|",
        f"| B2 pre-dispatch MPC | {_k(b2.revenue_per_mw)} | {_k(b2.net_per_mw)} | {b2.cycles_per_day:.2f} |",
        f"| B2-F4 pre-dispatch + gap correction | {_k(f4.revenue_per_mw)} | {_k(f4.net_per_mw)} | {f4.cycles_per_day:.2f} |",
        "",
        f"**Net change from the correction: {f4.net_per_mw - b2.net_per_mw:+,.0f} $/MW/yr "
        f"({f4.net_per_mw / b2.net_per_mw - 1:+.1%}).**",
        "",
    ])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("reports") / "m3b_forecast")
    args = ap.parse_args(argv)
    data_cfg = DataConfig()

    ends = pd.DatetimeIndex(_actual(data_cfg, *TRAIN).index)
    info = InfoSet.from_store(data_cfg, *TRAIN)
    train = training_rows(info, _actual(data_cfg, TRAIN[0], "2024-01-03"), issue_times(ends), step=3)
    model = fit(train)

    y0, y1 = f"{EVAL_YEAR}-01-01", f"{EVAL_YEAR + 1}-01-01"
    eval_info = InfoSet.from_store(data_cfg, y0, y1)
    rows = training_rows(eval_info, _actual(data_cfg, y0, f"{EVAL_YEAR + 1}-01-03"),
                         issue_times(pd.DatetimeIndex(_actual(data_cfg, y0, y1).index)))
    acc = accuracy(rows, model.predict(rows[FEATURES]))

    schedule = mlf_schedule(load_registration(data_cfg), BatteryConfig().mlf_station)
    with ProcessPoolExecutor(max_workers=2) as pool:
        res = pd.DataFrame(pool.map(run_mpc, ["B2", "B2-F4"], [None, model], [data_cfg] * 2, [schedule] * 2))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([acc.assign(kind="accuracy"), res.assign(kind="mpc")]).to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_suffix(".md").write_text(build_report(acc, res, len(train)))
    print(f"wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
