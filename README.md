# rbit

Grid-scale battery arbitrage on Australia's National Electricity Market (NEM): how much of the
perfect-foresight revenue can a realistic strategy capture, settled exactly as AEMO would settle it?

Iteration 1 scope: NSW1, energy only (no FCAS), price-taker, 100 MW / 200 MWh, 90% round-trip
efficiency, A$15/MWh degradation, Riverina 1 BESS marginal loss factors. Full design in [PLAN.md](PLAN.md).

## Results so far (2024, net $/MW/yr)

| Strategy | Net | % of B3 |
|---|---|---|
| B3: rolling MPC on actual prices (perfect foresight) | 395k | 100% |
| B2: rolling MPC on AEMO pre-dispatch prices as published | 213k | 54% |
| B1: time-of-day rule (charge 11:00, discharge 17:00) | 201k | 51% |
| SAC reinforcement learning agent, 3 seeds | 159k ± 17k | 40% |

- Pre-dispatch MPC (B2) is the realistic baseline to beat; RL v1 does not yet beat even the
  time-of-day rule ([reports/m5_rl.md](reports/m5_rl.md), including what wasn't tried).
- A gradient-boosting correction to pre-dispatch halves forecast error but *lowers* MPC revenue 12%
  ([reports/m3b_forecast.md](reports/m3b_forecast.md)).
- The industry figure of A$217k/MW for NSW 2 h batteries is 80% of 2025 perfect-foresight energy
  revenue ([reports/m2b_industry_claim.md](reports/m2b_industry_claim.md)).

Negative results are reported alongside positive ones. All reports are in [reports/](reports/).

## Correctness rules

- **No lookahead.** Every decision sees only data published before its dispatch run
  (`rbit.data.infoset.InfoSet`, with publish timestamps and tests).
- **One settlement.** Every strategy is scored by the same settlement code: 5-minute RRP × MW × MLF,
  minus degradation, from one shared `BatteryConfig`.
- **Parity.** LP schedules replayed through the RL environment match the LP objective to the cent.

## Layout

```
rbit/data/     AEMO MMS archive ingest, cleaning, InfoSet (point-in-time view)
rbit/market/   registration data, MLFs, settlement
rbit/battery/  battery physics
rbit/optim/    LP / MPC
rbit/env.py    Gymnasium environment
rbit/rl.py     SAC training and report
rbit/eval/     benchmark and report CLIs
reports/       generated results
```

## Running

Python ≥ 3.12.

```sh
pip install -e ".[dev]"
python -m rbit.data.ingest            # download and clean NSW1 data into data/
python -m rbit.data.quality           # reports/data_quality_NSW1.md
python -m rbit.eval.perfect_foresight # M2: B3/B4
python -m rbit.eval.industry          # M2b: industry-claim decomposition
python -m rbit.eval.baselines         # M3: B1/B2
python -m rbit.eval.forecast          # M3b: pre-dispatch gap model
python -m rbit.rl                     # M5: SAC (3 seeds x 1M steps, hours on CPU)
pytest
```

## How it's built

rbit is built with a coding-agent workflow (Claude Code). The human sets scope, makes the modelling
calls and reviews the results; agents write most of the code, under these guardrails:

- **Spec first.** [PLAN.md](PLAN.md) defines each milestone and its exit criterion before code is written.
- **Issue → branch → PR.** Work is tracked as GitHub issues; each PR closes one
  (e.g. [#4](https://github.com/btamadio/rbit/issues/4) → [#5](https://github.com/btamadio/rbit/pull/5)).
- **Two-axis review.** Each PR is reviewed by two independent agents, one against the repo's standards
  and one against the spec, and the findings are fixed or deferred in writing.
- **Tests as the contract.** No-lookahead, settlement and env↔LP parity tests have to pass before a result is reported.
- **Honest reports.** Every milestone writes a generated report, including the gates it fails.

Agent conventions for this repo are in [CLAUDE.md](CLAUDE.md) and [docs/agents/](docs/agents/).
