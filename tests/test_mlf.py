import numpy as np
import pandas as pd
import pytest

from rbit.battery import simulate
from rbit.config import BatteryConfig
from rbit.market import settle
from rbit.market.mlf import mlf_schedule, mlf_series
from rbit.optim import run_mpc, solve_schedule

T = pd.Timestamp


def _registration():
    """Shape of DUDETAILSUMMARY for a station that moved from GENERATOR/LOAD DUIDs to a BDU (RESS1 values)."""
    rows = [
        ("S1G", "2023-07-01", "2024-07-01", "GENERATOR", 0.9089, np.nan),
        ("S1L", "2023-07-01", "2024-07-01", "LOAD", 0.9024, np.nan),
        ("S1G", "2024-07-01", "2024-11-06", "GENERATOR", 0.8702, np.nan),
        ("S1L", "2024-07-01", "2024-11-06", "LOAD", 0.8657, np.nan),
        ("S1", "2024-10-10", "2025-07-01", "BIDIRECTIONAL", 0.8657, 0.8702),  # overlaps the split DUIDs
        ("S1", "2025-07-01", "2999-12-31", "BIDIRECTIONAL", 0.9396, 0.8781),
        ("OTHER", "2020-01-01", "2999-12-31", "GENERATOR", 0.5, np.nan),
    ]
    df = pd.DataFrame(rows, columns=["DUID", "START_DATE", "END_DATE", "DISPATCHTYPE", "TRANSMISSIONLOSSFACTOR",
                                     "SECONDARY_TLF"])
    df["STATIONID"] = np.where(df["DUID"] == "OTHER", "OTHER", "S1")
    for c in ("START_DATE", "END_DATE"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_bdu_secondary_tlf_is_generation_and_segments_merge():
    s = mlf_schedule(_registration(), "S1")
    assert list(s["start"]) == [T("2023-07-01"), T("2024-07-01"), T("2025-07-01")]
    assert s.loc[1, ["mlf_gen", "mlf_load"]].tolist() == [0.8702, 0.8657]
    assert s.loc[2, ["mlf_gen", "mlf_load"]].tolist() == [0.8781, 0.9396]


def test_series_uses_interval_start_and_backfills():
    s = mlf_schedule(_registration(), "S1")
    ends = pd.DatetimeIndex([T("2023-01-01 00:05"), T("2025-07-01 00:00"), T("2025-07-01 00:05")])
    m = mlf_series(s, ends)
    assert m.backfilled.tolist() == [True, False, False]
    assert m.gen.tolist() == [0.9089, 0.8702, 0.8781]  # 00:00 interval belongs to the old financial year


def test_lp_mpc_and_settlement_agree_with_time_varying_mlfs():
    cfg = BatteryConfig()
    rng = np.random.default_rng(3)
    n = 500
    p = 80 + 60 * np.sin(np.arange(n) / 40) + rng.normal(0, 15, n)
    gen = np.where(np.arange(n) < 250, 0.87, 0.95)
    load = np.where(np.arange(n) < 250, 0.94, 0.88)
    s = solve_schedule(cfg, p, mlf_gen=gen, mlf_load=load)
    mw, _ = simulate(cfg, s.mw)
    assert settle(cfg, p, mw, gen, load).net.sum() == pytest.approx(s.objective, abs=0.01)
    mpc_mw, _, _ = run_mpc(cfg, p, n, horizon=n, mlf_gen=gen, mlf_load=load)
    assert settle(cfg, p, mpc_mw, gen, load).net.sum() == pytest.approx(s.objective, rel=1e-6)
    # MLFs matter: the same schedule settles differently at MLF 1.0
    assert settle(cfg, p, mw).net.sum() != pytest.approx(s.objective, rel=1e-3)
