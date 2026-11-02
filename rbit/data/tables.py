"""Specs for the MMSDM tables we ingest.

Each spec says where the table lives in the monthly MMSDM archive, how its files
are named (both the pre-Aug-2024 ``PUBLIC_DVD_*`` and the later
``PUBLIC_ARCHIVE#*`` schemes), which source columns we keep and what they are
called in our canonical schema.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    name: str  # canonical table name (data/clean/<name>/)
    mms_table: str  # AEMO table name, e.g. DISPATCHPRICE
    folder: str  # DATA | P5MIN_ALL_DATA | PREDISP_ALL_DATA
    old_marker: str  # in PUBLIC_DVD_<TABLE><old_marker>_<date>.zip (e.g. "_ALL"; "" if none)
    new_marker: str  # in PUBLIC_ARCHIVE#<TABLE><new_marker>#FILEnn#<date>.zip (e.g. "#ALL")
    columns: dict[str, str]  # source column -> canonical column
    key: tuple[str, ...]  # canonical key columns (unique after cleaning)

    def file_regex(self) -> re.Pattern[str]:
        t = re.escape(self.mms_table)
        old = rf"PUBLIC_DVD_{t}{re.escape(self.old_marker)}_\d{{12}}"
        new = rf"PUBLIC_ARCHIVE#{t}{re.escape(self.new_marker)}#FILE\d+#\d{{12}}"
        return re.compile(rf"^(?:{old}|{new})\.zip$", re.IGNORECASE)


# Source columns common to every table we read.
_COMMON = {"REGIONID": "region", "INTERVENTION": "intervention", "LASTCHANGED": "lastchanged"}

DISPATCH_PRICE = TableSpec(
    name="dispatch_price",
    mms_table="DISPATCHPRICE",
    folder="DATA",
    old_marker="",
    new_marker="",
    columns=_COMMON
    | {
        "SETTLEMENTDATE": "interval_end",
        "RRP": "rrp",
        "APCFLAG": "apc_flag",
        "MARKETSUSPENDEDFLAG": "market_suspended",
        "PRICE_STATUS": "price_status",
    },
    key=("interval_end",),
)

DISPATCH_REGIONSUM = TableSpec(
    name="dispatch_regionsum",
    mms_table="DISPATCHREGIONSUM",
    folder="DATA",
    old_marker="",
    new_marker="",
    columns=_COMMON
    | {
        "SETTLEMENTDATE": "interval_end",
        "TOTALDEMAND": "total_demand",
        "DEMANDFORECAST": "demand_forecast",
        "AVAILABLEGENERATION": "available_generation",
        "NETINTERCHANGE": "net_interchange",
        "SS_SOLAR_UIGF": "ss_solar_uigf",
        "SS_WIND_UIGF": "ss_wind_uigf",
    },
    key=("interval_end",),
)

P5MIN_REGION = TableSpec(
    name="p5min_region",
    mms_table="P5MIN_REGIONSOLUTION",
    folder="P5MIN_ALL_DATA",
    old_marker="_ALL",
    new_marker="#ALL",
    columns=_COMMON
    | {
        "RUN_DATETIME": "run_datetime",
        "INTERVAL_DATETIME": "interval_end",
        "RRP": "rrp",
        "TOTALDEMAND": "total_demand",
        "DEMANDFORECAST": "demand_forecast",
        "NETINTERCHANGE": "net_interchange",
        "SS_SOLAR_UIGF": "ss_solar_uigf",
        "SS_WIND_UIGF": "ss_wind_uigf",
    },
    key=("run_datetime", "interval_end"),
)

PREDISPATCH_PRICE = TableSpec(
    name="predispatch_price",
    mms_table="PREDISPATCHPRICE",
    folder="PREDISP_ALL_DATA",
    old_marker="",
    new_marker="#ALL",
    columns=_COMMON
    | {
        "PREDISPATCHSEQNO": "seqno",
        "RUNNO": "runno",
        "PERIODID": "periodid",
        "DATETIME": "interval_end",
        "RRP": "rrp",
    },
    key=("seqno", "runno", "interval_end"),
)

PREDISPATCH_REGIONSUM = TableSpec(
    name="predispatch_regionsum",
    mms_table="PREDISPATCHREGIONSUM",
    folder="PREDISP_ALL_DATA",
    old_marker="",
    new_marker="#ALL",
    columns=_COMMON
    | {
        "PREDISPATCHSEQNO": "seqno",
        "RUNNO": "runno",
        "PERIODID": "periodid",
        "DATETIME": "interval_end",
        "TOTALDEMAND": "total_demand",
        "DEMANDFORECAST": "demand_forecast",
        "NETINTERCHANGE": "net_interchange",
        "SS_SOLAR_UIGF": "ss_solar_uigf",
        "SS_WIND_UIGF": "ss_wind_uigf",
    },
    key=("seqno", "runno", "interval_end"),
)

TABLES: dict[str, TableSpec] = {
    t.name: t
    for t in (DISPATCH_PRICE, DISPATCH_REGIONSUM, P5MIN_REGION, PREDISPATCH_PRICE, PREDISPATCH_REGIONSUM)
}
