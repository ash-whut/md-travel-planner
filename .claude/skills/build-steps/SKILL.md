---
name: build-steps
description: Build one or more numbered steps from docs/plan.md as a single commit-sized batch, using the coder, tester and reviewer subagents. Use when the user says "/build-steps 11 12 14", "build steps 2-4", or similar.
argument-hint: <step numbers, e.g. 2-4 or 11 12 14>
disable-model-invocation: true
---

# /build-steps

Steps requested: **$ARGUMENTS**

You are the **orchestrator**. Follow the workflow in `AGENTS.md` §5. You run it in the main
session and delegate the work to the subagents `coder`, `tester` and `reviewer`. Keep your own
context lean: ask the subagents for their short reports and don't re-read their work unless you
need to.

## 0. Prepare
1. Parse the arguments into an ordered list of step numbers. Ranges like `2-4` and lists like
   `11 12 14` are both allowed. No arguments → ask which steps.
2. Read `docs/plan.md` (only the requested steps plus the "How to use" header).
   - A step already ☑ → skip it and say so.
   - The first `[HUMAN]` step in the list → build only the steps before it, then tell the user
     what the human has to do.
   - A step whose dependencies ("needs N") aren't ☑ and aren't earlier in this batch → stop and
     ask.
3. Run `git status --porcelain`. If there are uncommitted changes, warn the user that they would
   be mixed into this batch's diff, and ask whether to continue.
4. Mark each requested step ◐ in its `docs/plan.md` heading.

## 1. For each step, in order
1. **coder** (Agent, `subagent_type: coder`): "Implement step N from docs/plan.md." Include any
   notes from earlier steps in this batch that matter.
2. If the coder reports *blocked* → stop the batch and go to §3.
3. **tester** (`subagent_type: tester`): "Write the tests for step N and run the full check."
   Pass along the coder's report.
4. If the tester reports red with a **code bug** → send the failures to the coder, then re-run
   the tester. Do this at most **2 fix rounds**. Still red → stop the batch and go to §3.
5. Green → change the step heading to ☑. Replace its `- **Notes:** —` with one short line
   (what was built, or anything surprising).

## 2. Review the whole batch
1. **reviewer** (`subagent_type: reviewer`): "Review the uncommitted diff for steps <list>."
2. **CHANGES** → send the blockers and the cheap minors to the coder ("fix review findings
   1, 3, 4"). Then run the tester for the full check, then a **fresh** reviewer. Do this at most
   **2 rounds**. Anything still open is reported to the user, not hidden.
3. Write the reviewer's *later-step notes* into those steps' **Notes** in `docs/plan.md`.

## 3. Report to the user (short)
- Per step: ☑ or blocked, what was built (1 line), tests added (1 line).
- Final full-check result and review verdict, with any open findings.
- Anything the human must do (a `[HUMAN]` step, keys, manual checks to try in the browser).
- A suggested commit message: `Steps 11–14: chat SSE, TAMU provider, …`.
- A reminder: review the diff, try it (`npm run dev` + uvicorn), then commit. Agents don't
  commit.
