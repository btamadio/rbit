import numpy as np
import pytest

from rbit.battery import simulate
from rbit.config import INTERVAL_H, BatteryConfig
from rbit.market import settle
from rbit.optim import run_mpc, solve_schedule

CFG = BatteryConfig()


def _prices(n=600, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    p = 80 + 70 * np.sin(2 * np.pi * t / 288) + rng.normal(0, 20, n)
    p[100:130] = -40  # negative-price window
    p[n // 2 + 50] = 9000  # spike
    return p


def test_two_interval_arbitrage_by_hand():
    cfg = BatteryConfig(duration_h=1.0, soc_init=0.05, degradation_cost=0.0)  # start empty
    s = solve_schedule(cfg, np.array([10.0, 100.0]))
    e_in = 100 * INTERVAL_H * cfg.eta  # charge at full power, then discharge what was stored
    d = e_in * cfg.eta / INTERVAL_H
    assert s.mw == pytest.approx([-100.0, d])
    assert s.objective == pytest.approx((100 * d - 10 * 100) * INTERVAL_H)


def test_lp_replay_parity_through_shared_battery_and_settlement():
    """M4 prerequisite: replaying the LP schedule reproduces its objective exactly."""
    for cfg in (CFG, BatteryConfig(mlf_gen=0.97, mlf_load=1.01, charge_fee=2.0, degradation_cost=8.0)):
        p = _prices()
        s = solve_schedule(cfg, p, terminal_min=cfg.e_init)
        mw, e = simulate(cfg, s.mw)
        assert np.abs(mw - s.mw).max() < 1e-6
        assert settle(cfg, p, mw).net.sum() == pytest.approx(s.objective, abs=0.01)
        assert e[-1] >= cfg.e_init - 1e-6


def test_no_simultaneous_charge_discharge_or_discharge_at_negative_price():
    p = _prices()
    p[200:260] = -900  # long deeply negative window with a full battery: tempting to burn energy
    s = solve_schedule(CFG, p)
    assert (s.mw[p < 0] <= 1e-6).all()
    mw, _ = simulate(CFG, s.mw)
    assert settle(CFG, p, mw).net.sum() == pytest.approx(s.objective, abs=0.01)


def test_mlf_exploit_is_blocked_by_binaries():
    cfg = BatteryConfig(mlf_gen=1.10, mlf_load=0.90)  # buying and selling at once would pay at high prices
    p = np.r_[np.full(50, 50.0), np.full(20, 5000.0)]
    s = solve_schedule(cfg, p)
    mw, _ = simulate(cfg, s.mw)
    assert settle(cfg, p, mw).net.sum() == pytest.approx(s.objective, abs=0.01)


def test_mpc_with_full_horizon_matches_lp():
    p = _prices(400)
    lp = solve_schedule(CFG, p)
    mw, _, _ = run_mpc(CFG, p, len(p), horizon=len(p))
    assert settle(CFG, p, mw).net.sum() == pytest.approx(lp.objective, rel=1e-6)


def test_mpc_short_horizon_is_below_lp_and_feasible():
    p = _prices(900, seed=1)
    lp = solve_schedule(CFG, p[:600])
    mw, e, _ = run_mpc(CFG, p, 600, horizon=48)
    v = settle(CFG, p[:600], mw).net.sum()
    assert v <= lp.objective + 1e-6
    assert (e >= CFG.e_min - 1e-9).all() and (e <= CFG.e_max + 1e-9).all()
