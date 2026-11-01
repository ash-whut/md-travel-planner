# Contributing (team workflow)

Four people, one repo. Keep it simple.

## Branches & PRs
- `main` is always runnable. Don't push directly to it.
- Branch from `main`: `<name>/<short-topic>` (e.g. `hari/plan-view`, `alex/map-markers`).
- Open a PR into `main` when a task (or a coherent part of one) works. Keep PRs small.
- At least one teammate glances at the PR before merging. Squash-merge.
- Pull `main` often; rebase or merge `main` into your branch before opening the PR.

## Before opening a PR
- Frontend: `npm run lint && npm run build`
- Backend: `pytest backend/tests`
- Mark finished tasks ☑ (with your initials) in `docs/06-implementation-plan.md`.
- If you changed an API, schema, or SSE event: update `docs/03-contracts.md` **in the same PR**
  and mention it in the PR description, because frontend and backend both depend on it.
- New decision or deviation from the docs → add an entry to `docs/decisions.md`.

## Shared files (coordinate before editing)
`docs/03-contracts.md`, `frontend/src/types/`, `frontend/src/api/`, `frontend/src/fixtures/`,
`backend/app/schemas/`. Keep changes to these in their own small PRs and give the team a heads-up.

## Secrets
Never commit `.env`, `.env.local`, API keys, or `*.db` files. See `docs/setup-guide.md`.

## Using coding agents
- Claude Code loads `CLAUDE.md` automatically; point it at a phase/task in
  `docs/06-implementation-plan.md` using the prompt template there.
- Review agent output like any other PR. Agents must follow the docs; if the docs are wrong, fix the docs.
