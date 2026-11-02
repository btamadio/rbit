# M2: perfect-foresight benchmarks (NSW1, energy only)

Generated 2026-11-02 15:11 by `python -m rbit.eval.perfect_foresight`.

Gross energy revenue per MW of rated power per calendar year, settled at actual 5-minute RRP.
Base asset: 100 MW, SoC 5–95%, RTE 88%, no fees, no degradation cost, and Riverina 1 BESS (RESS1)
MLFs by date from AEMO registration data (DUDETAILSUMMARY); see the MLF table below.
B4 = full-year LP (perfect foresight, terminal SoC ≥ initial). B3 = rolling MPC on actual prices,
24 h horizon, re-solved every interval. Both: no discharge at negative prices (see `rbit/optim/lp.py`).
B3 can edge above B4: it may end the year at a lower SoC and plans with prices past 31 Dec,
while B4 must finish at or above its starting SoC.

## $/MW/yr by year and duration

| Year | Duration | B4 full-horizon LP | B3 rolling MPC (24 h) | B3 / B4 | B4 cycles/day | B3 cycles/day |
|---|---|---|---|---|---|---|
| 2022 | 1 h | 187k | 187k | 100.0% | 5.00 | 5.00 |
| 2022 | 2 h | 238k | 238k | 100.0% | 2.93 | 2.93 |
| 2022 | 4 h | 297k | 297k | 100.0% | 1.69 | 1.69 |
| 2023 | 1 h | 178k | 178k | 100.0% | 5.48 | 5.48 |
| 2023 | 2 h | 223k | 223k | 100.0% | 3.21 | 3.21 |
| 2023 | 4 h | 273k | 273k | 100.0% | 1.86 | 1.86 |
| 2024 | 1 h | 322k | 322k | 100.0% | 5.93 | 5.93 |
| 2024 | 2 h | 422k | 422k | 100.0% | 3.43 | 3.43 |
| 2024 | 4 h | 515k | 515k | 100.0% | 1.98 | 1.98 |
| 2025 | 1 h | 206k | 206k | 100.0% | 4.79 | 4.79 |
| 2025 | 2 h | 271k | 271k | 100.0% | 2.90 | 2.90 |
| 2025 | 4 h | 361k | 361k | 100.0% | 1.77 | 1.77 |

## First check against the $217k/MW claim (2025, 2 h)

- B4 271k and B3 271k $/MW/yr, energy only, perfect foresight.
- The claim (217k) is energy + FCAS with no foresight, so it is 80% of B3 and 80% of B4 on this basis.
- Caveats: no degradation cost, price-taker, no network constraints. The energy-only comparator
  comes in M2b.

## Marginal loss factors (Riverina 1 BESS, RESS1) and their effect, B4 2 h

Time-weighted mean MLFs over the year. RESS1 was registered on 2023-05-23; earlier intervals use its
first published MLFs (FY2022-23: gen 0.9286, load 0.9311), shown as the back-filled share.

| Year | Gen MLF | Load MLF | Back-filled | B4 at MLF 1.0 | B4 at RESS1 MLFs | Change |
|---|---|---|---|---|---|---|
| 2022 | 0.9286 | 0.9311 | 100% | 257k | 238k | -7.4% |
| 2023 | 0.9187 | 0.9166 | 39% | 243k | 223k | -8.0% |
| 2024 | 0.8894 | 0.8839 | 0% | 474k | 422k | -11.1% |
| 2025 | 0.8742 | 0.9030 | 0% | 313k | 271k | -13.5% |

## Sensitivities (2025, 2 h)

| Case | Benchmark | Revenue $/MW/yr | Net of degradation $/MW/yr | Cycles/day |
|---|---|---|---|---|
| B3 horizon 48 h | B3 | 271k | 271k | 2.90 |
| RTE 85% | B3 | 265k | 265k | 2.65 |
| RTE 85% | B4 | 265k | 265k | 2.65 |
| RTE 90% | B3 | 275k | 275k | 3.08 |
| RTE 90% | B4 | 275k | 275k | 3.08 |
| degradation $10/MWh | B3 | 269k | 252k | 2.24 |
| degradation $10/MWh | B4 | 269k | 252k | 2.23 |
| degradation $20/MWh | B3 | 264k | 238k | 1.79 |
| degradation $20/MWh | B4 | 264k | 238k | 1.79 |
