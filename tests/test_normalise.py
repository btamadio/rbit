import pandas as pd

from rbit.data.normalise import normalise, predispatch_run_datetime
from rbit.data.tables import TABLES


def _raw(spec, rows):
    return pd.DataFrame(rows, columns=list(spec.columns), dtype=object)


def test_dispatch_intervention_and_dedup():
    spec = TABLES["dispatch_price"]
    # REGIONID, INTERVENTION, LASTCHANGED, SETTLEMENTDATE, RRP, APCFLAG, MARKETSUSPENDEDFLAG, PRICE_STATUS
    raw = _raw(spec, [
        ["NSW1", "0", "2025/03/01 00:00:02", "2025/03/01 00:05:00", "100", "0", "0", "FIRM"],
        ["NSW1", "1", "2025/03/01 00:00:02", "2025/03/01 00:05:00", "999", "0", "0", "FIRM"],
        ["NSW1", "0", "2025/03/01 00:05:03", "2025/03/01 00:10:00", "50", "0", "0", "FIRM"],
        ["NSW1", "0", "2025/03/01 02:00:00", "2025/03/01 00:10:00", "55", "0", "0", "FIRM"],  # revision
    ])
    df = normalise(raw, spec)
    assert list(df["rrp"]) == [100.0, 55.0]
    assert list(df["intervention_flag"]) == [True, False]
    # a late LASTCHANGED is treated as a re-stamp: visible at nominal publish + allowance, and flagged
    assert df.loc[1, "available_at"] == pd.Timestamp("2025-03-01 00:06:00")
    assert list(df["restamped"]) == [False, True]
    assert df.loc[0, "available_at"] == pd.Timestamp("2025-03-01 00:00:02")


def test_predispatch_run_datetime():
    s = pd.Series([2025030101, 2025030148, 2025030102])
    got = predispatch_run_datetime(s)
    assert list(got) == [pd.Timestamp("2025-03-01 04:00"), pd.Timestamp("2025-03-02 03:30"),
                         pd.Timestamp("2025-03-01 04:30")]


def test_run_available_at_is_max_over_run():
    spec = TABLES["p5min_region"]
    cols = list(spec.columns)
    base = dict.fromkeys(cols, "0")
    rows = []
    for interval, lc in [("2025/03/01 00:05:00", "2025/03/01 00:00:27"), ("2025/03/01 00:10:00", "2025/03/01 00:00:31")]:
        r = base | {"REGIONID": "NSW1", "RUN_DATETIME": "2025/03/01 00:05:00", "INTERVAL_DATETIME": interval,
                    "LASTCHANGED": lc}
        rows.append([r[c] for c in cols])
    df = normalise(_raw(spec, rows), spec)
    assert (df["available_at"] == pd.Timestamp("2025-03-01 00:00:31")).all()
