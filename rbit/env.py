"""Gymnasium environment for a price-taking battery on one NEM region (PLAN.md section 5).

Step = one 5-minute dispatch interval. Action = target MW as a fraction of rated power in [-1, 1]
(+ discharge), projected onto the feasible set by the shared battery model. Reward = settled energy
revenue net of fees and degradation (shared settlement), divided by ``reward_scale``; raw $ are in
``info``. Observations come only from InfoSet, precomputed once per interval by ``build_market``.

Observation (float32): per-interval market features (see ``FEATURES``) followed by SoC in [0, 1].
"""

import os
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import pandas as pd

from rbit.baselines import predispatch_path
from rbit.battery import project, step
from rbit.config import INTERVAL_H, BatteryConfig, DataConfig
from rbit.data import store
from rbit.data.infoset import InfoSet
from rbit.market import settle
from rbit.market.mlf import load_registration, mlf_schedule, mlf_series

FEATURE_VERSION = 1  # bump when build_market's output changes, to invalidate cached features
N_HISTORY = 24  # past dispatch prices (2 h)
N_P5 = 12  # next 5-min prices (P5MIN, 1 h)
N_PD = 46  # then 30-min prices to 24 h ahead (PREDISPATCH)
FEATURES = (
    [f"rrp_lag{k}" for k in range(N_HISTORY, 0, -1)]
    + [f"p5_{k}" for k in range(N_P5)]
    + [f"pd_{k}" for k in range(N_PD)]
    + ["path_padded", "tod_sin", "tod_cos", "doy_sin", "doy_cos", "weekend", "mlf_gen", "mlf_load"]
)


def price_transform(p: np.ndarray) -> np.ndarray:
    """Signed log for heavy-tailed prices (-1000 .. ~20000 $/MWh -> about -3 .. 6)."""
    return np.arcsinh(np.asarray(p) / 100.0)


@dataclass(frozen=True)
class Market:
    ends: pd.DatetimeIndex  # interval_end of each step
    rrp: np.ndarray  # settled price ($/MWh)
    mlf_gen: np.ndarray
    mlf_load: np.ndarray
    features: np.ndarray  # (n, len(FEATURES)) float32, built only from InfoSet


def build_market(info: InfoSet, ends: pd.DatetimeIndex, rrp: np.ndarray, mlf_gen: np.ndarray,
                 mlf_load: np.ndarray) -> Market:
    ends = pd.DatetimeIndex(ends)
    feats = np.empty((len(ends), len(FEATURES)), dtype=np.float32)
    start = ends - pd.Timedelta(minutes=5)
    tod = 2 * np.pi * (start.hour * 60 + start.minute).to_numpy() / 1440
    doy = 2 * np.pi * start.day_of_year.to_numpy() / 365.25
    calendar = np.column_stack([np.sin(tod), np.cos(tod), np.sin(doy), np.cos(doy), start.day_of_week >= 5])
    for i, t in enumerate(ends):
        obs = info.at(t)
        hist = obs.dispatch_price["rrp"].to_numpy()
        hist = np.pad(hist, (N_HISTORY - len(hist), 0), mode="edge") if 0 < len(hist) < N_HISTORY else hist
        if len(hist) == 0:
            hist = np.zeros(N_HISTORY)
        path, padded = predispatch_path(obs, N_P5 + 6 * N_PD)
        fwd = np.concatenate([path[:N_P5], path[N_P5::6]])
        feats[i] = np.concatenate([price_transform(hist), price_transform(fwd), [padded > 0], calendar[i],
                                   [mlf_gen[i], mlf_load[i]]])
    return Market(ends, np.asarray(rrp, float), np.asarray(mlf_gen, float), np.asarray(mlf_load, float), feats)


