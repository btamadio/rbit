"""M4 exit criterion: replaying the LP schedule through the env reproduces the LP objective."""

import numpy as np
import pandas as pd
import pytest
from gymnasium.utils.env_checker import check_env

from rbit.config import BatteryConfig, DataConfig
from rbit.data import store
from rbit.data.infoset import InfoSet
from rbit.env import FEATURES, N_HISTORY, BatteryEnv, Market, build_market, load_market, price_transform
from rbit.optim import solve_schedule
from test_infoset_no_lookahead import _synthetic


def _market(n=600, seed=0):
    rng = np.random.default_rng(seed)
    p = 80 + 70 * np.sin(np.arange(n) / 40) + rng.normal(0, 25, n)
    p[n // 6: n // 5], p[n * 7 // 12] = -60, 9000
    gen = np.where(np.arange(n) < n // 2, 0.87, 0.95)
    load = np.where(np.arange(n) < n // 2, 0.94, 0.88)
    ends = pd.date_range("2025-01-01 00:05", periods=n, freq="5min")
    return Market(ends, p, gen, load, rng.normal(size=(n, len(FEATURES))).astype(np.float32))


def _replay(env: BatteryEnv, mw: np.ndarray, **reset_options) -> tuple[float, float]:
    env.reset(options={"start": 0} | reset_options)
    net = reward = 0.0
    for a in mw / env.cfg.power_mw:
        _, r, term, trunc, info = env.step(np.array([a], dtype=np.float32))
        net, reward = net + info["net"], reward + r
    assert trunc and not term
    return net, reward


@pytest.mark.parametrize("cfg", [BatteryConfig(mlf_station=None),
                                 BatteryConfig(degradation_cost=8.0, charge_fee=2.0, mlf_station=None)])
def test_lp_schedule_replays_to_the_cent(cfg):
    m = _market()
    lp = solve_schedule(cfg, m.rrp, mlf_gen=m.mlf_gen, mlf_load=m.mlf_load)
    env = BatteryEnv(cfg, m, episode_steps=None)
    net, reward = _replay(env, lp.mw)
    assert net == pytest.approx(lp.objective, abs=0.01)
    assert reward * env.reward_scale == pytest.approx(net)


def test_actions_are_clipped_and_projected():
    cfg = BatteryConfig(mlf_station=None)
    env = BatteryEnv(cfg, _market(50), episode_steps=None)
    env.reset(options={"start": 0, "soc": 1.0})  # full
    _, _, _, _, info = env.step(np.array([-5.0]))
    assert info["requested_mw"] == -cfg.power_mw and info["mw"] == 0.0
    obs, _, _, _, info = env.step(np.array([1.0]))
    assert info["mw"] == cfg.power_mw and 0 < obs[-1] < 1


def test_random_episodes_and_gym_api():
    env = BatteryEnv(BatteryConfig(mlf_station=None), _market(), episode_steps=100)
    check_env(env, skip_render_check=True)
    starts = {env.reset(seed=s)[1]["interval_end"] for s in range(5)}
    assert len(starts) > 1


def test_build_market_features_come_from_infoset():
    tables = _synthetic()
    ends = pd.date_range("2025-03-01 06:05", periods=24, freq="5min")
    info = InfoSet(tables, DataConfig())
    n = len(ends)
    m = build_market(info, ends, np.zeros(n), np.ones(n), np.ones(n))
    assert m.features.shape == (n, len(FEATURES)) and np.isfinite(m.features).all()
    obs = info.at(ends[5])
    assert m.features[5, N_HISTORY - 1] == pytest.approx(price_transform(obs.dispatch_price["rrp"].iloc[-1]))


@pytest.mark.realdata
@pytest.mark.skipif(not any(store.table_dir(DataConfig(), "p5min_region").glob("*.parquet")),
                    reason="cleaned data not ingested")
def test_lp_parity_on_a_real_week():
    cfg = BatteryConfig(mlf_station=None)
    m = load_market(DataConfig(), cfg, "2025-06-01", "2025-06-08")
    lp = solve_schedule(cfg, m.rrp)
    net, _ = _replay(BatteryEnv(cfg, m, episode_steps=None), lp.mw)
    assert net == pytest.approx(lp.objective, abs=0.01)
    assert np.isfinite(m.features).all()


@pytest.mark.skipif(not any(store.table_dir(DataConfig(), "p5min_region").glob("*.parquet")),
                    reason="cleaned data not ingested")
def test_feature_cache_hit_equals_fresh_build(monkeypatch):
    import rbit.env as env_mod
    monkeypatch.setattr(env_mod, "FEATURE_VERSION", 999_999)  # test-only cache file, removed below
    cfg, data_cfg = BatteryConfig(mlf_station=None), DataConfig()
    fresh = load_market(data_cfg, cfg, "2025-06-01", "2025-06-02")
    cache = next((data_cfg.data_root / "features").glob("*_v999999.npz"))
    try:
        cached = load_market(data_cfg, cfg, "2025-06-01", "2025-06-02")
    finally:
        cache.unlink()
    assert (cached.ends == fresh.ends).all()
    for f in ("rrp", "mlf_gen", "mlf_load", "features"):
        np.testing.assert_array_equal(getattr(cached, f), getattr(fresh, f))
