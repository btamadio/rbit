## Response Style & Concision
- **Response length:** Concise. Lead with the direct result or answer first.
- **Format:** Use bullet points, code snippets, and short headers. Skip conversational filler, preamble, and post-summary wrap-ups.
- **Code explanations:** Do not explain obvious code changes unless asked; provide the diff or implementation directly.
- **Verbosity:** Omit passive voice, fluff, and unnecessary narrative.

## Agent skills

### Issue tracker

GitHub Issues on `btamadio/rbit`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root, created lazily. See `docs/agents/domain.md`.
