# Plan: RL battery arbitrage on the NEM (iteration 1)

## 1. Scope

**In scope (iteration 1)**
- Region: **NSW1** only.
- Market: **energy only**. No FCAS (frequency control services).
- **Price-taker**: the battery's actions don't change the regional reference price (RRP).
- Action: the agent outputs **one number per 5-minute dispatch interval: target MW** (+ = discharge, − = charge).
- Settlement: 5-minute dispatch price, as under five-minute settlement (5MS, live since 1 Oct 2021).
- Deliverables: a trained RL policy, a backtest harness, benchmark results against (a) perfect-foresight optimisation and (b) the $217k/MW industry claim, and a shadow-mode live deployment.

**Out of scope (later iterations)**
- FCAS co-optimisation, price-maker effects, bid stacks and price bands, rebidding, other regions, network constraints, and a fleet/portfolio of batteries.

## 2. Reference asset (configurable)

| Parameter | Default | Notes |
|---|---|---|
| Rated power | 100 MW | Results are reported per MW so they scale |
| Energy | 200 MWh (2 h) | **Fixed at 2 h** to match the claim's NSW 2-hour category. 1 h / 4 h are benchmark sensitivities only |
| Round-trip efficiency | 90% | Split as √RTE for charge and √RTE for discharge |
| SoC limits | 5–95% | |
| Ramp | Full range within one interval | Normal for BESS |
| Degradation | $/MWh throughput cost and/or a daily cycle cap | Must be **identical** across RL and every benchmark |
| MLFs | Riverina 1 BESS (RESS1) generation and load MLFs by date, from AEMO `DUDETAILSUMMARY` | Settlement: `RRP × MW × 5/60 × MLF` |
| Other costs | Optional per-MWh charging network/fees | Off by default, recorded in config |

Every comparison uses **one shared config object**, so RL, the benchmarks and the industry comparison run on the same physics and costs.

## 3. Information timing (the most important correctness rule)

Under the price-taker assumption, a backtest is only meaningful if the agent can't see the price it is settled at.

- The decision for interval *t* may use **only data published before interval *t*'s dispatch run**:
  - actual dispatch prices up to *t−1*
  - the latest **P5MIN** run (5-minute pre-dispatch, about 1 hour ahead)
  - the latest **PREDISPATCH** run (30-minute, to end of the next trading day)
  - error statistics of recent P5MIN/PREDISPATCH runs against actual RRP (computed only from intervals that have already settled)
  - demand and renewable forecasts, the calendar, and SoC
- The agent is then settled at the actual `RRP_t`.
- **P5MIN and PREDISPATCH are not forecasts.** They are AEMO's projected market solutions: NEMDE re-run on the bids, demand forecasts and constraints current at publish time. Implications:
  - they assume no rebids, so they systematically miss late rebidding, especially around price spikes, and they move every run
  - the system treats them as **observed inputs at publish time**, never as unbiased price predictions; their error isn't zero-mean, and the sign and size depend on the regime
  - the agent learns how far to trust them; pre-dispatch MPC (B2) shows what taking them at face value earns
  - a statistical price-forecast model built on top of pre-dispatch is out of scope for iteration 1; it could later be added as both an observation feature and an MPC variant (B2b)
- Build a single `InfoSet(t)` function that returns the observable data, filtering on each record's **publish timestamp** (not its interval timestamp). It's the only way the environment and the pre-dispatch MPC baseline can read market data.
- Add a unit test that fails if any observation contains data published at or after *t*'s dispatch run.

## 4. Data layer

**Sources**
- AEMO NEMWeb / MMSDM archive, read with `nemosis` or a custom loader:
  - `DISPATCHPRICE` (RRP, the price cap/floor intervention flags)
  - `DISPATCHREGIONSUM` (demand)
  - `P5MIN_REGIONSOLUTION`
  - `PREDISPATCHPRICE` / `PREDISPATCHREGIONSUM`
  - rooftop PV and semi-scheduled forecasts as available
- Open Electricity (OpenNEM) API as a cross-check.
- The market price cap / floor for each financial year: the cap is indexed every year, so normalise prices by it.

**Storage**
- Raw files → cleaned Parquet partitioned by table/month → DuckDB for queries.
- Keep `publish_datetime` on every P5MIN / PREDISPATCH / forecast row; section 3 depends on it.

