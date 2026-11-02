import numpy as np
import pandas as pd
import pytest

from conftest import write_mms_zip
from rbit.data.mms import read_mms_zip
from rbit.eval.industry import SERVICES, unit_revenues

H = 5 / 60


def _sched(gen, load):
    return pd.DataFrame({"start": [pd.Timestamp("2020-01-01")], "end": [pd.Timestamp("2999-12-31")],
                         "mlf_gen": [gen], "mlf_load": [load]})


def test_energy_trapezoid_mlf_by_direction_and_fcas():
    ends = pd.date_range("2025-01-01 00:05", periods=4, freq="5min")
    units = pd.DataFrame({"duid": "B1", "interval_end": ends,
                          "initial_mw": [0.0, -60.0, -60.0, 60.0], "total_cleared": [-60.0, -60.0, 60.0, 60.0]}
                         | {s.lower(): 0.0 for s in SERVICES})
    units.loc[0, "raise6sec"] = 10.0
    prices = pd.DataFrame({"interval_end": ends} | {f"{s}RRP": 0.0 for s in SERVICES})
    prices.loc[0, "RAISE6SECRRP"] = 30.0
    rrp = pd.DataFrame({"interval_end": ends, "rrp": [10.0, 20.0, 30.0, 40.0]})
    r = unit_revenues(units, prices, rrp, {"B1": _sched(0.9, 0.8)}).loc["B1"]
    e = np.array([-30, -60, 0, 60]) * H  # trapezoid between successive SCADA readings; last uses its own value
    mlf = np.where(e > 0, 0.9, 0.8)
    assert r["energy"] == pytest.approx(float((np.array([10, 20, 30, 40]) * e * mlf).sum()))
    assert r["fcas"] == pytest.approx(10 * 30 * H)
    assert r["energy_target"] == pytest.approx(float((np.array([10, 20, 30, 40]) * np.array([-60, -60, 60, 60]) * H
                                                      * np.array([0.8, 0.8, 0.9, 0.9])).sum()))


def test_where_filter_keeps_only_listed_values(tmp_path):
    p = write_mms_zip(tmp_path / "dl.zip", [(["DUID", "INITIALMW"], [["RESS1", "1"], ["RESS1G", "2"], ["X", "RESS1"]])])
    df = read_mms_zip(p, ["DUID", "INITIALMW"], where=("DUID", {"RESS1"}))
    assert df["DUID"].tolist() == ["RESS1"]


def test_unit_cache_hits_even_when_a_requested_unit_has_no_rows(tmp_path, monkeypatch):
    import rbit.eval.industry as ind
    from rbit.config import DataConfig
    calls = []
    monkeypatch.setattr(ind.archive, "download_table", lambda *a, **k: calls.append(a) or ["x.zip"])
    rows = {"SETTLEMENTDATE": ["2025/01/01 00:05:00"], "DUID": ["A"], "INTERVENTION": ["0"], "INITIALMW": ["1"],
            "TOTALCLEARED": ["1"]} | {s: ["0"] for s in SERVICES}
    monkeypatch.setattr(ind, "read_mms_zip", lambda *a, **k: pd.DataFrame(rows))
    cfg = DataConfig(data_root=tmp_path)
    for _ in range(2):  # unit "B" not registered yet: no rows, but the second call must still hit the cache
        df = ind._unit_month(cfg, ("A", "B"), 2025, 1)
    assert len(calls) == 1 and df["duid"].tolist() == ["A"]
    ind._unit_month(cfg, ("A", "C"), 2025, 1)  # a unit never asked for: miss
    assert len(calls) == 2


def test_report_refuses_an_empty_fleet():
    from rbit.eval.industry import build_report
    res = pd.DataFrame({"two_hour": [False], "full_year": [True], "excluded": [""]}, index=["X"])
    with pytest.raises(ValueError, match="no 2-hour"):
        build_report(res, 2024, None)
