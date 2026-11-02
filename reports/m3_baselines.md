# M3: baselines (NSW1, 2 h, energy only, Riverina 1 MLFs)

Generated 2026-11-02 15:51 by `python -m rbit.eval.baselines`. Gross energy revenue,
$/MW/yr, same asset and settlement as M2 (`BatteryConfig()` defaults).

- **B1** time-of-day rule: charge from 11:00 and discharge from 17:00 for
  2 h at full power; tuned on 2022–2023 (in-sample there).
- **B2** pre-dispatch MPC: 15 h rolling LP on P5MIN then PREDISPATCH prices as published,
  read through InfoSet (decision 1 min before the dispatch run), first action executed, settled at actual RRP.
- **B3 / B4** from `reports/m2_perfect_foresight.csv` (perfect foresight).

| Year | B1 | B2 | B3 | B4 | B1 / B3 | B2 / B3 | B1 cycles/day | B2 cycles/day | B2 padded steps |
|---|---|---|---|---|---|---|---|---|---|
| 2022 | 121k | 129k | 246k | 246k | 49% | **52%** | 0.85 | 2.70 | 8,898 |
| 2023 | 128k | 132k | 228k | 228k | 56% | **58%** | 0.85 | 2.87 | 0 |
| 2024 | 210k | 235k | 428k | 428k | 49% | **55%** | 0.85 | 2.98 | 0 |
| 2025 | 129k | 164k | 275k | 275k | 47% | **60%** | 0.85 | 2.46 | 0 |

Padded steps: decisions where pre-dispatch did not cover the horizon and the last price was held
(archive gap: PREDISPATCH 2022-10).
