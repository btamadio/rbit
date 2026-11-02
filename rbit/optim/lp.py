"""Price-taker battery scheduling LP (HiGHS) and a hot-started rolling-horizon MPC.

Variables per interval t: charge c_t, discharge d_t (grid-side MW, both >= 0) and stored
energy e_t at the end of t. Energy balance: e_t = e_{t-1} + eta*dt*c_t - dt/eta*d_t.
Objective: maximise sum_t dt * [(rrp*MLF_gen - degradation) d_t - (rrp*MLF_load + fee) c_t].

A pure LP can charge and discharge in the same interval to burn energy at negative prices,
which a real battery cannot do. Two guards:
1. Discharge is not allowed in intervals with a negative price (exporting there only costs
   money). This removes the exploit at its source. It also rules out the rare "pay to discharge
   now to make room for a more negative price later", so B3/B4 are very slightly conservative.
2. Any remaining simultaneous interval (possible e.g. with MLF_gen > MLF_load) gets a binary
   and the problem is re-solved as a MILP until no interval does both.
"""

from dataclasses import dataclass

import highspy
import numpy as np

from rbit.battery import project, step
from rbit.config import INTERVAL_H, BatteryConfig

_SIM_TOL = 1e-3  # MW; c and d both above this counts as simultaneous charge/discharge (above MIP noise)
# Tiny throughput cost ($/MWh) that breaks ties against pointless simultaneous charge/discharge when
# stored energy has zero marginal value. Not part of the reported objective.
_TIE_BREAK = 1e-3


@dataclass(frozen=True)
class Schedule:
    mw: np.ndarray  # net grid power per interval (+ discharge, - charge)
    energy: np.ndarray  # stored energy at the end of each interval (MWh)
    objective: float  # LP objective value ($, net of fees and degradation)
    n_binary: int  # intervals that needed a binary to stop simultaneous charge/discharge


def _mlfs(cfg: BatteryConfig, mlf_gen, mlf_load):
    return (cfg.mlf_gen if mlf_gen is None else np.asarray(mlf_gen),
            cfg.mlf_load if mlf_load is None else np.asarray(mlf_load))


def _costs(cfg: BatteryConfig, rrp: np.ndarray, mlf_gen=None, mlf_load=None) -> tuple[np.ndarray, np.ndarray]:
    """Minimisation costs for the charge and discharge columns (including the tie-break)."""
    g, ld = _mlfs(cfg, mlf_gen, mlf_load)
    c_cost = (rrp * ld + cfg.charge_fee + _TIE_BREAK) * INTERVAL_H
    d_cost = -(rrp * g - cfg.degradation_cost - _TIE_BREAK) * INTERVAL_H
    return c_cost, d_cost


def _discharge_upper(cfg: BatteryConfig, rrp: np.ndarray) -> np.ndarray:
    return np.where(rrp < 0, 0.0, cfg.power_mw)


def objective(cfg: BatteryConfig, rrp: np.ndarray, c: np.ndarray, d: np.ndarray, mlf_gen=None,
              mlf_load=None) -> float:
    """True schedule value ($): energy revenue net of fees and degradation."""
    g, ld = _mlfs(cfg, mlf_gen, mlf_load)
    return float(np.sum(((rrp * g - cfg.degradation_cost) * d - (rrp * ld + cfg.charge_fee) * c) * INTERVAL_H))


