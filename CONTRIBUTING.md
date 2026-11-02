# Contributing (team workflow)

Four people, one repo, AI agents doing much of the typing. Keep it simple.

## Branches & PRs
- `main` is always runnable. Don't push directly to it.
- Branch from `main`: `<name>/<short-topic>` (e.g. `hari/plan-view`, `alex/map-markers`).
- One item (or a small group of related items) per branch; small PRs.
- At least one teammate glances at the PR before merging. Squash-merge.
- Pull `main` often; rebase or merge `main` into your branch before opening the PR.

## Picking work
- No fixed assignments. Open [docs/05-implementation-plan.md](docs/05-implementation-plan.md),
  take any ☐ item in the earliest unfinished stage whose **Depends** are all ☑.
- Claim it first: set `◐ <initials>`, commit and push that one-line change.
- **H** items are human tasks (accounts, keys, demo checks); everything else goes through an agent.

## Working with agents
- Claude Code: `/implement-task S1.4` for items, `/research RQ-4` for backend research.
  Other tools: use the manual worker/reviewer prompts in
  [docs/06-agent-workflow.md](docs/06-agent-workflow.md) §6.
- **Every agent-made change must get a code-reviewer APPROVE before you commit it.**
  Up to 2 automatic fix rounds; after that, you decide.
- Agents never commit. You review the diff (`git diff`), commit with the suggested message,
  and open the PR — paste the agent's final report into the PR description.
- Run one agent task at a time per working copy; start from a clean `git status`.
- If an agent says the docs are wrong or ambiguous, fix the docs (team decision for 01/02).

## Before opening a PR
- Frontend: `npm run lint && npm run build`
- Backend: `pytest backend/tests`
- Items marked ☑ in `docs/05-implementation-plan.md` — add your initials.
- Changed an API, schema, or SSE event? `docs/03-contracts.md` updated **in the same PR**,
  called out in the PR description (frontend and backend both depend on it).
- New decision or deviation from the docs → entry in `docs/decisions.md`.

## Shared files (coordinate before editing)
`docs/03-contracts.md`, `docs/05-implementation-plan.md` (claims only), `frontend/src/types/`,
`frontend/src/api/`, `backend/app/schemas/`, `backend/tests/fixtures/`. Keep changes to these in their own small PRs and give the team a heads-up.

## Secrets
Never commit `.env`, `.env.local`, API keys, or `*.db` files. See [docs/setup-guide.md](docs/setup-guide.md).
