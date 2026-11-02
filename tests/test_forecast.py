import numpy as np
import pandas as pd

from rbit.data.infoset import Observation
from rbit.forecast import FEATURES, GapCorrector, features, issue_times

FIVE = pd.Timedelta(minutes=5)
EMPTY = pd.DataFrame(columns=["interval_end", "rrp"])


def _obs(t, last=50.0):
    disp = pd.DataFrame({"interval_end": [t - FIVE], "rrp": [last]})
    return Observation(t, t, disp, EMPTY, EMPTY, EMPTY, EMPTY)


class _Model:
    """Predicts the issue-time 'last' price for every step, so refreshes are visible."""
    def predict(self, X):
        assert list(X.columns) == FEATURES
        return X["last"].to_numpy()


def test_correction_refreshes_on_the_half_hour_and_is_held_by_target():
    c = GapCorrector(_Model())
    t0 = pd.Timestamp("2024-03-01 12:05")  # interval starting 12:00 -> refresh
    assert (c(_obs(t0, last=10.0), np.zeros(6)) == 10.0).all()
    t1 = t0 + FIVE  # no refresh: held correction, shifted by one step; last step past the held end gets 0
    out = c(_obs(t1, last=99.0), np.zeros(6))
    assert out[:5].tolist() == [10.0] * 5 and out[5] == 0.0
    t2 = pd.Timestamp("2024-03-01 12:35")
    assert (c(_obs(t2, last=99.0), np.zeros(6)) == 99.0).all()


def test_features_and_issue_times():
    t = pd.Timestamp("2024-03-01 12:05")
    f = features(_obs(t), np.arange(4.0))
    assert f.index[0] == t and f["h"].tolist() == [0, 1, 2, 3] and f["hour"].iloc[1] == 12 + 5 / 60
    ends = pd.date_range("2024-03-01 00:05", periods=12, freq=FIVE)
    assert issue_times(ends).tolist() == [pd.Timestamp("2024-03-01 00:05"), pd.Timestamp("2024-03-01 00:35")]
