# M2: perfect-foresight benchmarks (NSW1, energy only)

Generated 2026-11-02 15:23 by `python -m rbit.eval.perfect_foresight`.

Gross energy revenue per MW of rated power per calendar year, settled at actual 5-minute RRP.
Base asset: 100 MW, SoC 5–95%, RTE 90%, no fees, no degradation cost, and Riverina 1 BESS (RESS1)
MLFs by date from AEMO registration data (DUDETAILSUMMARY); see the MLF table below.
B4 = full-year LP (perfect foresight, terminal SoC ≥ initial). B3 = rolling MPC on actual prices,
24 h horizon, re-solved every interval. Both: no discharge at negative prices (see `rbit/optim/lp.py`).
B3 can edge above B4: it may end the year at a lower SoC and plans with prices past 31 Dec,
while B4 must finish at or above its starting SoC.

## $/MW/yr by year and duration

| Year | Duration | B4 full-horizon LP | B3 rolling MPC (24 h) | B3 / B4 | B4 cycles/day | B3 cycles/day |
|---|---|---|---|---|---|---|
| 2022 | 1 h | 194k | 194k | 100.0% | 5.42 | 5.42 |
| 2022 | 2 h | 246k | 246k | 100.0% | 3.16 | 3.16 |
| 2022 | 4 h | 306k | 307k | 100.0% | 1.81 | 1.81 |
| 2023 | 1 h | 182k | 182k | 100.0% | 5.88 | 5.88 |
| 2023 | 2 h | 228k | 228k | 100.0% | 3.41 | 3.41 |
| 2023 | 4 h | 279k | 279k | 100.0% | 1.96 | 1.96 |
| 2024 | 1 h | 328k | 328k | 100.0% | 6.33 | 6.33 |
| 2024 | 2 h | 428k | 428k | 100.0% | 3.63 | 3.63 |
| 2024 | 4 h | 521k | 521k | 100.0% | 2.07 | 2.07 |
| 2025 | 1 h | 209k | 209k | 100.0% | 5.15 | 5.15 |
| 2025 | 2 h | 275k | 275k | 100.0% | 3.08 | 3.08 |
| 2025 | 4 h | 366k | 366k | 100.0% | 1.85 | 1.85 |

## First check against the $217k/MW claim (2025, 2 h)

- B4 275k and B3 275k $/MW/yr, energy only, perfect foresight.
- The claim (217k) is energy + FCAS with no foresight, so it is 79% of B3 and 79% of B4 on this basis.
- Caveats: no degradation cost, price-taker, no network constraints. The energy-only comparator
  comes in M2b.

## Marginal loss factors (Riverina 1 BESS, RESS1) and their effect, B4 2 h

Time-weighted mean MLFs over the year. RESS1 was registered on 2023-05-23; earlier intervals use its
first published MLFs (FY2022-23: gen 0.9286, load 0.9311), shown as the back-filled share.

| Year | Gen MLF | Load MLF | Back-filled | B4 at MLF 1.0 | B4 at RESS1 MLFs | Change |
|---|---|---|---|---|---|---|
| 2022 | 0.9286 | 0.9311 | 100% | 266k | 246k | -7.4% |
| 2023 | 0.9187 | 0.9166 | 39% | 248k | 228k | -8.0% |
| 2024 | 0.8894 | 0.8839 | 0% | 481k | 428k | -11.1% |
| 2025 | 0.8742 | 0.9030 | 0% | 318k | 275k | -13.6% |

## Sensitivities (2025, 2 h)

| Case | Benchmark | Revenue $/MW/yr | Net of degradation $/MW/yr | Cycles/day |
|---|---|---|---|---|
| B3 horizon 48 h | B3 | 275k | 275k | 3.08 |
| RTE 85% | B3 | 265k | 265k | 2.65 |
| RTE 85% | B4 | 265k | 265k | 2.65 |
| RTE 88% | B3 | 271k | 271k | 2.90 |
| RTE 88% | B4 | 271k | 271k | 2.90 |
| degradation $10/MWh | B3 | 273k | 256k | 2.35 |
| degradation $10/MWh | B4 | 273k | 256k | 2.35 |
| degradation $20/MWh | B3 | 268k | 240k | 1.86 |
| degradation $20/MWh | B4 | 268k | 240k | 1.86 |
