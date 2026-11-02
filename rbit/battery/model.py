"""Battery dynamics. The single source of truth for SoC updates (LP replay, MPC, RL env).

Sign convention: mw > 0 discharges to the grid, mw < 0 charges from the grid.
Energy is stored energy in MWh; efficiency sqrt(rte) applies on each side.
"""

import numpy as np

from rbit.config import INTERVAL_H, BatteryConfig


def step(cfg: BatteryConfig, energy: float, mw: float) -> float:
    """Stored energy after one interval at net grid power ``mw`` (assumed feasible)."""
    if mw >= 0:
        return energy - mw * INTERVAL_H / cfg.eta
    return energy - mw * INTERVAL_H * cfg.eta


def project(cfg: BatteryConfig, energy: float, mw: float) -> float:
    """Closest feasible net power to ``mw`` given power and energy limits."""
    max_dis = min(cfg.power_mw, max(0.0, (energy - cfg.e_min) * cfg.eta / INTERVAL_H))
    max_chg = min(cfg.power_mw, max(0.0, (cfg.e_max - energy) / (cfg.eta * INTERVAL_H)))
    return float(np.clip(mw, -max_chg, max_dis))


def simulate(cfg: BatteryConfig, mw: np.ndarray, energy0: float | None = None,
             tol: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """Replay a net-power schedule. Returns (executed mw, energy at the end of each interval).

    Each action is projected onto the feasible set; a schedule that was feasible stays unchanged
    up to ``tol`` MW of numerical noise.
    """
    e = cfg.e_init if energy0 is None else energy0
    out_mw = np.empty(len(mw))
    out_e = np.empty(len(mw))
    for i, a in enumerate(mw):
        p = project(cfg, e, a)
        if abs(p - a) <= tol:  # keep solver output exactly rather than trimming 1e-9 noise
            p = a
        e = min(max(step(cfg, e, p), cfg.e_min), cfg.e_max)  # clamp only absorbs float noise
        out_mw[i], out_e[i] = p, e
    return out_mw, out_e
