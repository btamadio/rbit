"""InfoSet: the only door through which models and baselines see market data.

For the dispatch interval ending at T, the decision is made at

    cutoff = T - 5min - decision_margin

i.e. before the dispatch run for T (whose price is published at about T - 5min).
Everything returned has ``available_at < cutoff``. No other module should read
the cleaned tables directly for decision-making.
"""

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from rbit.config import DataConfig
from rbit.data import store

INTERVAL = pd.Timedelta(minutes=5)


def decision_time(interval_end: pd.Timestamp, margin: timedelta) -> pd.Timestamp:
    return pd.Timestamp(interval_end) - INTERVAL - pd.Timedelta(margin)


@dataclass(frozen=True)
class Observation:
    interval_end: pd.Timestamp  # interval we are deciding for (settled at its RRP)
    cutoff: pd.Timestamp  # decision time; all data below has available_at < cutoff
    dispatch_price: pd.DataFrame  # last n_history visible dispatch intervals
    dispatch_regionsum: pd.DataFrame
    p5min: pd.DataFrame  # full path of the latest visible P5MIN run (empty if none or stale)
    predispatch_price: pd.DataFrame  # full path of the latest visible PREDISPATCH run (empty if none or stale)
    predispatch_regionsum: pd.DataFrame


class _History:
    """Interval-indexed table; returns the latest n visible intervals."""

    def __init__(self, df: pd.DataFrame, slack: int = 64):
        self.df = df.sort_values(["available_at", "interval_end"]).reset_index(drop=True)
        self.av = self.df["available_at"].to_numpy()
        self.slack = slack  # extra rows scanned in case of out-of-order publication

    def at(self, cutoff: pd.Timestamp, n: int) -> pd.DataFrame:
        i = int(np.searchsorted(self.av, np.datetime64(cutoff), side="left"))
        window = self.df.iloc[max(0, i - n - self.slack): i]
        return window.sort_values("interval_end").tail(n).reset_index(drop=True)


class _Runs:
    """Run-based table (P5MIN / PREDISPATCH); returns the most recent visible run."""

    def __init__(self, df: pd.DataFrame, run_key: list[str], max_age: timedelta):
        self.max_age = pd.Timedelta(max_age)
        df = df.sort_values(run_key + ["interval_end"]).reset_index(drop=True)
        g = df.groupby(run_key, sort=False)  # df is sorted, so groups come out in run_key order
        sizes = g.size().to_numpy()
        runs = pd.DataFrame({
            "available_at": g["available_at"].max().to_numpy(),
            "run_datetime": g["run_datetime"].first().to_numpy(),
            "stop": np.cumsum(sizes),
        })
        runs["start"] = runs["stop"] - sizes
        runs["order"] = np.arange(len(runs))  # position in run_key order (most recent run = largest)
        runs = runs.sort_values(["available_at", "order"]).reset_index(drop=True)
        self.df = df
        self.av = runs["available_at"].to_numpy()
        # best[j] = most recent run (by run_key order) among the first j+1 runs to be published
        self.best = np.maximum.accumulate(runs["order"].to_numpy())
        by_order = runs.sort_values("order")
        self.run_datetime = by_order["run_datetime"].to_numpy()
        self.start = by_order["start"].to_numpy()
        self.stop = by_order["stop"].to_numpy()

    def at(self, cutoff: pd.Timestamp) -> pd.DataFrame:
        j = int(np.searchsorted(self.av, np.datetime64(cutoff), side="left")) - 1
        if j < 0:
            return self.df.iloc[0:0]
        k = self.best[j]
        if np.datetime64(cutoff) - self.run_datetime[k] > np.timedelta64(self.max_age):
            return self.df.iloc[0:0]  # latest run is stale (e.g. archive gap)
        return self.df.iloc[self.start[k]: self.stop[k]].reset_index(drop=True)


class InfoSet:
    def __init__(self, tables: dict[str, pd.DataFrame], cfg: DataConfig | None = None, n_history: int = 24):
        self.cfg = cfg or DataConfig()
        self.n_history = n_history
        self._dispatch_price = _History(tables["dispatch_price"])
        self._dispatch_regionsum = _History(tables["dispatch_regionsum"])
        c = self.cfg
        self._p5min = _Runs(tables["p5min_region"], ["run_datetime"], c.max_p5min_age)
        self._pd_price = _Runs(tables["predispatch_price"], ["seqno", "runno"], c.max_predispatch_age)
        self._pd_regionsum = _Runs(tables["predispatch_regionsum"], ["seqno", "runno"], c.max_predispatch_age)

    @classmethod
    def from_store(cls, cfg: DataConfig, start: str | pd.Timestamp, end: str | pd.Timestamp,
                   lookback: pd.Timedelta = pd.Timedelta(days=3), **kw) -> "InfoSet":
        """Load the tables needed to answer queries for start <= interval_end < end."""
        lo = pd.Timestamp(start) - lookback
        hi = pd.Timestamp(end) + pd.Timedelta(days=3)  # pre-dispatch paths run ~2 days ahead
        names = ["dispatch_price", "dispatch_regionsum", "p5min_region", "predispatch_price", "predispatch_regionsum"]
        return cls({t: store.load(cfg, t, lo, hi) for t in names}, cfg, **kw)

    def cutoff(self, interval_end: pd.Timestamp) -> pd.Timestamp:
        return decision_time(interval_end, self.cfg.decision_margin)

    def at(self, interval_end: pd.Timestamp) -> Observation:
        t = pd.Timestamp(interval_end)
        c = self.cutoff(t)
        return Observation(
            interval_end=t,
            cutoff=c,
            dispatch_price=self._dispatch_price.at(c, self.n_history),
            dispatch_regionsum=self._dispatch_regionsum.at(c, self.n_history),
            p5min=self._p5min.at(c),
            predispatch_price=self._pd_price.at(c),
            predispatch_regionsum=self._pd_regionsum.at(c),
        )
