# M2b: energy vs FCAS revenue of NSW grid batteries, CY2025

Generated 2026-11-02 15:35 by `python -m rbit.eval.industry`. Method and exclusions:
see the module docstring in `rbit/eval/industry.py`. Estimates from public AEMO data (SCADA, FCAS
enablement, prices, registered MLFs); annualised $/MW of registered max capacity.
**RRP basis** = revenue at the regional price with no loss factors (how PortfolioEnergy reports);
**MLF basis** = after each unit's marginal loss factors (closer to cash settlement).

## Per unit

| DUID | MW | MWh | h | 2 h | Days | MLF gen / load | Energy $/MW (RRP) | Energy $/MW (MLF) | FCAS $/MW | Total $/MW (RRP) | Energy share | Cycles/day | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WTAHB1 | 850 | 1679 | 1.98 | yes | 365 | 0.987 / 0.995 | 3k | 3k | 0k | 3k | 100% | 0.09 | excluded |
| LDBESS1 | 500 | 1086.2 | 2.17 | yes | 93 | 0.958 / 0.964 | -0k | -0k | 0k | -0k | 100% | 0.00 |  |
| ERB01 | 460 | 1770 | 3.85 |  | 303 | 0.988 / 0.991 | -2k | -2k | 0k | -2k | 100% | 0.06 |  |
| ORABESS1 | 415 | 1660 | 4.00 |  | 20 | 0.959 / 0.974 | 0k | 0k | 0k | 0k |  | 0.00 |  |
| CAPBES1 | 100 | 200 | 2.00 | yes | 365 | 0.956 / 1.024 | 98k | 92k | 1k | 99k | 99% | 0.63 |  |
| RIVNB2 | 65 | 130 | 2.00 | yes | 365 | 0.911 / 0.911 | 126k | 114k | 5k | 131k | 96% | 0.71 |  |
| SMTHBES1 | 65 | 130 | 2.00 | yes | 142 | 1.002 / 1.002 | 49k | 49k | 2k | 51k | 97% | 0.35 |  |
| RESS1 | 60 | 120 | 2.00 | yes | 365 | 0.874 / 0.903 | 183k | 159k | 3k | 186k | 99% | 0.98 |  |
| BHB1 | 50 | 50 | 1.00 |  | 365 | 0.871 / 0.889 | 70k | 60k | 0k | 70k | 100% | 0.75 |  |
| LIMBESS1 | 50 | 536 | 10.72 |  | 100 | 0.924 / 0.928 | 7k | 6k | 0k | 7k | 100% | 0.01 |  |
| WALGRV1 | 50 | 78 | 1.56 |  | 365 | 1.001 / 1.001 | 129k | 129k | 23k | 152k | 85% | 0.99 |  |
| DPNTB1 | 25 | 50 | 2.00 | yes | 365 | 0.912 / 0.912 | 131k | 119k | 5k | 136k | 96% | 0.74 |  |
| QBYNB1 | 10 | 20 | 2.00 | yes | 365 | 0.965 / 0.993 | 26k | 24k | 16k | 41k | 62% | 0.29 |  |

Excluded from fleet statistics:

- WTAHB1: Waratah Super Battery: contracted as a System Integrity Protection Scheme and mostly held in reserve (2025 mean |MW| ~8-50 of 850)

## Calibration against PortfolioEnergy's comparison page

- RESS1: RRP basis **186k** vs 190k published (-2%); MLF basis 162k (-15%). Their figures look like the RRP basis.

## NSW 2-hour merchant fleet (1.75–2.25 h, registered all year): CAPBES1, RIVNB2, RESS1, DPNTB1, QBYNB1

- Energy share of energy + FCAS revenue (RRP basis, pooled $): **97.5%**; by unit 62%–99%.
- Claimed ~93% arbitrage share: the estimate is 97.5%, so the 93% figure understates the arbitrage share by 4.5 percentage points.
- Capacity-weighted energy revenue: 125k $/MW/yr (RRP basis), 113k (MLF basis).

FCAS revenue mix of this fleet:

| Service | Share of FCAS $ |
|---|---|
| RAISEREG | 44% |
| LOWERREG | 14% |
| LOWER60SEC | 11% |
| RAISE6SEC | 9% |
| RAISE1SEC | 9% |
| LOWER6SEC | 4% |
| RAISE60SEC | 4% |
| LOWER5MIN | 3% |
| RAISE5MIN | 2% |

## Energy-only comparator for the 217k claim

`217k x 97.5%` = **212k $/MW/yr** on the RRP basis (range 135k–215k with the per-unit shares; 202k at the claimed 93%). Assumes the claimant's revenue mix matches this fleet's.

## Side by side, CY2025, 2 h, energy only, $/MW/yr

B4 on the MLF basis uses Riverina 1's MLFs (M2); on the RRP basis it is the M2 "MLF 1.0" run.

| Strategy | RRP basis | % of B4 | MLF basis (RESS1) | % of B4 |
|---|---|---|---|---|
| B4 perfect-foresight LP | 318k | 100% | 275k | 100% |
| B3 perfect-foresight MPC, 24 h |  |  | 275k | 100% |
| Energy-only comparator (claim x fleet energy share) | 212k | 66% |  |  |
| Riverina 1 actual energy revenue | 183k | 58% | 159k | 58% |
| NSW 2 h merchant fleet actual energy revenue | 125k | 39% | 113k | 41% |
| Industry claim, energy + FCAS (reference) | 217k | 68% | | |

B3 was only run on the MLF basis. B2 (pre-dispatch MPC) and RL rows are added from M3 / M6.
