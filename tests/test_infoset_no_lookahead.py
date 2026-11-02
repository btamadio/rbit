"""No-lookahead tests for InfoSet (milestone M1 exit criterion).

Invariant: for a decision about the interval ending at T, every row returned has
available_at < cutoff = T - 5min - margin, and run-based tables return the most
recent run that was already published at the cutoff.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from rbit.config import DataConfig
from rbit.data import store
from rbit.data.infoset import InfoSet

FIVE = pd.Timedelta(minutes=5)
CFG = DataConfig()


def _run_tables(tables) -> dict[str, pd.DataFrame]:
    """Per-run publish time and run_datetime, computed once per set of tables."""
    out = {}
    for table, key in [("p5min_region", ["run_datetime"]), ("predispatch_price", ["seqno", "runno"]),
                       ("predispatch_regionsum", ["seqno", "runno"])]:
        g = tables[table].groupby(key)
        out[table] = pd.DataFrame({"available_at": g["available_at"].max(), "run_datetime": g["run_datetime"].first(),
                                   "rows": g.size()})
    return out


def _check(obs, tables, runs_by_table=None) -> None:
    runs_by_table = runs_by_table or _run_tables(tables)
    c = obs.cutoff
    assert c == obs.interval_end - FIVE - pd.Timedelta(CFG.decision_margin)
    for name in ["dispatch_price", "dispatch_regionsum", "p5min", "predispatch_price", "predispatch_regionsum"]:
        df = getattr(obs, name)
        assert (df["available_at"] < c).all(), f"{name} leaks data published at/after {c}"
    # the interval being decided (and anything later) is never visible
    if len(obs.dispatch_price):
        assert obs.dispatch_price["interval_end"].max() < obs.interval_end
    # run tables: chosen run == most recent run published before the cutoff (brute force)
    for name, table, key, max_age in [
        ("p5min", "p5min_region", ["run_datetime"], CFG.max_p5min_age),
        ("predispatch_price", "predispatch_price", ["seqno", "runno"], CFG.max_predispatch_age),
        ("predispatch_regionsum", "predispatch_regionsum", ["seqno", "runno"], CFG.max_predispatch_age),
    ]:
        runs = runs_by_table[table]
        visible = runs[runs["available_at"] < c]
        got = getattr(obs, name)
        if visible.empty or c - visible["run_datetime"].loc[visible.index.max()] > pd.Timedelta(max_age):
            assert got.empty, f"{name}: expected no run (none visible, or latest is stale)"
            continue
        want = visible.index.max()
        got_key = tuple(got.iloc[0][key]) if len(key) > 1 else got.iloc[0][key[0]]
        assert got_key == want, f"{name}: got run {got_key}, latest visible is {want}"
        assert len(got) == runs.loc[want, "rows"]


def _synthetic() -> dict[str, pd.DataFrame]:
    """Two days of synthetic data with realistic publish times plus some pathological cases."""
    ends = pd.date_range("2025-03-01 00:05", "2025-03-03 00:00", freq="5min")
    dp = pd.DataFrame({"interval_end": ends, "rrp": np.arange(len(ends), dtype=float)})
    dp["available_at"] = dp["interval_end"] - FIVE + pd.Timedelta(seconds=3)
    # a late revision: interval 12:00 on day 1 only republished two hours later
    late = dp["interval_end"] == pd.Timestamp("2025-03-01 12:00")
    dp.loc[late, "available_at"] = pd.Timestamp("2025-03-01 14:00")
    # a slow publication: 18:00 published at 17:59:33, after the 17:59 cutoff for deciding 18:05
    slow = dp["interval_end"] == pd.Timestamp("2025-03-01 18:00")
    dp.loc[slow, "available_at"] += pd.Timedelta(minutes=4, seconds=30)
    drs = dp[["interval_end", "available_at"]].assign(total_demand=8000.0)

    p5 = []
    for r in ends:
        pub = r - FIVE + pd.Timedelta(seconds=27)
        if r == pd.Timestamp("2025-03-01 09:00"):
            pub += pd.Timedelta(hours=1)  # an old run that only becomes visible much later
        p5.append(pd.DataFrame({"run_datetime": r, "interval_end": pd.date_range(r, periods=12, freq="5min"),
                                "rrp": 1.0, "available_at": pub}))
    p5 = pd.concat(p5, ignore_index=True)

    pdp = []
    for i, r in enumerate(pd.date_range("2025-02-28 04:00", "2025-03-02 23:30", freq="30min")):
        seqno = int(f"{(r - pd.Timedelta(hours=4)):%Y%m%d}{((r.hour - 4) % 24) * 2 + r.minute // 30 + 1:02d}")
        for runno in (1, 2) if i % 7 == 0 else (1,):  # occasional re-runs
            pdp.append(pd.DataFrame({
                "seqno": seqno, "runno": runno, "run_datetime": r,
                "interval_end": pd.date_range(r + pd.Timedelta(minutes=30), periods=60, freq="30min"),
                "rrp": float(runno), "available_at": r + pd.Timedelta(minutes=1 + 5 * runno),
            }))
    pdp = pd.concat(pdp, ignore_index=True)
    return {"dispatch_price": dp, "dispatch_regionsum": drs, "p5min_region": p5,
            "predispatch_price": pdp, "predispatch_regionsum": pdp.drop(columns="rrp").assign(total_demand=1.0)}


def test_decision_cutoff_definition():
    info = InfoSet(_synthetic(), CFG)
    t = pd.Timestamp("2025-03-02 10:00")
    assert info.cutoff(t) == t - FIVE - timedelta(seconds=60)


def test_no_lookahead_synthetic_every_interval():
    tables = _synthetic()
    info, runs = InfoSet(tables, CFG), _run_tables(tables)
    for t in pd.date_range("2025-03-01 00:05", "2025-03-02 23:00", freq="5min"):
        _check(info.at(t), tables, runs)


def test_typical_case_sees_previous_interval_and_current_p5min_run():
    info = InfoSet(_synthetic(), CFG)
    t = pd.Timestamp("2025-03-02 10:00")
    obs = info.at(t)
    assert obs.dispatch_price["interval_end"].max() == t - FIVE  # price of T-5 is known, T is not
    assert obs.p5min["run_datetime"].iloc[0] == t - FIVE  # run that includes T as its 2nd interval
    assert t in set(obs.p5min["interval_end"])


def test_late_revision_and_slow_publication_excluded():
    info = InfoSet(_synthetic(), CFG, n_history=48)
    # revised 12:00 interval is invisible until 14:00 even though later intervals are visible
    obs = info.at(pd.Timestamp("2025-03-01 13:00"))
    assert pd.Timestamp("2025-03-01 12:00") not in set(obs.dispatch_price["interval_end"])
    obs = info.at(pd.Timestamp("2025-03-01 14:30"))
    assert pd.Timestamp("2025-03-01 12:00") in set(obs.dispatch_price["interval_end"])
    # 18:00 published late is not visible when deciding 18:05
    obs = info.at(pd.Timestamp("2025-03-01 18:05"))
    assert obs.dispatch_price["interval_end"].max() == pd.Timestamp("2025-03-01 17:55")


def test_late_old_run_does_not_replace_newer_run():
    info = InfoSet(_synthetic(), CFG)
    obs = info.at(pd.Timestamp("2025-03-01 10:00"))  # the 09:00 run became visible at ~09:55
    assert obs.p5min["run_datetime"].iloc[0] == pd.Timestamp("2025-03-01 09:55")
    obs = info.at(pd.Timestamp("2025-03-01 09:05"))  # 09:00 run not yet visible -> fall back to 08:55
    assert obs.p5min["run_datetime"].iloc[0] == pd.Timestamp("2025-03-01 08:55")


def test_stale_runs_are_not_served_across_a_gap():
    tables = _synthetic()
    p5 = tables["p5min_region"]
    gap = (p5["run_datetime"] > pd.Timestamp("2025-03-01 20:00")) & (p5["run_datetime"] < pd.Timestamp("2025-03-01 22:00"))
    tables["p5min_region"] = p5[~gap]
    info = InfoSet(tables, CFG)
    assert not info.at(pd.Timestamp("2025-03-01 20:20")).p5min.empty  # 20:00 run is 14 min old: fine
    assert info.at(pd.Timestamp("2025-03-01 21:00")).p5min.empty  # 54 min old: stale
    for t in pd.date_range("2025-03-01 19:00", "2025-03-01 23:00", freq="5min"):
        _check(info.at(t), tables)


_REAL = [t for t in ["dispatch_price", "dispatch_regionsum", "p5min_region", "predispatch_price",
                     "predispatch_regionsum"] if any(store.table_dir(CFG, t).glob("*.parquet"))]


@pytest.mark.realdata
@pytest.mark.skipif(len(_REAL) < 5, reason="cleaned data not ingested (python -m rbit.data.ingest)")
def test_no_lookahead_real_data_random_points():
    tables = {t: store.load(CFG, t) for t in _REAL}
    info = InfoSet(tables, CFG)
    ends = tables["dispatch_price"]["interval_end"]
    lo, hi = ends.min() + pd.Timedelta(days=2), ends.max()
    rng = np.random.default_rng(0)
    n_steps = int((hi - lo) / FIVE)
    points = lo + FIVE * np.sort(rng.choice(n_steps, size=min(2000, n_steps), replace=False))
    runs = _run_tables(tables)
    for t in points:
        _check(info.at(t), tables, runs)
