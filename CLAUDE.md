# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- Subagents are defined in `.claude/agents/`: `backend-researcher`, `frontend-dev`,
  `backend-dev`, `code-reviewer`. The main session acts as the **lead** that orchestrates them.
- Entry points (skills in `.claude/skills/`):
  - `/implement-task <task-ids>` — dev agent → code-reviewer → fix loop (max 2 rounds) → report.
  - `/research <RQ-id>` — backend-researcher → code-reviewer → fix loop → report.
- Before writing or changing `backend/app/llm/anthropic_provider.py` (or anything that calls
  Claude), load the `claude-api` skill — model IDs and SDK patterns change; don't rely on memory.
- Never commit. End with a suggested commit message and PR description.
