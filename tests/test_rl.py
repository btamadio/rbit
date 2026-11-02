import numpy as np
import pandas as pd
import pytest

from rbit.config import BatteryConfig
from rbit.env import BatteryEnv
from test_env import _market

sb3 = pytest.importorskip("stable_baselines3")


def test_random_soc_spreads_initial_state():
    env = BatteryEnv(BatteryConfig(mlf_station=None), _market(), episode_steps=100, random_soc=True)
    socs = [env.reset(seed=s)[0][-1] for s in range(20)]
    assert min(socs) < 0.3 and max(socs) > 0.7
    assert env.reset(options={"soc": 0.25})[0][-1] == pytest.approx(0.25)


def test_short_training_run_validates_and_saves_best(tmp_path, monkeypatch):
    import rbit.rl as rl
    monkeypatch.setattr(rl, "EVAL_EVERY", 200)
    cfg = BatteryConfig(mlf_station=None)
    train, valid = _market(600, seed=1), _market(300, seed=2)
    env = BatteryEnv(cfg, train, episode_steps=100, random_soc=True)
    model = sb3.SAC("MlpPolicy", env, gamma=rl.GAMMA, device="cpu", seed=0, learning_starts=100)
    cb = rl._Validate(cfg, valid, tmp_path, seed=0)
    model.learn(total_timesteps=400, callback=cb)
    assert [h["steps"] for h in cb.history] == [200, 400]
    on_disk = pd.read_csv(tmp_path / "history.csv")
    assert on_disk["steps"].tolist() == [200, 400]
    assert on_disk["net_per_mw"].tolist() == pytest.approx([h["net_per_mw"] for h in cb.history])
    assert (tmp_path / "best.zip").exists()
    assert np.isfinite(cb.history[0]["net_per_mw"])