def load_market(data_cfg: DataConfig, cfg: BatteryConfig, start: str | pd.Timestamp, end: str | pd.Timestamp,
                ) -> Market:
    """Market for start < interval_end <= end, with MLFs of cfg.mlf_station (or cfg's scalars).

    Cached in data/features/ (building costs ~1.5 ms/interval, ~2.5 min/year).
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    mlf = cfg.mlf_station or f"mlf{cfg.mlf_gen:g}-{cfg.mlf_load:g}"
    cache = (data_cfg.data_root / "features"
             / f"{data_cfg.region}_{mlf}_{start:%Y%m%d%H%M}_{end:%Y%m%d%H%M}_v{FEATURE_VERSION}.npz")
    if cache.exists():
        z = np.load(cache)
        return Market(pd.DatetimeIndex(z["ends"]), z["rrp"], z["mlf_gen"], z["mlf_load"], z["features"])
    df = store.load(data_cfg, "dispatch_price", pd.Timestamp(start) + pd.Timedelta(minutes=5),
                    pd.Timestamp(end) + pd.Timedelta(minutes=5))
    ends = pd.DatetimeIndex(df["interval_end"])
    if cfg.mlf_station is None:
        gen, load = np.full(len(ends), cfg.mlf_gen), np.full(len(ends), cfg.mlf_load)
    else:
        m = mlf_series(mlf_schedule(load_registration(data_cfg), cfg.mlf_station), ends)
        gen, load = m.gen, m.load
    info = InfoSet.from_store(data_cfg, ends[0], ends[-1])
    m = build_market(info, ends, df["rrp"].to_numpy(), gen, load)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f"{cache.stem}.{os.getpid()}.tmp.npz")  # write then rename: readers never see a partial file
    np.savez(tmp, ends=m.ends.to_numpy(), rrp=m.rrp, mlf_gen=m.mlf_gen, mlf_load=m.mlf_load, features=m.features)
    tmp.replace(cache)
    return m


class BatteryEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, cfg: BatteryConfig, market: Market, episode_steps: int | None = 3 * 288,
                 reward_scale: float | None = None, random_soc: bool = False):
        """``episode_steps=None`` runs the whole market once from its start (evaluation).

        ``random_soc`` draws the initial SoC uniformly over the usable range (training).
        """
        self.random_soc = random_soc
        self.cfg, self.market = cfg, market
        n = len(market.ends)
        self.episode_steps = n if episode_steps is None else min(episode_steps, n)
        # $ per step for full power at $100/MWh, so typical rewards are O(1)
        self.reward_scale = reward_scale or cfg.power_mw * INTERVAL_H * 100.0
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(1,), dtype=np.float32)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, shape=(len(FEATURES) + 1,), dtype=np.float32)
        self._i = self._t0 = 0
        self._e = cfg.e_init

    def _obs(self) -> np.ndarray:
        soc = (self._e - self.cfg.e_min) / (self.cfg.e_max - self.cfg.e_min)
        i = min(self._i, len(self.market.ends) - 1)  # final obs after the last step repeats the last features
        return np.append(self.market.features[i], np.float32(soc)).astype(np.float32)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        options = options or {}
        n = len(self.market.ends)
        if "start" in options:
            self._t0 = int(options["start"])
        elif self.episode_steps == n:
            self._t0 = 0
        else:
            self._t0 = int(self.np_random.integers(0, n - self.episode_steps + 1))
        self._i = self._t0
        # options["soc"]: initial SoC as a fraction of the usable range (same scale as the observation)
        soc = options.get("soc", self.np_random.uniform() if self.random_soc else None)
        self._e = self.cfg.e_init if soc is None else self.cfg.e_min + soc * (self.cfg.e_max - self.cfg.e_min)
        return self._obs(), {"interval_end": self.market.ends[self._i]}

    def step(self, action):
        m, i, cfg = self.market, self._i, self.cfg
        requested = float(np.clip(np.asarray(action).reshape(-1)[0], -1.0, 1.0)) * cfg.power_mw
        mw = project(cfg, self._e, requested)
        self._e = min(max(step(cfg, self._e, mw), cfg.e_min), cfg.e_max)
        s = settle(cfg, m.rrp[i: i + 1], np.array([mw]), m.mlf_gen[i: i + 1], m.mlf_load[i: i + 1])
        net = float(s.net[0])
        info = {"interval_end": m.ends[i], "mw": mw, "requested_mw": requested, "revenue": float(s.revenue[0]),
                "net": net, "energy": self._e}
        self._i += 1
        terminated = False
        truncated = self._i - self._t0 >= self.episode_steps or self._i >= len(m.ends)
        return self._obs(), net / self.reward_scale, terminated, truncated, info
