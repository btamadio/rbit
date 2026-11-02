"""Pre-dispatch gap model (M3b, variant F4): learns actual RRP minus the pre-dispatch price path.

At an issue time the model sees only InfoSet data (the P5MIN/PREDISPATCH path and recent dispatch
prices) and predicts, for each 5-minute step of the path, the expected gap to the price that will
settle. Squared-error loss, because the MPC is risk-neutral and needs the conditional mean.

Uses scikit-learn's HistGradientBoostingRegressor (LightGBM-style histogram boosting; LightGBM itself
needs a system OpenMP on macOS).
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from rbit.baselines import B2_HORIZON, predispatch_path
from rbit.data.infoset import InfoSet, Observation

FIVE = pd.Timedelta(minutes=5)
FEATURES = ["raw", "h", "last", "mean_1h", "raw0_minus_last", "hour", "weekday", "month"]


def features(obs: Observation, raw: np.ndarray) -> pd.DataFrame:
    """One row per path step; all inputs are known at obs.cutoff."""
    hist = obs.dispatch_price["rrp"].to_numpy()
    last = hist[-1] if len(hist) else raw[0]
    target = pd.date_range(obs.interval_end, periods=len(raw), freq=FIVE) - FIVE  # interval start
    return pd.DataFrame({
        "raw": raw,
        "h": np.arange(len(raw)),
        "last": last,
        "mean_1h": hist[-12:].mean() if len(hist) else raw[0],
        "raw0_minus_last": raw[0] - last,
        "hour": target.hour + target.minute / 60,
        "weekday": target.day_of_week,
        "month": target.month,
    }, index=target + FIVE)


def issue_times(ends: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Every 30 minutes, aligned with PREDISPATCH runs (interval starting on :00 / :30)."""
    ends = pd.DatetimeIndex(ends)
    return ends[(ends - FIVE).minute % 30 == 0]


def training_rows(info: InfoSet, actual: pd.Series, times: pd.DatetimeIndex, horizon: int = B2_HORIZON,
                  step: int = 1) -> pd.DataFrame:
    """Features + target (actual - raw) for each issue time; skips padded paths and unknown actuals."""
    frames = []
    for t in times:
        obs = info.at(t)
        raw, padded = predispatch_path(obs, horizon)
        if padded:
            continue
        f = features(obs, raw).iloc[::step]
        f["target"] = actual.reindex(f.index).to_numpy() - f["raw"].to_numpy()
        frames.append(f.dropna(subset=["target"]))
    return pd.concat(frames)


def fit(rows: pd.DataFrame, seed: int = 0) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(loss="squared_error", max_iter=300, learning_rate=0.05,
                                          max_leaf_nodes=63, min_samples_leaf=200, random_state=seed)
    return model.fit(rows[FEATURES], rows["target"])


class GapCorrector:
    """``adjust`` hook for run_predispatch_mpc: refreshes the correction every 30 min and holds it.

    Between refreshes the fresh pre-dispatch path is used and the held correction is added by target
    interval (steps past the held forecast's end get no correction).
    """

    def __init__(self, model: HistGradientBoostingRegressor):
        self.model = model
        self.corr = pd.Series(dtype=float)

    def __call__(self, obs: Observation, path: np.ndarray) -> np.ndarray:
        t = obs.interval_end
        if (t - FIVE).minute % 30 == 0 or self.corr.empty:
            f = features(obs, path)
            self.corr = pd.Series(self.model.predict(f[FEATURES]), index=f.index)
        targets = pd.date_range(t, periods=len(path), freq=FIVE)
        return path + self.corr.reindex(targets).fillna(0.0).to_numpy()
