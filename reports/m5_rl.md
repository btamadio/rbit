# M5: SAC agent, validation year 2024 (NSW1, 2 h, Riverina 1 MLFs, A$15/MWh degradation)

Generated 2026-11-02 18:59 by `python -m rbit.rl`. SB3 SAC, default hyperparameters,
gamma 0.997, 1,000,000 steps per seed, trained on 2021-10 – 2023-12 (3-day episodes, random start
and SoC). The 2024 policy was evaluated every 100,000 steps; the best checkpoint by 2024 net is
reported, so the SAC figures are selected on 2024 and slightly optimistic. 2025 was not used.

| Strategy | Gross $/MW/yr | Net $/MW/yr | Cycles/day |
|---|---|---|---|
| B1 | 210k | 201k | 0.85 |
| B2 | 235k | 213k | 2.04 |
| B3 | 422k | 395k | 2.46 |
| **SAC** (best checkpoint per seed, mean ± std over 3) | 173k ± 17k | **159k ± 17k** | 1.24 |

**M5 gate (SAC net > B1 net): FAIL.** SAC net is 75% of B2 and 40% of B3.

## Best checkpoint per seed

| Seed | Steps | Gross | Net | Cycles/day |
|---|---|---|---|---|
| 0 | 600,000 | 156k | 143k | 1.24 |
| 1 | 1,000,000 | 191k | 177k | 1.23 |
| 2 | 1,000,000 | 172k | 158k | 1.25 |

Full evaluation history (every checkpoint) is in `reports/m5_rl.csv`.
