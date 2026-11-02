# M5 diagnosis: why SAC trails the time-of-day rule (2024, NSW1)

One-off analysis on 2026-11-02 of the M5 best checkpoints (`data/models/m5/seed{0,1,2}/best.zip`), no
retraining. Figures are for seed 1 unless stated; net $/MW/yr. Checkpoints were selected on 2024, so
SAC figures are optimistic. The analysis scripts were throwaway and are not in the repo.

**Bottom line:** SAC spends energy in mid-price hours and is short of charge when the 17–18 h spikes
arrive. Not the cause: train/eval mismatch, missing time-of-day features, dithering.

## Where the gap is (SAC vs B1)

- Total net gap 24k. Top-1% price intervals (≥ $371/MWh): B1 143k gross, SAC 127k, 17k of the 19k gross gap.
- By hour: 17–18 h −88k; 11–16 h +73k; other hours ≈ 0. SAC trails B1 in every month.
- Spike share of gross (top 0.1%): B1 30%, B2 30%, B3 31%, SAC 32–39%. SAC isn't bad at spikes,
  it has less energy to sell into them.

## Causes, ranked

1. **Energy rationing (high confidence).** MWh/MW discharged, SAC vs B1: 06–16 h 287 vs 0; 17–18 h
   401 vs 625. At 17–18 h intervals above $5,000 (n = 125), SAC starts at 0.29 SoC (46% of them below
   0.15) vs B1 at 0.46, and delivers 0.50 of rated power vs 0.92. With gamma 0.997 a spike 8 h ahead
   is worth 0.75 of its value, 24 h ahead 0.42.
2. **Weak price response at the evening peak (medium).** Mean action at 17–18 h: 0.68 at $100–300,
   0.85 above $5,000; corr(action, arcsinh price) = 0.30.
3. **Distribution shift (high that it exists, medium that it matters).** Intervals above $5,000:
   2022 52, 2023 44, 2024 233. Top-1% share of |price| mass: 8–11% in 2022–23, 28% in 2024.
4. **Undertrained (medium).** Mean net 137k at 700k steps, 151k at 1M; seeds 1 and 2 still rising.
5. **Heavy-tailed reward (low–medium).** `reward_scale` 833 $/step; rewards reach ±175 at the cap but
   |r| > 10 in ~0.1% of steps, so a handful of transitions dominate critic targets.

## Ruled out

- **Train/eval mismatch:** 3-day random-SoC episodes vs continuous on the same 60 windows differ ≤ 4%.
- **Missing time of day:** `tod_sin`/`tod_cos` are in the observation and actions vary by hour.
- **Dithering or saturation:** |a| ≥ 0.99 in 8–9% of steps, |a| < 0.05 in 2%; no switching cost in the env.
- **Stuck at SoC bounds:** SoC ≤ 0.06 in 54–57% of SAC steps vs 68% for B1.

## Candidate fixes (untested)

1. B2 with an evening reserve: bias the planning price path up at 17–18 h through the existing
   `adjust` hook (`rbit/baselines.py`), tuned on 2022–23. Minutes per evaluation.
2. Behaviour-clone the actor from B2 schedules, then fine-tune SAC at a low learning rate.
3. Longer horizon (gamma ≈ 0.9995) plus reward normalisation or clipping.

Target for any fix is B2 (213k net in 2024), not B1. Tune on 2022–23; 2025 stays sealed.
