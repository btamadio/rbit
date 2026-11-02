"""Turn raw MMS rows into canonical, typed tables with an ``available_at`` column.

``available_at`` is when a row could first have been seen by a market participant.

Run-based tables (P5MIN, PREDISPATCH): max LASTCHANGED over the run, i.e. a run is
visible only once all of its rows are. Late runs are genuinely late, so this is exact.

Dispatch tables: ``min(LASTCHANGED, interval start + DISPATCH_PUBLISH_ALLOWANCE)``.
The MMSDM archive re-stamps LASTCHANGED on many dispatch rows long after publication
(e.g. ~20% of NSW1 intervals in Mar-Apr 2026, 10-30 min late) without changing RRP:
checked against the real-time DispatchIS files for 2026-03-24, 184 re-stamped rows,
0 RRP differences. Using LASTCHANGED there would hide history a live agent sees.
Rows with a late stamp are flagged ``restamped``; the rare genuine revisions (e.g.
the June 2022 market suspension) are listed in the data-quality report.
"""

import pandas as pd

from rbit.data.tables import TableSpec

TS_FORMAT = "%Y/%m/%d %H:%M:%S"
_TIME_COLS = ("interval_end", "run_datetime", "lastchanged")
_STR_COLS = ("region", "price_status")
DISPATCH_PUBLISH_ALLOWANCE = pd.Timedelta(seconds=60)


def normalise(raw: pd.DataFrame, spec: TableSpec) -> pd.DataFrame:
    df = raw.rename(columns=spec.columns)[list(spec.columns.values())].copy()
    for c in df.columns:
        if c in _TIME_COLS:
            df[c] = pd.to_datetime(df[c], format=TS_FORMAT)
        elif c in _STR_COLS:
            df[c] = df[c].astype("string")
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["intervention"] = df["intervention"].fillna(0).astype("int8")

    if spec.name.startswith("predispatch"):
        df["seqno"] = df["seqno"].astype("int64")
        df["runno"] = df["runno"].astype("int64")
        df["run_datetime"] = predispatch_run_datetime(df["seqno"])

    df = _resolve_intervention(df, spec.key)
    df = dedup(df, spec.key)

    if "run_datetime" in df.columns:
        run_key = ["seqno", "runno"] if "seqno" in df.columns else ["run_datetime"]
        df["available_at"] = df.groupby(run_key)["lastchanged"].transform("max")
    else:
        on_time = df["interval_end"] - pd.Timedelta(minutes=5) + DISPATCH_PUBLISH_ALLOWANCE
        df["restamped"] = df["lastchanged"] > on_time
        df["available_at"] = df["lastchanged"].where(~df["restamped"], on_time)
    return df.sort_values(list(spec.key)).reset_index(drop=True)


def _resolve_intervention(df: pd.DataFrame, key: tuple[str, ...]) -> pd.DataFrame:
    """Keep the INTERVENTION=0 (pricing run) row; flag keys that also had an intervention run."""
    flagged = df.loc[df["intervention"] == 1, list(key)].drop_duplicates()
    out = df[df["intervention"] == 0].drop(columns="intervention")
    flagged["intervention_flag"] = True
    out = out.merge(flagged, on=list(key), how="left")
    out["intervention_flag"] = out["intervention_flag"].fillna(False).astype(bool)
    return out


def dedup(df: pd.DataFrame, key: tuple[str, ...]) -> pd.DataFrame:
    """Keep the latest-revised row per key."""
    return df.sort_values("lastchanged").drop_duplicates(list(key), keep="last")


def predispatch_run_datetime(seqno: pd.Series) -> pd.Series:
    """Nominal run time from PREDISPATCHSEQNO (YYYYMMDDPP).

    The trading day starts at 04:00; run PP is nominally at 04:00 + (PP-1) * 30min,
    and its first period ends 30 minutes later.
    """
    s = seqno.astype("int64")
    day = pd.to_datetime((s // 100).astype(str), format="%Y%m%d")
    period = s % 100
    return day + pd.Timedelta(hours=4) + pd.to_timedelta((period - 1) * 30, unit="min")


def nominal_publish_time(df: pd.DataFrame, table: str) -> pd.Series:
    """When each row is nominally expected to be published (used for lag diagnostics)."""
    if table.startswith("dispatch"):
        return df["interval_end"] - pd.Timedelta(minutes=5)
    if table == "p5min_region":
        return df["run_datetime"] - pd.Timedelta(minutes=5)
    if table.startswith("predispatch"):
        return df["run_datetime"]
    raise ValueError(table)
