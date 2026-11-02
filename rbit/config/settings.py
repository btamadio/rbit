"""Shared configuration.

All timestamps in rbit are NEM market time (AEST, UTC+10, no daylight saving),
stored as timezone-naive values.
"""

from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel


class DataConfig(BaseModel):
    data_root: Path = Path("data")
    region: str = "NSW1"
    start: str = "2021-10"  # first month (YYYY-MM); 5MS went live 1 Oct 2021
    end: str = "2026-09"  # last month (YYYY-MM) available in the MMSDM archive
    # Decisions for the interval ending at T are made at T - 5min - decision_margin,
    # i.e. before the dispatch run that sets the price we are settled at.
    decision_margin: timedelta = timedelta(seconds=60)
    # Runs older than this at decision time are treated as unavailable (e.g. archive gaps),
    # so a stale path is never served as if it were current.
    max_p5min_age: timedelta = timedelta(minutes=30)
    max_predispatch_age: timedelta = timedelta(hours=3)

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def clean_dir(self) -> Path:
        return self.data_root / "clean"
