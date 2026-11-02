"""Battery asset and cost configuration shared by every strategy (LP, MPC, RL)."""

from pydantic import BaseModel, computed_field

INTERVAL_H = 5 / 60  # NEM dispatch interval in hours


class BatteryConfig(BaseModel):
    power_mw: float = 100.0
    duration_h: float = 2.0
    rte: float = 0.90  # round-trip efficiency, split sqrt(rte) on charge and on discharge
    soc_min: float = 0.05
    soc_max: float = 0.95
    soc_init: float = 0.5
    # Per-interval MLFs come from this station's AEMO registration records (rbit.market.mlf).
    # Default: Riverina 1 BESS (RESS1), the NSW 2 h reference asset. None = use the scalars below.
    mlf_station: str | None = "RESS1"
    mlf_gen: float = 1.0  # scalar MLF on discharge (generation) when mlf_station is None
    mlf_load: float = 1.0  # scalar MLF on charge (load) when mlf_station is None
    charge_fee: float = 0.0  # $/MWh charged (network/market fees), off by default
    # $/MWh discharged. A$15 = cycle-driven share of LFP energy-block cost (~A$120-150k/MWh over
    # 5,400-7,200 MWh discharged per MWh), range A$10-20; see the M2 report.
    degradation_cost: float = 15.0

    @computed_field
    @property
    def energy_mwh(self) -> float:
        return self.power_mw * self.duration_h

    @property
    def eta(self) -> float:
        return self.rte**0.5

    @property
    def e_min(self) -> float:
        return self.soc_min * self.energy_mwh

    @property
    def e_max(self) -> float:
        return self.soc_max * self.energy_mwh

    @property
    def e_init(self) -> float:
        return self.soc_init * self.energy_mwh
