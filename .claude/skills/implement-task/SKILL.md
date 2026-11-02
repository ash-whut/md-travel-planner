---
name: implement-task
description: Implement one or more items from docs/05-implementation-plan.md with a developer subagent, gate the result with the code-reviewer subagent, and loop on fixes (max 2 rounds). Usage - /implement-task S1.4  |  /implement-task S1.5-S1.6  |  /implement-task S1.3,S1.9
argument-hint: <task-ids>
disable-model-invocation: true
---

# /implement-task $ARGUMENTS

You are the **lead**. Orchestrate; don't write the feature code yourself.
Follow `docs/06-agent-workflow.md`.

## 1. Prepare
1. Parse the item IDs from `$ARGUMENTS` (single `S1.4`, range `S1.5-S1.6`, or comma list).
2. Read `AGENTS.md` and the item rows in `docs/05-implementation-plan.md`. For each item:
   - it exists and isn't ☑;
   - its Agent is FE or BE. **H** items are for humans and **R** items run via `/research` —
     stop and tell the human;
   - every ID in its **Depends** column is ☑ (ask the human if unclear). If a dependency is an
     R item that isn't ☑, tell the human which `/research RQ-n` to run.
3. Pick the worker from the Agent column: FE → `frontend-dev`, BE → `backend-dev`.
   If the IDs mix FE and BE, stop and ask the human to run them as separate invocations,
   committing in between (the reviewer reviews the whole working tree).
   Tell the worker which **stage** the items belong to; it must not build later-stage features.
4. Run `git status`. If there are uncommitted changes unrelated to these tasks, ask the human
   before continuing (the reviewer reviews the whole working tree).

## 2. Implement
Spawn the worker subagent with: the item IDs, the full item rows + the stage's acceptance criteria,
and the instruction to finish with a HANDOFF (06 §3). Keep its final HANDOFF.

## 3. Review loop (max 2 fix rounds)
For round = 1, 2, 3:
1. Spawn `code-reviewer` (fresh) with: task IDs, round number, the latest HANDOFF, and on
   rounds 2–3 the previous VERDICT's findings to re-check.
2. If `VERDICT: APPROVE` → go to step 4.
3. If `REQUEST_CHANGES` and round < 3 → send the findings to the worker (continue the same
   worker if possible, otherwise spawn it again with the previous HANDOFF + findings); get an
   updated HANDOFF; continue.
4. If round 3 still returns REQUEST_CHANGES → **stop and escalate**: show the human the open
   blocker/major findings and the current state. Do not mark tasks ☑.

## 4. Finish (on APPROVE)
1. Mark the items ☑ in `docs/05-implementation-plan.md` (keep any claimer initials; the human adds theirs).
2. Report to the human:
   - Summary of what changed (files grouped by purpose).
   - Final verdict, rounds used, and any minor/nit findings left open.
   - Commands the reviewer ran and their results.
   - Any `CONTRACT CHANGE`, doc edits, assumptions, or open questions.
   - Suggested commit message (conventional style, e.g. `feat(frontend): chat panel (S1.13)`)
     and a short PR description.
3. **Do not commit, push, or open a PR.** The human does that.
