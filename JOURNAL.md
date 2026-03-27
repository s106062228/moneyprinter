# Research Journal — MoneyPrinterV2

> Append-only research log. Each entry records what was attempted, what was learned, and what to do next.
> Format: `## YYYY-MM-DD HH:MM — <title>`

---

## 2026-03-27 00:00 — Auto Research Pipeline initialized

**Setup:** Restructured project to use Auto Research Pipeline architecture with Agent Teams.

**Directories created:**
- `specs/` — Open Spec files (input topics → structured research specs)
- `results/` — Raw experiment outputs and data
- `reports/` — Synthesized analysis reports
- `logs/` — cron and claude execution logs

**Skills registered (global):**
- `research-init` — converts topics into Open Spec
- `spec-to-tasks` — decomposes spec into TODO tasks
- `run-experiments` — Agent Team parallel execution (Researcher + Experimenter + Analyst)
- `analyze-and-update` — synthesizes results into JOURNAL + TODO updates
- `sync-github` — commits and pushes with semantic messages

**Next:** Add first research topic to `specs/` and run `/research-init`.

---
