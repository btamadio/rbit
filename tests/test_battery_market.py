import numpy as np
import pytest

from rbit.battery import project, simulate, step
from rbit.config import INTERVAL_H, BatteryConfig
from rbit.market import settle

CFG = BatteryConfig()


def test_step_applies_efficiency_on_each_side():
    e = 100.0
    assert step(CFG, e, -100) == pytest.approx(e + 100 * INTERVAL_H * CFG.eta)
    assert step(CFG, e, 100) == pytest.approx(e - 100 * INTERVAL_H / CFG.eta)
    # round trip loses (1 - rte) of the energy charged
    e2 = step(CFG, step(CFG, e, -100), 100 * CFG.rte)
    assert e2 == pytest.approx(e)


def test_project_respects_power_and_energy_limits():
    assert project(CFG, CFG.e_init, 500) == CFG.power_mw
    assert project(CFG, CFG.e_init, -500) == -CFG.power_mw
    assert project(CFG, CFG.e_min, 50) == 0.0
    assert project(CFG, CFG.e_max, -50) == 0.0
    near_empty = CFG.e_min + 1.0  # 1 MWh above floor
    a = project(CFG, near_empty, 100)
    assert step(CFG, near_empty, a) == pytest.approx(CFG.e_min)


def test_simulate_never_leaves_bounds():
    rng = np.random.default_rng(0)
    mw, e = simulate(CFG, rng.uniform(-150, 150, 2000))
    assert (e >= CFG.e_min - 1e-9).all() and (e <= CFG.e_max + 1e-9).all()
    assert (np.abs(mw) <= CFG.power_mw).all()


def test_settlement_mlfs_fees_degradation():
    cfg = BatteryConfig(mlf_gen=0.95, mlf_load=1.02, charge_fee=3.0, degradation_cost=5.0)
    s = settle(cfg, np.array([100.0, 50.0]), np.array([60.0, -60.0]))
    assert s.revenue == pytest.approx([100 * 60 * 0.95 * INTERVAL_H, -50 * 60 * 1.02 * INTERVAL_H])
    assert s.costs == pytest.approx([5 * 60 * INTERVAL_H, 3 * 60 * INTERVAL_H])
