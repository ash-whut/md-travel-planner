---
name: research
description: Resolve one backend research question (RQ-n in docs/research/README.md) with the backend-researcher subagent, which writes a sourced note and updates docs/04-backend-design.md; then gate it with the code-reviewer subagent (max 2 fix rounds). Usage - /research RQ-3
argument-hint: <RQ-id>
disable-model-invocation: true
---

# /research $ARGUMENTS

You are the **lead**. Orchestrate; don't do the research yourself.
Follow `docs/06-agent-workflow.md`.

## 1. Prepare
1. Read `docs/research/README.md`; confirm `$ARGUMENTS` is a listed RQ that is still open.
2. Find the matching `[PROPOSED → RQ-n]` section(s) in `docs/04-backend-design.md`.
3. Run `git status`; if unrelated uncommitted changes exist, ask the human before continuing.

## 2. Research
Spawn `backend-researcher` with: the RQ id, its full agenda row, the 04 section(s) it
resolves, the "research (R) item" acceptance criteria from `docs/05-implementation-plan.md`,
the stage whose items it blocks, and the instruction to finish with a HANDOFF (06 §3).

## 3. Review loop (max 2 fix rounds)
For round = 1, 2, 3:
1. Spawn `code-reviewer` (fresh) with: the RQ id, "research/spec review", round number, the
   latest HANDOFF, and on rounds 2–3 the previous findings to re-check.
2. APPROVE → step 4.
3. REQUEST_CHANGES and round < 3 → send findings to the researcher (continue it if possible,
   else re-spawn with HANDOFF + findings); continue.
4. Round 3 still REQUEST_CHANGES → stop and escalate with the open findings.

## 4. Finish (on APPROVE)
Mark the matching R item (e.g. `R2.1` for RQ-4) ☑ in `docs/05-implementation-plan.md`, then
report to the human:
- The recommendation in 2–3 sentences, plus the fallback.
- Files changed (research note, 04 sections, decisions entry, setup-guide if any).
- Any `CONTRACT CHANGE` and its frontend impact; plan tasks that need adjusting.
- Unverified claims the human should double-check.
- Suggested commit message (e.g. `docs(research): RQ-3 hotel pricing source`).

**Do not commit or push.** The human reads the spec diff and commits.