def _build_lp(cfg: BatteryConfig, rrp: np.ndarray, e0: float, terminal_min: float | None, mlf_gen=None,
              mlf_load=None) -> highspy.HighsLp:
    T = len(rrp)
    dt, eta = INTERVAL_H, cfg.eta
    c_cost, d_cost = _costs(cfg, rrp, mlf_gen, mlf_load)
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = 3 * T, T
    lp.col_cost_ = np.concatenate([c_cost, d_cost, np.zeros(T)])
    e_lo = np.full(T, cfg.e_min)
    if terminal_min is not None:
        e_lo[-1] = max(cfg.e_min, terminal_min)
    lp.col_lower_ = np.concatenate([np.zeros(2 * T), e_lo])
    lp.col_upper_ = np.concatenate([np.full(T, cfg.power_mw), _discharge_upper(cfg, rrp), np.full(T, cfg.e_max)])
    rhs = np.zeros(T)
    rhs[0] = e0
    lp.row_lower_ = rhs
    lp.row_upper_ = rhs.copy()

    t = np.arange(T)
    # column-wise matrix: c_t -> row t; d_t -> row t; e_t -> rows t and t+1
    c_idx, c_val = t, np.full(T, -eta * dt)
    d_idx, d_val = t, np.full(T, dt / eta)
    e_counts = np.where(t < T - 1, 2, 1)
    e_idx = np.empty(e_counts.sum(), dtype=np.int64)
    e_val = np.empty(e_counts.sum())
    pos = np.concatenate([[0], np.cumsum(e_counts)[:-1]])
    e_idx[pos], e_val[pos] = t, 1.0
    nxt = pos[:-1] + 1
    e_idx[nxt], e_val[nxt] = t[:-1] + 1, -1.0
    counts = np.concatenate([np.ones(2 * T, dtype=np.int64), e_counts])
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = np.concatenate([[0], np.cumsum(counts)]).astype(np.int32)
    lp.a_matrix_.index_ = np.concatenate([c_idx, d_idx, e_idx]).astype(np.int32)
    lp.a_matrix_.value_ = np.concatenate([c_val, d_val, e_val])
    return lp


def _new_highs() -> highspy.Highs:
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("mip_rel_gap", 1e-7)
    return h


def _run(h: highspy.Highs) -> np.ndarray:
    h.run()
    status = h.getModelStatus()
    if status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"HiGHS did not solve to optimality: {h.modelStatusToString(status)}")
    return np.asarray(h.getSolution().col_value)


def _add_binaries(h: highspy.Highs, cfg: BatteryConfig, T: int, intervals: np.ndarray) -> None:
    """For each interval: z in {0,1}, c_t <= P z, d_t <= P (1 - z)."""
    P = cfg.power_mw
    for t in intervals:
        h.addVar(0.0, 1.0)
        z = h.getNumCol() - 1
        h.changeColIntegrality(z, highspy.HighsVarType.kInteger)
        h.addRow(-highspy.kHighsInf, 0.0, 2, np.array([t, z], dtype=np.int32), np.array([1.0, -P]))
        h.addRow(-highspy.kHighsInf, P, 2, np.array([T + t, z], dtype=np.int32), np.array([1.0, P]))


def solve_schedule(cfg: BatteryConfig, rrp: np.ndarray, e0: float | None = None,
                   terminal_min: float | None = None, mlf_gen: np.ndarray | None = None,
                   mlf_load: np.ndarray | None = None) -> Schedule:
    """Optimal schedule for a known price path (perfect foresight over ``rrp``).

    Per-interval MLF arrays override the scalar MLFs in ``cfg``.
    """
    rrp = np.asarray(rrp, dtype=float)
    T = len(rrp)
    e0 = cfg.e_init if e0 is None else e0
    h = _new_highs()
    h.passModel(_build_lp(cfg, rrp, e0, terminal_min, mlf_gen, mlf_load))
    x = _run(h)
    fixed: set[int] = set()
    while True:
        c, d = x[:T], x[T: 2 * T]
        both = np.flatnonzero((c > _SIM_TOL) & (d > _SIM_TOL))
        new = [t for t in both if t not in fixed]
        if not new:
            break
        _add_binaries(h, cfg, T, np.array(new))
        fixed.update(new)
        x = _run(h)
    c, d = x[:T], x[T: 2 * T]
    return Schedule(mw=d - c, energy=x[2 * T: 3 * T], objective=objective(cfg, rrp, c, d, mlf_gen, mlf_load),
                    n_binary=len(fixed))


