"""Read access to the cleaned parquet tables."""

from pathlib import Path

import duckdb
import pandas as pd

from rbit.config import DataConfig
from rbit.data.normalise import dedup
from rbit.data.tables import TABLES


def table_dir(cfg: DataConfig, table: str) -> Path:
    return cfg.clean_dir / table


def month_path(cfg: DataConfig, table: str, year: int, month: int) -> Path:
    return table_dir(cfg, table) / f"{year}{month:02d}.parquet"


def missing_marker(cfg: DataConfig, table: str, year: int, month: int) -> Path:
    """Marker recording that a table-month is absent from the AEMO archive."""
    return table_dir(cfg, table) / f"{year}{month:02d}.missing"


def missing_months(cfg: DataConfig) -> dict[str, list[str]]:
    return {t: sorted(p.stem for p in table_dir(cfg, t).glob("*.missing")) for t in TABLES}


def load(cfg: DataConfig, table: str, start: str | pd.Timestamp | None = None,
         end: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Load a table, optionally restricted to start <= interval_end < end.

    Re-applies dedup because a key can appear in two adjacent monthly files.
    """
    glob = str(table_dir(cfg, table) / "*.parquet")
    where = []
    if start is not None:
        where.append(f"interval_end >= TIMESTAMP '{pd.Timestamp(start)}'")
    if end is not None:
        where.append(f"interval_end < TIMESTAMP '{pd.Timestamp(end)}'")
    sql = f"SELECT * FROM read_parquet('{glob}')" + (f" WHERE {' AND '.join(where)}" if where else "")
    with duckdb.connect() as con:
        df = con.execute(sql).df()
    return dedup(df, TABLES[table].key).sort_values(list(TABLES[table].key)).reset_index(drop=True)
