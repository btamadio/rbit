# M3b stage 1: pre-dispatch gap model (F4), CY2024

Generated 2026-11-02 16:30 by `python -m rbit.eval.forecast`. Gradient-boosted
model of (actual RRP − pre-dispatch path price), trained on 2022–2023 issue
times every 30 min (2,013,420 rows, every 3rd step), features: raw, h, last, mean_1h, raw0_minus_last, hour, weekday, month.
Evaluation year never seen in training. Errors in $/MWh against the price that settled.

## Forecast accuracy (path built from P5MIN then PREDISPATCH)

| Horizon | MAE raw | MAE F4 | RMSE raw | RMSE F4 | Bias raw | Bias F4 |
|---|---|---|---|---|---|---|
| 0–1 h | 93.5 | 71.9 | 926 | 633 | -39.8 | +12.4 |
| 1–4 h | 185.0 | 88.0 | 1,523 | 697 | -129.8 | +6.7 |
| 4–15 h | 247.9 | 102.5 | 1,803 | 754 | -185.4 | +12.6 |

## Value in the MPC (2 h, Riverina 1 MLFs, `BatteryConfig()` defaults)

| Strategy | Gross $/MW/yr | Net $/MW/yr | Cycles/day |
|---|---|---|---|
| B2 pre-dispatch MPC | 235k | 213k | 2.04 |
| B2-F4 pre-dispatch + gap correction | 210k | 187k | 2.15 |

**Net change from the correction: -26,207 $/MW/yr (-12.3%).**
