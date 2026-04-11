# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Framework: WAT Architecture

This workspace operates on the **WAT (Workflows, Agents, Tools)** pattern — a separation of concerns between AI reasoning and deterministic execution:

| Layer | Location | Role |
|-------|----------|------|
| Workflows | `workflows/` | Markdown SOPs: objectives, inputs, tool sequence, expected outputs, edge cases |
| Agent | (you) | Orchestration — read workflow, call tools in order, handle failures, ask when unclear |
| Tools | `tools/` | Python scripts for deterministic execution: API calls, data transforms, file ops |

**Why the separation matters:** Chained AI steps compound errors (90% accuracy × 5 steps = 59% success). Deterministic scripts keep that rate flat.

## Operating Rules

**Before building anything**, check `tools/` for an existing script that satisfies the workflow requirement. Only create new scripts when nothing fits.

**Do not create or overwrite workflows** without explicit instruction — workflows are persistent instructions that must be preserved and refined, not regenerated.

**When a tool fails:**
1. Read the full error and trace
2. Fix the script and retest (check before re-running if the tool uses paid API calls)
3. Update the workflow with what you learned (rate limits, batch endpoints, timing quirks)

## File Structure

```
workflows/          # Markdown SOPs — do not overwrite without permission
tools/              # Python execution scripts
.tmp/               # Disposable intermediates; safe to regenerate
.env                # API keys and credentials (never store secrets elsewhere)
credentials.json    # Google OAuth (gitignored)
token.json          # Google OAuth token (gitignored)
```

Deliverables go to cloud services (Google Sheets, Slides, etc.) — not to local files. Everything in `.tmp/` is disposable.

## Running Tools

Tools are Python scripts invoked directly:

```bash
python tools/<script_name>.py
```

Credentials are loaded from `.env`. If a script needs Google OAuth, `credentials.json` and `token.json` must be present in the project root.
