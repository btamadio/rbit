import numpy as np
import pandas as pd

from rbit.baselines import predispatch_path, tod_schedule
from rbit.config import BatteryConfig
from rbit.data.infoset import Observation

T = pd.Timestamp("2025-03-01 12:05")


def _obs(p5_steps=12, pd_periods=40, history=True):
    p5 = pd.DataFrame({"interval_end": pd.date_range(T - pd.Timedelta(minutes=5), periods=p5_steps, freq="5min"),
                       "rrp": np.arange(p5_steps, dtype=float)})
    pdp = pd.DataFrame({"interval_end": pd.date_range("2025-03-01 12:30", periods=pd_periods, freq="30min"),
                        "rrp": 100.0 + np.arange(pd_periods)})
    disp = pd.DataFrame({"interval_end": [T - pd.Timedelta(minutes=5)], "rrp": [42.0]})
    empty = pd.DataFrame(columns=["interval_end", "rrp"])
    return Observation(T, T, disp if history else empty, empty, p5, pdp, empty)


def test_path_uses_p5min_then_predispatch_by_period():
    path, padded = predispatch_path(_obs(), 24)
    assert padded == 0
    assert path[:11].tolist() == list(range(1, 12))  # P5MIN from T (its 2nd interval) to its end
    # 13:00 onwards: ends 13:00 (period 13:00 = 101), 13:05..13:30 -> period ending 13:30 (102)
    assert path[11] == 101.0 and path[12:18].tolist() == [102.0] * 6


def test_gap_holds_last_price_and_counts_padding():
    path, padded = predispatch_path(_obs(pd_periods=0), 24)
    assert padded == 13 and (path[11:] == 11.0).all()  # last P5MIN price held
    path, padded = predispatch_path(_obs(p5_steps=0, pd_periods=0), 5)
    assert padded == 5 and (path == 42.0).all()  # nothing published: hold last dispatch price


def test_tod_windows_wrap_and_discharge_wins():
    cfg = BatteryConfig()
    ends = pd.date_range("2025-03-01 00:05", periods=288, freq="5min")
    a = tod_schedule(cfg, ends, charge_start=10, discharge_start=23)
    hour = (ends - pd.Timedelta(minutes=5)).hour
    assert (a[(hour >= 10) & (hour < 12)] == -cfg.power_mw).all()
    assert (a[(hour == 23) | (hour == 0)] == cfg.power_mw).all()  # wraps past midnight
    assert (a[(hour >= 12) & (hour < 23) & (hour != 0)] == 0).all()
