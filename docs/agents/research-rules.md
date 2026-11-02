# Research rules

Apply to any change that trains, tunes, evaluates or reports a strategy.

- **Data periods:** train 2021-10 to 2023-12, validate 2024, test 2025. 2025 stays sealed until a final run. Tune and select on 2022–23; evaluate 2024 once per candidate.
- **One accounting:** every strategy uses `BatteryConfig()` defaults, the shared settlement (`rbit.market.settle`) and `metrics()`, so numbers are comparable.
- **No lookahead:** decisions see only data published before their dispatch run, via `InfoSet`.
- **Reports:** each milestone writes a generated `reports/*.md` with a PASS/FAIL verdict against its PLAN.md gate. Report failures too, and state any selection bias (e.g. checkpoints chosen on 2024).
- **Known limits** get a `shortcut: <limit>, <when to upgrade>` comment in code.