**Quality checks**
- Missing intervals, duplicate runs, intervention pricing, and administered price periods.
- **Pre-5MS data (before Oct 2021)**: settlement was 30-minute and bidding behaviour differed. Use it for pre-training only. Report results on 5MS data only.

**Data splits** (walk-forward, no shuffling)
- Train: Oct 2021 – Dec 2023
- Validation: CY2024
- Test (held out, used once per milestone): **CY2025**, matching the $217k/MW claim period
- Extra out-of-sample check: Jan 2026 to latest available
- Also run a rolling-origin evaluation (train → test on next quarter, repeated) to show the results aren't specific to one year.

## 5. Simulator (Gymnasium environment)

- **Step** = one 5-minute interval. **Episode** = 1–7 days sampled at random from the training period. Evaluation runs the full year continuously, carrying SoC across days.
- **Action**: a continuous value in [−1, 1] × rated MW, **projected onto the feasible set** (SoC and energy limits) inside the environment. The agent can't take infeasible actions. The size of the projection is logged.
- **Observation**:
  - SoC
  - recent RRP history (e.g. last 12–24 intervals)
  - P5MIN price path for the next 12 intervals
  - PREDISPATCH 30-minute price path for the next 24–48 h
  - (from M3b, if it adds value) foundation-model forecast quantiles over the same horizons (section 8)
  - demand and renewable forecasts
  - time of day / day of week / season
  - remaining daily cycle budget (if a cycle cap is used)
- **Price transform**: NEM prices are heavy-tailed (from −$1,000 to about $20k/MWh). Feed the model a signed-log or cap-normalised transform. **Rewards and all reported dollars use raw $.**
- **Reward**: settlement revenue − degradation cost for the interval, scaled for learning. An optional reward-shaping term (e.g. change in SoC valued at the P5MIN pre-dispatch price) is tested only as an ablation.
- **Matching the optimiser**: the environment's settlement and SoC update come from the **same function** the LP uses. Test: replaying the LP's perfect-foresight schedule through the environment reproduces the LP's objective to the cent.

## 6. Benchmarks

Ordered from lower bound to upper bound. All of them use the same asset config, costs and test period.

| # | Benchmark | Purpose |
|---|---|---|
| B0 | Do nothing | Sanity check ($0) |
| B1 | Time-of-day rule (charge during the solar trough, discharge in the evening peak, tuned on train) | Simple floor RL must clearly beat |
| B2 | **Pre-dispatch MPC**: rolling LP each interval, run on the latest P5MIN + PREDISPATCH prices taken as-is, first action executed | The realistic strong baseline. This is what RL has to beat to be worth it |
| B2-F\* | **Forecast MPC**: same as B2 but run on a section 8 foundation-model forecast (median, or quantile scenarios) | Shows what each forecast is worth in dollars, and whether it beats raw pre-dispatch |
| B3 | **Perfect-foresight MPC**: same rolling LP with a 24–48 h horizon on *actual* prices | Upper bound with a realistic horizon |
| B4 | **Perfect-foresight full-horizon LP**: the whole year solved at once on actual prices | Theoretical ceiling |
| B5 | **Industry claim: $217k/MW** | External reference point (see section 7) |

- **Solver**: Pyomo or cvxpy with HiGHS. A one-year 5-minute LP (~105k intervals) solves in seconds to minutes. To prevent simultaneous charge/discharge, either use a small binary or rely on RTE < 1 making it suboptimal (check prices < 0, where it can still pay to do both).
- **Headline metric**: **% of perfect foresight captured** = RL $/MW/yr ÷ B3 (and ÷ B4). Report RL against B2 as the measure of value added.

## 7. Comparing against the $217k/MW claim

