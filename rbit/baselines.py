"""Non-learning baselines.

B1: time-of-day rule. Charge at full power for ``hours`` from ``charge_start``, discharge for ``hours``
    from ``discharge_start`` (hour of interval start, NEM time); the battery model trims to SoC limits.
B2: pre-dispatch MPC. Each interval, plan on the latest P5MIN prices (5-min, ~1 h) then PREDISPATCH
    (30-min, held flat over its six 5-min intervals) taken as-is, read only through InfoSet, and execute
    the first action.
"""

import numpy as np
import pandas as pd

from rbit.battery import project, simulate, step
from rbit.config import BatteryConfig
from rbit.data.infoset import InfoSet, Observation
from rbit.market import settle
from rbit.optim.lp import RollingMPC

FIVE = pd.Timedelta(minutes=5)
# PREDISPATCH reaches at least ~15.5 h ahead (the 12:00 run ends at 04:00 next day), so a 15 h
# horizon needs no padding except in archive gaps.
B2_HORIZON = 180


def tod_schedule(cfg: BatteryConfig, interval_end: pd.DatetimeIndex, charge_start: int, discharge_start: int,
                 hours: int | None = None) -> np.ndarray:
    hours = int(round(cfg.duration_h)) if hours is None else hours
    h = (pd.DatetimeIndex(interval_end) - FIVE).hour.to_numpy()
    window = lambda s: (h - s) % 24 < hours  # noqa: E731
    return np.where(window(discharge_start), cfg.power_mw, np.where(window(charge_start), -cfg.power_mw, 0.0))


def tune_tod(cfg: BatteryConfig, years: list[tuple[np.ndarray, pd.DatetimeIndex, np.ndarray, np.ndarray]],
             ) -> tuple[int, int]:
    """Best (charge_start, discharge_start) by total net revenue over the given (rrp, ends, gen, load) years.

    Grid follows the rule's intent: charge in the solar trough (06-15h), discharge in the evening (15-22h).
    """
    best, best_v = (0, 0), -np.inf
    for c in range(6, 16):
        for d in range(15, 23):
            v = sum(settle(cfg, rrp, simulate(cfg, tod_schedule(cfg, ends, c, d))[0], g, ld).net.sum()
                    for rrp, ends, g, ld in years)
            if v > best_v:
                best, best_v = (c, d), v
    return best


def predispatch_path(obs: Observation, horizon: int) -> tuple[np.ndarray, int]:
    """Price path for intervals obs.interval_end .. +horizon-1 and the number of padded steps.

    P5MIN where it covers, then PREDISPATCH by 30-min period; any remaining gap holds the last known
    price (only in archive gaps / stale runs, where InfoSet returns no run).
    """
    ends = pd.date_range(obs.interval_end, periods=horizon, freq=FIVE)
    p5 = obs.p5min.set_index("interval_end")["rrp"].reindex(ends)
    pd30 = obs.predispatch_price.set_index("interval_end")["rrp"].reindex(ends.ceil("30min"))
    path = p5.fillna(pd.Series(pd30.to_numpy(), index=ends))
    padded = int(path.isna().sum())
    if padded:
        last = obs.dispatch_price["rrp"].iloc[-1] if len(obs.dispatch_price) else 0.0
        path = path.ffill().fillna(last)
    return path.to_numpy(), padded


def run_predispatch_mpc(cfg: BatteryConfig, info: InfoSet, ends: pd.DatetimeIndex, gen: np.ndarray,
                        load: np.ndarray, horizon: int = B2_HORIZON) -> tuple[np.ndarray, dict[str, int]]:
    """B2 over ``ends``. ``gen``/``load`` are MLFs for ``ends`` followed by ``horizon`` more intervals."""
    mpc = RollingMPC(cfg, horizon)
    e = cfg.e_init
    mw = np.empty(len(ends))
    padded_steps = 0
    for i, t in enumerate(ends):
        path, padded = predispatch_path(info.at(t), horizon)
        padded_steps += padded > 0
        a = project(cfg, e, mpc.plan(path, e, gen[i: i + horizon], load[i: i + horizon])[0])
        e = min(max(step(cfg, e, a), cfg.e_min), cfg.e_max)
        mw[i] = a
    return mw, {"n_padded": padded_steps, "n_fallback": mpc.n_fallback, "n_cold": mpc.n_cold}
