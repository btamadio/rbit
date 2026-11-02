"""Marginal loss factors (MLFs) by connection point, from AEMO registration data.

Source: MMSDM ``DUDETAILSUMMARY`` (dated records per DUID, latest monthly archive).
- GENERATOR / LOAD DUIDs: TRANSMISSIONLOSSFACTOR is that direction's MLF.
- BIDIRECTIONAL units (BDUs, since IESS in 2024): TRANSMISSIONLOSSFACTOR is the import (load) MLF
  and SECONDARY_TLF the export (generation) MLF. Checked for Riverina 1 BESS (RESS1) FY2024-25
  against AEMO's published MLF report (import 0.8657, export 0.8702) and the unit's price limits
  (MINIMUM_ENERGY_PRICE -870.2 = -1000 x 0.8702; LOAD_MINIMUM_ENERGY_PRICE -865.7 = -1000 x 0.8657).

Intervals before a station's first record get its earliest MLFs and are flagged ``backfilled``.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from rbit.config import DataConfig
from rbit.data import archive
from rbit.data.mms import read_mms_zip
from rbit.data.tables import TableSpec

DUDETAILSUMMARY = TableSpec(
    name="dudetailsummary",
    mms_table="DUDETAILSUMMARY",
    folder="DATA",
    old_marker="",
    new_marker="",
    columns={},
    key=(),
)
_COLS = ["DUID", "START_DATE", "END_DATE", "DISPATCHTYPE", "STATIONID", "REGIONID", "TRANSMISSIONLOSSFACTOR",
         "SECONDARY_TLF"]
_TS = "%Y/%m/%d %H:%M:%S"


def load_registration(cfg: DataConfig, month: str | None = None) -> pd.DataFrame:
    """DUDETAILSUMMARY rows for cfg.region from the given (default: latest configured) monthly archive."""
    p = pd.Period(month or cfg.end, freq="M")
    raw_dir = cfg.raw_dir / f"{p.year}{p.month:02d}"
    with archive.make_client() as client:
        names = archive.match_files(archive.list_folder(client, p.year, p.month, "DATA"), DUDETAILSUMMARY)
        if not names:
            raise FileNotFoundError(f"DUDETAILSUMMARY not in the {p} archive")
        paths = [archive.download(client, p.year, p.month, "DATA", n, raw_dir) for n in names]
    df = pd.concat([read_mms_zip(path, _COLS, cfg.region) for path in paths], ignore_index=True)
    for c in ("START_DATE", "END_DATE"):
        df[c] = pd.to_datetime(df[c], format=_TS)
    for c in ("TRANSMISSIONLOSSFACTOR", "SECONDARY_TLF"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def mlf_schedule(registration: pd.DataFrame, station_id: str) -> pd.DataFrame:
    """Piecewise-constant [start, end) table of generation and load MLFs for one station."""
    r = registration[registration["STATIONID"] == station_id]
    if r.empty:
        raise KeyError(f"station {station_id!r} not in registration data")
    recs = []
    for x in r.itertuples():
        if x.DISPATCHTYPE == "BIDIRECTIONAL":
            recs.append((x.START_DATE, x.END_DATE, x.SECONDARY_TLF, x.TRANSMISSIONLOSSFACTOR, 0))
        elif x.DISPATCHTYPE == "GENERATOR":
            recs.append((x.START_DATE, x.END_DATE, x.TRANSMISSIONLOSSFACTOR, np.nan, 1))
        elif x.DISPATCHTYPE == "LOAD":
            recs.append((x.START_DATE, x.END_DATE, np.nan, x.TRANSMISSIONLOSSFACTOR, 1))
    recs = pd.DataFrame(recs, columns=["start", "end", "gen", "load", "priority"])  # BDU records win overlaps
    cuts = sorted(set(recs["start"]) | set(recs["end"]))
    rows = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        cover = recs[(recs["start"] <= a) & (recs["end"] >= b)].sort_values("priority")
        if cover.empty:
            continue
        gen, load = cover["gen"].dropna(), cover["load"].dropna()
        if gen.empty or load.empty:
            raise ValueError(f"{station_id}: no {'generation' if gen.empty else 'load'} MLF for {a}..{b}")
        rows.append((a, b, float(gen.iloc[0]), float(load.iloc[0])))
    out = pd.DataFrame(rows, columns=["start", "end", "mlf_gen", "mlf_load"])
    # merge adjacent segments with identical values
    same = (out["mlf_gen"] == out["mlf_gen"].shift()) & (out["mlf_load"] == out["mlf_load"].shift())
    out["block"] = (~same).cumsum()
    return (out.groupby("block").agg(start=("start", "first"), end=("end", "last"), mlf_gen=("mlf_gen", "first"),
                                     mlf_load=("mlf_load", "first")).reset_index(drop=True))


@dataclass(frozen=True)
class MlfSeries:
    gen: np.ndarray
    load: np.ndarray
    backfilled: np.ndarray  # True where the station had no record yet (earliest MLFs used)


def mlf_series(schedule: pd.DataFrame, interval_end: pd.Series | pd.DatetimeIndex) -> MlfSeries:
    """MLFs for each interval, looked up by the interval's start time."""
    start = pd.DatetimeIndex(interval_end) - pd.Timedelta(minutes=5)
    s = schedule.sort_values("start").reset_index(drop=True)
    i = np.searchsorted(s["start"].to_numpy(), start.to_numpy(), side="right") - 1
    backfilled = i < 0
    i = np.maximum(i, 0)
    if (start[~backfilled] >= s["end"].to_numpy()[i[~backfilled]]).any():
        raise ValueError("gap in MLF schedule")
    return MlfSeries(s["mlf_gen"].to_numpy()[i], s["mlf_load"].to_numpy()[i], backfilled)
