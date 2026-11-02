# rbit
Battery arbitrage backtests on the NEM (NSW1): benchmarks, MPC and RL, settled exactly as AEMO settles. Spec and milestones: [PLAN.md](PLAN.md).

- Python: `.venv/bin/python`. Tests: `.venv/bin/python -m pytest` (real-data tests skip if `data/` isn't ingested).
- `gh` auth: export `GH_TOKEN` from `.env`; never print it.
- Workflow: issue → branch → PR that closes it; commits end with the Claude `Co-Authored-By` trailer; run `/code-review` before merge. Never commit to `main`.
- Before training, tuning, evaluating or reporting a strategy, read [docs/agents/research-rules.md](docs/agents/research-rules.md).

## Agent skills

- **Issue tracker:** GitHub Issues on `btamadio/rbit`. See [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).
- **Triage labels:** `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See [docs/agents/triage-labels.md](docs/agents/triage-labels.md).
- **Domain docs:** single-context, `GLOSSARY.md` and `docs/adr/` at the repo root, created lazily. See [docs/agents/domain.md](docs/agents/domain.md).
