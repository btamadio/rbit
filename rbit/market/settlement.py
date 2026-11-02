"""Energy-market settlement for a price-taking battery (energy only, no FCAS).

Per interval: revenue = RRP x (discharge x MLF_gen - charge x MLF_load) x 5/60.
Costs: charge fees ($/MWh charged) and degradation ($/MWh discharged).
"""

from dataclasses import dataclass

import numpy as np

from rbit.config import INTERVAL_H, BatteryConfig


@dataclass(frozen=True)
class Settlement:
    revenue: np.ndarray  # $ per interval, gross energy revenue
    costs: np.ndarray  # $ per interval, fees + degradation

    @property
    def net(self) -> np.ndarray:
        return self.revenue - self.costs


def settle(cfg: BatteryConfig, rrp: np.ndarray, mw: np.ndarray, mlf_gen: np.ndarray | None = None,
           mlf_load: np.ndarray | None = None) -> Settlement:
    """Settle a schedule. Per-interval MLF arrays override the scalar MLFs in ``cfg``."""
    mw = np.asarray(mw, dtype=float)
    dis = np.maximum(mw, 0.0)
    chg = np.maximum(-mw, 0.0)
    g = cfg.mlf_gen if mlf_gen is None else np.asarray(mlf_gen)
    ld = cfg.mlf_load if mlf_load is None else np.asarray(mlf_load)
    revenue = np.asarray(rrp) * (dis * g - chg * ld) * INTERVAL_H
    costs = (chg * cfg.charge_fee + dis * cfg.degradation_cost) * INTERVAL_H
    return Settlement(revenue, costs)