**What Portfolio Energy publishes** ([NEM Autobidder](https://portfolioenergy.com/nem-autobidder), [News, 7 Jan 2026](https://portfolioenergy.com/news)):
- About **217 kAUD/MW/yr**, **NSW**, **2-hour category**, **2025 performance cycle**. They describe it as the highest in that category.
- Peers on the same page: Riverina 1 BESS at 190, LF Energy RTC-Tools baseline at 182.
- Their optimiser **co-optimises energy + contingency + regulation FCAS** and works from statistically enhanced AEMO pre-dispatch. So the 217 **includes FCAS**.

**What isn't published:**
- the split between energy and FCAS revenue; the ~93% arbitrage share is **unconfirmed**
- whether 217 is realised settlement or a shadow-mode result
- which DUIDs (individual market units) are included, and whether 217 is gross or net of charging cost and fees
- any independent audit

**Deriving an energy-only comparator from AEMO data** (milestone M2b):
1. For each NSW 2 h BESS DUID in CY2025, compute from MMSDM:
   - energy revenue: `DISPATCHLOAD` MW × RRP × MLF
   - FCAS revenue: enablement × FCAS RRP, by service
2. Check this against Riverina 1's published 190.
3. Take the fleet's FCAS share (with its range across peers) as an empirical test of the ~93% figure.
4. Energy-only comparator = `217 × (1 − FCAS share)`, reported with the peer range.

**Report side by side, all on the same 2 h / RTE / MLF config, for CY2025:**
- the RL agent
- B2 (pre-dispatch MPC)
- B3 (perfect-foresight MPC)
- B4 (perfect-foresight full-horizon LP)
- the energy-only comparator
- 217 itself
- Riverina 1's actual energy-only revenue

**Caveats to state with the results:**
- 217 is a vendor claim
- our agent is a price-taker (an upward bias)
- network constraints are ignored. Modo estimated NSW batteries lost about $3.8k/MW of potential revenue in April 2025 from being constrained off for 15 minutes.

**Sanity check:** if B4 on an energy-only basis lands below the comparator, the claim has a different basis, and we say so explicitly.

## 8. Price forecasting with time-series foundation models

**Goal:** test whether a foundation-model price forecast, built **on top of** pre-dispatch (not instead of it), adds value to the RL agent and the MPC. P5MIN and PREDISPATCH include bid information that no model trained on price history alone can see. Where a forecast model can help is in correcting pre-dispatch's known biases and in giving probability ranges (quantiles).

**Shortlist (the best 3):**

| Model | Why it's on the list | Watch-outs |
|---|---|---|
| **Chronos-2** (Amazon, Oct 2025) | Native support for known future inputs (pre-dispatch, demand, solar), probability ranges, fine-tunable locally, Apache-2.0. **Lowest leakage risk**: no NEM price data in training, and its covariate training is fully synthetic | Gives no date ranges or cutoff for its real training data |
| **Timestral** (Mistral, Oct 2026; 5M–209M) | Native past and known future inputs, 21 quantiles, 32k-step context (~110 days at 5-minute resolution). Runs at 10–140 ms on CPU, so backfilling forecasts for the full history is cheap. Pretrained mostly on synthetic data | "Modified MIT" licence still to be checked. Fine-tuning seems to go through Mistral Forge only, so test zero-shot only. Technical report not yet published |
| **TimesFM-3** (Google, Aug 2026; 330M) | Native multivariate and known-future-input support. Google says it ranks first among foundation models on GIFT-Eval, fev-bench and TIME | Quantiles only go from the 10th to the 90th percentile, which may miss price spikes. Training data has no stated cutoff, so higher risk it has seen NEM 2025 prices. **Licence may be non-commercial**: if so, it's research-only and TimesFM 2.5 (Apache-2.0) is the fallback. One independent review found no gain from the new covariate features |

**References (not candidates):** F0 = pre-dispatch used as-is. LightGBM quantile regression predicting the gap between pre-dispatch and the actual price is the non-foundation baseline every model has to beat.

**Variants per model:**

| ID | Variant |
|---|---|
| F1 | Zero-shot, price history only |
| F2 | Zero-shot, with P5MIN/PREDISPATCH, demand and solar as known future inputs |
| F2r | Like F2, but predicting the gap between pre-dispatch and the actual price |
| F3 | F2 fine-tuned inside each training window. **Chronos-2 only**, unless local fine-tuning becomes available for the others |

**Horizons:**
- 5-minute steps for the next 1–2 h, lined up with P5MIN.
- 30-minute steps out to 24–48 h, lined up with PREDISPATCH.

**Avoiding lookahead and leakage:**
- Generate forecasts walk-forward, one per decision point, using only `InfoSet(t)`.
- Store them as a table with `publish_datetime`, so the section 3 no-lookahead test covers them.
- Any fine-tuning uses only data inside the training window.
- Pretraining leakage: report CY2025 results, **plus** results on 2026 data after each model's release date (a short window, used as a sanity check).

**Evaluation (on the validation year CY2024 first):**
1. **Forecast accuracy:** quantile loss and CRPS (a score for probability forecasts) by horizon. Use a version of the quantile loss that weights the tails, plus precision and recall on price spikes (e.g. RRP > $300 and > $5,000/MWh).
2. **Money made — the deciding test:** run the MPC on each forecast (**B2-F\***). For quantile forecasts, also run a scenario-based MPC. A forecast that's more accurate on average but misses spikes can earn less, so this test decides the winner.
3. **RL:** feed the winner's quantiles (e.g. 10th/50th/90th percentiles and the tails, over the horizon) into the observation **alongside** raw pre-dispatch. Compare RL trained with and without it.

**Compute:** about 105k decision points a year × ~5 years, per model and variant. Batch the runs, cache the results in Parquet, and backfill the full history only for the top 1–2 variants.

**Deployment:**
- The live forecaster runs inside the 5-minute loop, using the same feature code as the backtest.
- Timestral's CPU speed makes it the easiest to deploy. If the forecaster fails or runs late, fall back to raw pre-dispatch.
- **The licence must allow commercial use** before a model goes into production.

## 9. Training

- **Algorithms**: SAC (continuous action, sample-efficient) as the primary method, with PPO as a check. Use Stable-Baselines3 to start; switch to CleanRL/TorchRL if more control is needed.
- **Optional warm start**: behaviour-clone from the B2 pre-dispatch MPC schedules, then fine-tune with RL. This often speeds convergence a lot.
- **Experiment tracking**: MLflow or W&B. Log config hash, data snapshot version, seed and environment version on every run.
- **Hyperparameter search**: Optuna on the **validation** set only.
- **Seeds**: at least 5 per configuration. Report mean ± standard deviation.
- **Tail diagnostics**: share of revenue from the top 1% of intervals, behaviour during cap/floor events, and whether the agent holds charge into spikes shown (or missed) by pre-dispatch.

**Evaluation report** (generated automatically for each candidate model)
- $/MW/yr, % of B3 and B4 captured, and value over B2
- revenue by month and by time of day
- cycles per day and throughput
- revenue concentration
- worst days against the MPC
- rolling-origin results

## 10. Deployment (iteration 1 = shadow mode)

```
AEMO NEMWeb "Current" feeds (DispatchIS, P5MIN, PredispatchIS) — polled each ~5 min
        → ingest service → feature store (same code as the backtest InfoSet)
        → policy inference (ONNX/TorchScript, <1 s)
        → safety layer (SoC/power projection, fallback to pre-dispatch MPC B2 on stale data or errors)
        → target MW logged with timestamps, then settled against the actual RRP once published
```

- **Shared code**: training and production use the **same feature code**, so production features match training features.
- **Shadow (paper) trading**: run for at least one quarter. Track live $/MW against shadow B2 and against perfect-foresight hindsight.
- **Monitoring**: data latency, missing feeds, feature drift, action distribution, and P&L against the MPC baseline. Alert on these.
- **Model registry and promotion**: a model is promoted only if it beats B2 on both validation and the rolling-origin test.
- **Packaging**: containerised. Use one scheduler (Prefect, or cron to start) for ingest, retraining and the daily report.
- **Later (not iteration 1)**: convert target MW into NEM bids / price bands and rebids, and integrate with a trading desk or OEM controller.

## 11. Repository layout

```
rbit/
  config/        # asset + cost + market config (pydantic), shared by all
  data/          # NEMWeb/MMSDM loaders, cleaning, parquet/duckdb, InfoSet(t)
  market/        # settlement, MLFs, price cap/floor by FY
  battery/       # SoC dynamics, feasibility projection, degradation
  env/           # Gymnasium env
  optim/         # LP / MPC (perfect-foresight + pre-dispatch)
  forecast/      # TSFM wrappers (Chronos-2, Timestral, TimesFM-3), LightGBM gap model, walk-forward backfill, forecast store
  baselines/     # rule-based
  agents/        # RL training, BC warm start
  eval/          # backtest runner, metrics, report generation
  serve/         # live ingest, inference, safety layer, shadow ledger
tests/           # no-lookahead, env↔LP parity, settlement maths
```

## 12. Milestones

| # | Milestone | Exit criterion |
|---|---|---|
| M1 ✅ | Data pipeline for NSW1 (dispatch, P5MIN, predispatch), with publish timestamps. `python -m rbit.data.ingest`, `python -m rbit.data.quality`, `pytest` | Done 2026-11-02: Oct 2021 – Sep 2026 ingested; report at `reports/data_quality_NSW1.md`; no-lookahead tests pass (synthetic + 2,000 real points). Known gap: PREDISPATCH all-runs missing from the AEMO archive for 2022-10 |
| M2 ✅ | Battery/market core + perfect-foresight LP (B4) and MPC (B3). `python -m rbit.eval.perfect_foresight` | Done 2026-11-02: report at `reports/m2_perfect_foresight.md`. NSW1 2 h energy-only perfect foresight with Riverina 1 (RESS1) MLFs, 90% RTE, A$15/MWh degradation: 241k / 223k / 422k / 270k gross $/MW for CY2022–25 (2025 net 248k); the 217k claim is 80% of 2025 gross |
| M2b ✅ | Industry-claim decomposition (section 7): NSW 2 h fleet energy vs FCAS split for CY2025. `python -m rbit.eval.industry` | Done 2026-11-02: report at `reports/m2b_industry_claim.md`. Method reproduces Riverina 1's published 190k within 2% on an RRP (no-MLF) basis. Energy share of the NSW 2 h merchant fleet 97.5% (not ~93%); energy-only comparator **212k $/MW** (RRP basis) = 66% of B4 |
| M3 ✅ | Baselines B1, B2 + evaluation harness and report. `python -m rbit.eval.baselines` | Done 2026-11-02: report at `reports/m3_baselines.md`. B2 (pre-dispatch MPC, 15 h) 131k / 135k / 235k / 169k gross $/MW for CY2022–25 = 54–62% of B3 (net 50–61%); B1 (charge 11:00, discharge 17:00) 48–57% of B3. 2025 B2 169k vs Riverina 1 actual 159k (MLF basis) |
| M3b (stage 1) | Pre-dispatch gap model F4 (gradient boosting, scikit-learn) vs raw pre-dispatch on CY2024. `python -m rbit.eval.forecast` | Done 2026-11-02, negative result: report at `reports/m3b_forecast.md`. F4 halves MAE (4–15 h: 248 → 103 $/MWh) and removes pre-dispatch's over-forecast bias, but B2-F4 earns −12% net vs B2 (187k vs 213k). Accuracy-trained point forecasts don't add MPC value; Chronos-2/Timestral/TimesFM-3 not run. Next forecasting step, if any: quantile/scenario forecasts |
| M4 ✅ | Gymnasium environment (`rbit/env.py`) | Done 2026-11-02: LP schedules replay through the env to the cent (synthetic with MLFs/fees/degradation, and a real June 2025 week). Observation: 24 past prices, 12 P5MIN + 46 PREDISPATCH steps (signed-log), calendar, MLFs, SoC |
| M5 | RL v1 (SAC, with/without BC warm start) | Beats B1. Results on validation |
| M6 | RL tuned + rolling-origin evaluation | Beats B2 on validation and test, stable across seeds |
| M7 | Shadow deployment | One quarter of live paper P&L tracking the backtest |

M2 comes before any RL work on purpose: the perfect-foresight numbers show the size of the opportunity, and they test the $217k/MW figure, before anything is trained.

## 13. Key risks

- **Lookahead leakage** makes the backtest look much better than reality. Mitigation: `InfoSet` with publish timestamps, plus tests.
- **Revenue concentrated in a few spike intervals**: results swing a lot year to year, and RL can overfit to particular events. Mitigation: multi-year rolling evaluation, tail metrics, cap-normalised prices.
- **Regime change** (new BESS entry compressing spreads, changes to the price cap). Mitigation: recent-weighted training and scheduled retraining.
- **Price-taker optimism**: a real 100 MW+ battery in NSW does move prices in tight intervals. Note this as a known upward bias. Addressing it is for a later iteration.
- **Pre-dispatch MPC may be hard to beat.** Even then, RL capturing a similar share at much lower inference cost, or doing better in the tails, is a useful finding. Define success as being beyond B2.
- **Foundation-model pretraining leakage / licensing**: a model may have seen NEM 2025 prices, or its licence may block commercial use. Mitigation: prefer Chronos-2 / Timestral, check results on 2026 data after each release, and review licences before deployment.
