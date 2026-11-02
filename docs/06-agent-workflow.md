# 06 — Agent Workflow

How research and development are split across AI agents, and how every change gets
critiqued before a human commits it. Rules every agent follows: [AGENTS.md](../AGENTS.md).

## 1. Roles

| Role | Definition | Input | Output | May edit |
|---|---|---|---|---|
| **Lead** | The main Claude Code session (or a human) | Task IDs / RQ id | Orchestrates the loop, final report | `05-implementation-plan.md` status (☑ after APPROVE) |
| **backend-researcher** | `.claude/agents/backend-researcher.md` | One RQ from [research/README.md](research/README.md) | Research note + spec edits + handoff | `docs/research/`, `docs/04-backend-design.md`, `docs/decisions.md`; `docs/03-contracts.md` only with `CONTRACT CHANGE` |
| **frontend-dev** | `.claude/agents/frontend-dev.md` | FE task IDs from 05 | Code + handoff | `frontend/`, task status ◐, `03-contracts.md` with `CONTRACT CHANGE` |
| **backend-dev** | `.claude/agents/backend-dev.md` | BE task IDs from 05 | Code + handoff | `backend/`, `04-backend-design.md` (details forced by implementation), task status ◐, `03-contracts.md` with `CONTRACT CHANGE` |
| **code-reviewer** | `.claude/agents/code-reviewer.md` | Task IDs/RQ + worker handoff + working-tree diff | Verdict | Nothing (read-only; runs checks) |
| **Human** | Teammate | Final report + diff | Commit, PR, merge | Everything; sole owner of 01 and 02 |

Why a separate critic: subagents start with a fresh context, so the reviewer judges the diff
against the docs without the worker's assumptions.

## 2. The loop

```
 human: claims an item (◐ + initials), then
        /implement-task S1.4      or      /research RQ-4
            │
            ▼
   Lead: check item exists, is FE/BE (not H), Depends all ☑, pick worker
            │
            ▼
   Worker (frontend-dev | backend-dev | backend-researcher)
     does the task, runs checks, returns HANDOFF
            │
            ▼
   code-reviewer: reads diff + docs, re-runs checks, returns VERDICT
            │
     APPROVE ──────────────────────────────┐
     REQUEST_CHANGES                       │
            │ (fix rounds used < 2)        │
            ▼                              │
   Worker fixes listed blocker/major       │
   findings → back to code-reviewer        │
            │ (2 fix rounds used, failing) │
            ▼                              ▼
   ESCALATE to human with open      Lead: mark ☑, final report,
   findings                         suggested commit message + PR text
                                           │
                                           ▼
                                    human reviews diff, commits, opens PR
```

- **Max 2 fix rounds:** review 1 → fix → review 2 → fix → review 3. If review 3 still has
  blocker/major findings, escalate to a human.
- **Agents never commit or push.** Changes stay in the working tree for the human.
- **One item at a time per working copy.** Teammates parallelize across their own branches,
  each on an item they claimed in 05.

## 3. Handoff format (worker → reviewer)

```
## HANDOFF
Tasks: S1.4 (and/or RQ-n) · Stage: 1
Files changed: path — one-line purpose (each)
Acceptance criteria:
  - <criterion> — MET | NOT MET — how verified (command, manual check)
Commands run: <command> → <result summary>
Doc changes: <files>; CONTRACT CHANGE: yes/no (+ what and impact on the other side)
Decisions / assumptions: …
Open questions: …
```

## 4. Verdict format (reviewer → lead)

```
## VERDICT: APPROVE | REQUEST_CHANGES
Round: 1 | 2 | 3
Commands re-run: <command> → <result>
Acceptance criteria:
  | criterion | status | evidence |
Findings:
  - [blocker|major|minor|nit] path:line — problem — suggested fix
Summary: 1–3 sentences
```
- `REQUEST_CHANGES` only if there is at least one **blocker** or **major** finding.
- blocker = broken build/tests, criterion not met, contract violated, secret leaked, hard rule broken.
- major = likely bug, missing required test, scope creep, unflagged contract change, unsourced key research claim.
- minor / nit = listed for the human, never block.

### Reviewer checklist — code
1. Acceptance criteria actually met (verified by running, not by reading the handoff).
2. Lint / build / tests pass when the reviewer runs them.
3. Types (`src/types/`) and models (`app/schemas/`) match 03-contracts.
4. Only the assigned item IDs touched; no unrelated refactors; nothing from a later stage.
5. AGENTS.md hard rules (api layer, llm layer, deterministic tags/prices, tool mocks, secrets, no new frameworks).
6. Tests exist for logic (tags, postprocess, tools, routes).
7. Readable for teammates; no dead code or needless abstraction.

### Reviewer checklist — research / spec edits
1. Every key claim (limits, prices, quotas, API shapes) has a source link + access date; unverified claims are marked.
2. Recommendation fits the constraints: free tier, local-only, simplicity, swappable LLM, MVP scope.
3. 04 section rewritten coherently and tagged [DECIDED]; it extends the "Stage 1 baseline"
   subsections (§3.0, §4.0, §5.0, §7.0) rather than silently contradicting them; decisions.md entry added.
4. No contradictions with 01, 02, 03; any contract change flagged with frontend impact.
5. Implementation tasks in 05 that depend on it still make sense (note needed adjustments).

## 5. Escalate to a human when

- 2 fix rounds are used and blocker/major findings remain.
- A `CONTRACT CHANGE` affects the other side and nobody owns the follow-up.
- The docs are wrong, ambiguous or contradict each other (agents must not "fix" 01/02).
- A dependency (task or RQ) isn't done.
- A paid service, new account, or new heavy dependency would be needed.

## 6. Running the loop without Claude Code skills

Any agentic tool works; run the roles as separate sessions/chats so the reviewer has a fresh context.

**Worker prompt:**
> Read AGENTS.md and docs/06-agent-workflow.md. You are the <frontend-dev | backend-dev |
> backend-researcher>. Do item(s) <IDs, e.g. S1.4> from docs/05-implementation-plan.md (or
> <RQ-n> from docs/research/README.md) and nothing else — nothing from a later stage. Verify each acceptance criterion, do not commit,
> and end with a HANDOFF in the format of §3.

**Reviewer prompt (new session):**
> Read AGENTS.md and docs/06-agent-workflow.md. You are the code-reviewer. Do not edit any
> files. Review the uncommitted changes (`git status`, `git diff`) for task(s) <IDs> against
> the docs and this handoff: <paste>. Re-run lint/build/tests. Reply with a VERDICT in the
> format of §4.

Feed REQUEST_CHANGES findings back to the worker session; stop after 2 rounds.
