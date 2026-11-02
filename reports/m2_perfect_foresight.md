# M2: perfect-foresight benchmarks (NSW1, energy only)

Generated 2026-11-02 16:20 by `python -m rbit.eval.perfect_foresight`.

Gross energy revenue per MW of rated power per calendar year, settled at actual 5-minute RRP.
Base asset: 100 MW, SoC 5–95%, RTE 90%, no fees, degradation A$15/MWh discharged (optimised net; gross revenue shown, net in the B4 net column) and Riverina 1 BESS (RESS1)
MLFs by date from AEMO registration data (DUDETAILSUMMARY); see the MLF table below.
B4 = full-year LP (perfect foresight, terminal SoC ≥ initial). B3 = rolling MPC on actual prices,
24 h horizon, re-solved every interval. Both: no discharge at negative prices (see `rbit/optim/lp.py`).
B3 can edge above B4: it may end the year at a lower SoC and plans with prices past 31 Dec,
while B4 must finish at or above its starting SoC.

## $/MW/yr by year and duration

| Year | Duration | B4 full-horizon LP | B4 net | B3 rolling MPC (24 h) | B3 / B4 | B4 cycles/day | B3 cycles/day |
|---|---|---|---|---|---|---|---|
| 2022 | 1 h | 189k | 169k | 189k | 100.0% | 3.70 | 3.70 |
| 2022 | 2 h | 241k | 217k | 242k | 100.0% | 2.26 | 2.26 |
| 2022 | 4 h | 302k | 272k | 302k | 100.0% | 1.37 | 1.38 |
| 2023 | 1 h | 177k | 156k | 177k | 100.0% | 3.77 | 3.77 |
| 2023 | 2 h | 223k | 197k | 223k | 100.0% | 2.33 | 2.33 |
| 2023 | 4 h | 273k | 242k | 273k | 100.0% | 1.44 | 1.44 |
| 2024 | 1 h | 322k | 300k | 322k | 100.0% | 3.99 | 3.99 |
| 2024 | 2 h | 422k | 395k | 422k | 100.0% | 2.46 | 2.46 |
| 2024 | 4 h | 515k | 482k | 515k | 100.0% | 1.53 | 1.53 |
| 2025 | 1 h | 204k | 187k | 204k | 100.0% | 3.13 | 3.14 |
| 2025 | 2 h | 270k | 248k | 270k | 100.0% | 2.05 | 2.05 |
| 2025 | 4 h | 361k | 331k | 361k | 100.0% | 1.37 | 1.37 |

## First check against the $217k/MW claim (2025, 2 h)

- B4 270k and B3 270k $/MW/yr, energy only, perfect foresight.
- The claim (217k) is energy + FCAS with no foresight, so it is 80% of B3 and 80% of B4 on this basis.
- Gross revenue, as industry figures are. Caveats: price-taker, no network constraints. The energy-only comparator
  comes in M2b.

## Marginal loss factors (Riverina 1 BESS, RESS1) and their effect, B4 2 h

Time-weighted mean MLFs over the year. RESS1 was registered on 2023-05-23; earlier intervals use its
first published MLFs (FY2022-23: gen 0.9286, load 0.9311), shown as the back-filled share.

| Year | Gen MLF | Load MLF | Back-filled | B4 at MLF 1.0 | B4 at RESS1 MLFs | Change |
|---|---|---|---|---|---|---|
| 2022 | 0.9286 | 0.9311 | 100% | 261k | 241k | -7.6% |
| 2023 | 0.9187 | 0.9166 | 39% | 242k | 223k | -8.2% |
| 2024 | 0.8894 | 0.8839 | 0% | 475k | 422k | -11.3% |
| 2025 | 0.8742 | 0.9030 | 0% | 313k | 270k | -13.8% |

## Sensitivities (2025, 2 h)

| Case | Benchmark | Revenue $/MW/yr | Net of degradation $/MW/yr | Cycles/day |
|---|---|---|---|---|
| B3 horizon 48 h | B3 | 270k | 248k | 2.05 |
| RTE 85% | B3 | 261k | 241k | 1.86 |
| RTE 85% | B4 | 261k | 241k | 1.86 |
| RTE 88% | B3 | 266k | 245k | 1.97 |
| RTE 88% | B4 | 266k | 245k | 1.97 |
| degradation $0/MWh | B3 | 275k | 275k | 3.08 |
| degradation $0/MWh | B4 | 275k | 275k | 3.08 |
| degradation $30/MWh | B3 | 263k | 228k | 1.58 |
| degradation $30/MWh | B4 | 263k | 228k | 1.58 |