class RollingMPC:
    """Re-solves a fixed-horizon LP each step, reusing the HiGHS model so solves hot-start."""

    def __init__(self, cfg: BatteryConfig, horizon: int):
        self.cfg, self.T = cfg, horizon
        self.h = _new_highs()
        self.h.passModel(_build_lp(cfg, np.zeros(horizon), cfg.e_init, None))
        self.cols = np.arange(2 * horizon, dtype=np.int32)
        self.d_cols = np.arange(horizon, 2 * horizon, dtype=np.int32)
        self.d_lower = np.zeros(horizon)
        self.n_fallback = 0  # plans whose first step needed the MILP fix
        self.n_cold = 0  # hot-started solves that failed and were re-solved from scratch

    def plan(self, rrp: np.ndarray, e0: float, mlf_gen=None, mlf_load=None) -> np.ndarray:
        rrp = np.asarray(rrp, dtype=float)
        if len(rrp) != self.T:  # end of data: one-off solve on the shorter window
            return solve_schedule(self.cfg, rrp, e0, mlf_gen=mlf_gen, mlf_load=mlf_load).mw
        c_cost, d_cost = _costs(self.cfg, rrp, mlf_gen, mlf_load)
        self.h.changeColsCost(2 * self.T, self.cols, np.concatenate([c_cost, d_cost]))
        self.h.changeColsBounds(self.T, self.d_cols, self.d_lower, _discharge_upper(self.cfg, rrp))
        self.h.changeRowBounds(0, e0, e0)
        x = self._run()
        if x[0] > _SIM_TOL and x[self.T] > _SIM_TOL:
            # Only the executed first step must be physical: branch on it (charge-only vs
            # discharge-only) on the same hot model, which is an exact one-binary MILP.
            self.n_fallback += 1
            x = max((self._solve_with_zero(col) for col in (0, self.T)), key=lambda r: r[0])[1]
        return x[self.T: 2 * self.T] - x[: self.T]

    def _run(self) -> np.ndarray:
        try:
            return _run(self.h)
        except RuntimeError:  # rare numerical trouble after many hot starts: drop the basis and retry
            self.n_cold += 1
            self.h.clearSolver()
            return _run(self.h)

    def _solve_with_zero(self, col: int) -> tuple[float, np.ndarray]:
        lp = self.h.getLp()
        upper = lp.col_upper_[col]
        self.h.changeColBounds(col, 0.0, 0.0)
        try:
            x = self._run()
            return -self.h.getInfo().objective_function_value, x
        finally:
            self.h.changeColBounds(col, 0.0, upper)


def run_mpc(cfg: BatteryConfig, rrp: np.ndarray, n_steps: int, horizon: int, resolve_every: int = 1,
            mlf_gen: np.ndarray | None = None, mlf_load: np.ndarray | None = None,
            ) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Rolling-horizon MPC over ``n_steps`` intervals, planning on ``rrp`` (len >= n_steps).

    Each plan is executed through the shared battery model (project + step).
    Returns (executed mw, end-of-interval energy, solver stats).
    """
    mpc = RollingMPC(cfg, horizon)
    e = cfg.e_init
    mw, energy = np.empty(n_steps), np.empty(n_steps)
    for t in range(0, n_steps, resolve_every):
        w = slice(t, t + horizon)
        plan = mpc.plan(rrp[w], e, None if mlf_gen is None else mlf_gen[w], None if mlf_load is None else mlf_load[w])
        for j in range(min(resolve_every, n_steps - t)):
            a = project(cfg, e, plan[j])
            e = min(max(step(cfg, e, a), cfg.e_min), cfg.e_max)
            mw[t + j], energy[t + j] = a, e
    return mw, energy, {"n_fallback": mpc.n_fallback, "n_cold": mpc.n_cold}
