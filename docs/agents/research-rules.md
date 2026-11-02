# Research rules

Apply to any change that trains, tunes, evaluates or reports a strategy.

- **Data periods** (PLAN.md section 4): train 2021-10 to 2023-12, validate 2024, test 2025, used once per milestone. Prefer tuning on 2022–23; if you select on 2024, say so in the report.
- **One accounting:** every strategy uses `BatteryConfig()` defaults, the shared settlement (`rbit.market.settle`) and `metrics()`, so numbers are comparable.
- **No lookahead:** decisions see only data published before their dispatch run, via `InfoSet`.
- **Reports:** each milestone writes a generated `reports/*.md` that states the result against its PLAN.md exit criterion, including failures and any selection bias (e.g. checkpoints chosen on 2024).
- **Known limits** get a `shortcut: <limit>, <when to upgrade>` comment in code.
