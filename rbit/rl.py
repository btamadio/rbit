"""SAC agent for the battery environment (milestone M5).

    python -m rbit.rl [--seeds 0 1 2] [--steps 1000000]

Trains Stable-Baselines3 SAC (defaults except gamma) on Oct 2021 – Dec 2023 with 3-day episodes from a
random start and random initial SoC. Every EVAL_EVERY steps the deterministic policy runs the full 2024
validation year continuously from the default SoC; the checkpoint with the best 2024 net revenue is kept
in data/models/m5/seed<N>/best.zip, and each evaluation is appended to seed<N>/history.csv as it happens
(so a crashed run keeps its learning curve). 2025 is never touched. Writes reports/m5_rl.{md,csv}.
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import BaseCallback

from rbit.config import BatteryConfig, DataConfig
from rbit.env import BatteryEnv, Market, load_market
from rbit.eval.perfect_foresight import metrics

TRAIN = ("2021-10-01", "2024-01-01")
VALID = ("2024-01-01", "2025-01-01")
GAMMA = 0.997  # ~333-step (28 h) horizon at 5-minute steps
EVAL_EVERY = 100_000


def evaluate(model: SAC, cfg: BatteryConfig, market: Market) -> dict[str, float]:
    """Deterministic policy over the whole market, from the default SoC."""
    env = BatteryEnv(cfg, market, episode_steps=None)
    obs, _ = env.reset(options={"start": 0})
    mw = np.empty(len(market.ends))
    for i in range(len(mw)):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, _, _, info = env.step(action)
        mw[i] = info["mw"]
    return metrics(cfg, market.rrp, mw, market.mlf_gen, market.mlf_load)


class _Validate(BaseCallback):
    def __init__(self, cfg: BatteryConfig, market: Market, out: Path, seed: int):
        super().__init__()
        self.cfg, self.market, self.out, self.seed = cfg, market, out, seed
        self.history: list[dict] = []
        self.best = -np.inf
        self.t0 = time.time()

    def _on_step(self) -> bool:
        if self.num_timesteps % EVAL_EVERY == 0:
            m = evaluate(self.model, self.cfg, self.market)
            row = {"seed": self.seed, "steps": self.num_timesteps,
                   "minutes": round((time.time() - self.t0) / 60, 1)} | m
            self.history.append(row)
            path = self.out / "history.csv"  # one file per seed, so parallel seeds never share a file
            pd.DataFrame([row]).to_csv(path, mode="a", header=not path.exists(), index=False)
            if m["net_per_mw"] > self.best:
                self.best = m["net_per_mw"]
                self.model.save(self.out / "best.zip")
        return True


def train_seed(seed: int, steps: int, data_cfg: DataConfig, out_root: Path) -> list[dict]:
    torch.set_num_threads(2)  # several seeds share the CPU
    cfg = BatteryConfig()
    train = load_market(data_cfg, cfg, *TRAIN)
    valid = load_market(data_cfg, cfg, *VALID)
    out = out_root / f"seed{seed}"
    out.mkdir(parents=True, exist_ok=True)
    env = BatteryEnv(cfg, train, random_soc=True)
    model = SAC("MlpPolicy", env, gamma=GAMMA, device="cpu", seed=seed, verbose=0)
    cb = _Validate(cfg, valid, out, seed)
    model.learn(total_timesteps=steps, callback=cb)
    return cb.history


def _k(x: float) -> str:
    return f"{x / 1000:,.0f}k"


def build_report(hist: pd.DataFrame, baselines: pd.DataFrame, steps: int) -> str:
    best = hist.loc[hist.groupby("seed")["net_per_mw"].idxmax()]
    b = baselines[baselines["year"] == 2024].set_index("benchmark")
    rows = [f"| {name} | {_k(b.loc[name, 'revenue_per_mw'])} | {_k(b.loc[name, 'net_per_mw'])} | "
            f"{b.loc[name, 'cycles_per_day']:.2f} |" for name in ("B1", "B2", "B3")]
    ms = lambda c: f"{_k(best[c].mean())} ± {_k(best[c].std())}"  # noqa: E731
    rows.append(f"| **SAC** (best checkpoint per seed, mean ± std over {len(best)}) | {ms('revenue_per_mw')} | "
                f"**{ms('net_per_mw')}** | {best['cycles_per_day'].mean():.2f} |")
    gate = best["net_per_mw"].mean() > b.loc["B1", "net_per_mw"]
    per_seed = [f"| {int(r.seed)} | {int(r.steps):,} | {_k(r.revenue_per_mw)} | {_k(r.net_per_mw)} | "
                f"{r.cycles_per_day:.2f} |" for r in best.itertuples()]
    return "\n".join([
        "# M5: SAC agent, validation year 2024 (NSW1, 2 h, Riverina 1 MLFs, A$15/MWh degradation)",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.rl`. SB3 SAC, default hyperparameters,",
        f"gamma {GAMMA}, {steps:,} steps per seed, trained on {TRAIN[0][:7]} – 2023-12 (3-day episodes, random start",
        f"and SoC). The 2024 policy was evaluated every {EVAL_EVERY:,} steps; the best checkpoint by 2024 net is",
        "reported, so the SAC figures are selected on 2024 and slightly optimistic. 2025 was not used.",
        "",
        "| Strategy | Gross $/MW/yr | Net $/MW/yr | Cycles/day |",
        "|---|---|---|---|",
        *rows,
        "",
        f"**M5 gate (SAC net > B1 net): {'PASS' if gate else 'FAIL'}.** "
        f"SAC net is {best['net_per_mw'].mean() / b.loc['B2', 'net_per_mw']:.0%} of B2 and "
        f"{best['net_per_mw'].mean() / b.loc['B3', 'net_per_mw']:.0%} of B3.",
        "",
        "## Best checkpoint per seed",
        "",
        "| Seed | Steps | Gross | Net | Cycles/day |",
        "|---|---|---|---|---|",
        *per_seed,
        "",
        "Full evaluation history (every checkpoint) is in `reports/m5_rl.csv`.",
        "",
        "## Not done in this iteration",
        "",
        "PLAN.md section 9 items not yet tried, so this is weak evidence against SAC itself:",
        "",
        "- Behaviour-cloning warm start from B2 schedules",
        "- PPO as a check",
        "- Hyperparameter search (Optuna on validation); gamma and all SAC settings are untuned",
        "- 5+ seeds (3 here) and experiment tracking (MLflow/W&B)",
        "- % of B4, value over B2, revenue by month and time of day, tail diagnostics",
        "- Train/eval mismatch: training uses 3-day episodes from a random SoC, evaluation one continuous year",
        "",
    ])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    ap.add_argument("--steps", type=int, default=1_000_000)
    ap.add_argument("--baselines", type=Path, default=Path("reports") / "m3_baselines.csv")
    ap.add_argument("--out", type=Path, default=Path("reports") / "m5_rl")
    args = ap.parse_args(argv)
    data_cfg = DataConfig()
    out_root = data_cfg.data_root / "models" / "m5"
    # shortcut: best checkpoint is selected on 2024, so 2024 figures are optimistic; add a held-out
    # selection window before M6 compares against B2.
    for period in (TRAIN, VALID):  # build the feature caches once, so seeds only read them
        load_market(data_cfg, BatteryConfig(), *period)
    with ProcessPoolExecutor(max_workers=len(args.seeds)) as pool:
        hists = list(pool.map(train_seed, args.seeds, [args.steps] * len(args.seeds),
                              [data_cfg] * len(args.seeds), [out_root] * len(args.seeds)))
    hist = pd.DataFrame([row for h in hists for row in h])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    hist.to_csv(args.out.with_suffix(".csv"), index=False)
    args.out.with_suffix(".md").write_text(build_report(hist, pd.read_csv(args.baselines), args.steps))
    print(f"wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
