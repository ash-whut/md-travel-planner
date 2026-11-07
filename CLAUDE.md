@AGENTS.md

## Claude Code specifics
- Build plan steps with the project skill **`/build-steps <numbers>`**
  (`.claude/skills/build-steps/`). It runs the subagents in `.claude/agents/`: `coder`,
  `tester` and `reviewer`.
- Before writing or changing an Anthropic adapter (not planned for the MVP), load the
  `claude-api` skill.
