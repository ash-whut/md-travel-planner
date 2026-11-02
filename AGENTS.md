# AGENTS.md — Rules for every coding agent on md-travel-planner

Canonical instructions for any AI agent (Claude Code, Codex, Cursor, Copilot…) and a quick
orientation for humans. `CLAUDE.md` imports this file. Keep it short; details live in `docs/`.

## 1. The project

A single-user, chat-driven planner for short trips (2–4 days, 1–2 cities, budget-minded
travelers aged 15–35). Chat with a planning agent on the **right half** of the screen; the
generated itinerary appears on the **left** as day cards, a Google Map, and a booking
checklist. Every place gets a stable **letter tag** (A, B, C…; hotels H1/H2) that the user
uses to edit the plan via chat ("replace C"). A history sidebar lists past sessions
(open / rename / delete). Units: °F, miles. 4-person student project (CSCE 634 IUI) — keep
code simple and readable for teammates.

**Built in stages** (docs/05): 1 talking skeleton (chat + LLM-drafted plan, no tools) →
2 places on the map → 3 live tools & smarter chat → 4 memory/history → 5 polish. Build only
what your item's stage needs; the docs describe the end state plus each stage's baseline.

## 2. Doc map

| Doc | Read when | Who may edit |
|---|---|---|
| [docs/01-product-spec.md](docs/01-product-spec.md) | Always, once per session | Humans only (team consensus) |
| [docs/02-ui-spec.md](docs/02-ui-spec.md) | Any frontend work | Humans only (team consensus) |
| [docs/03-contracts.md](docs/03-contracts.md) | Any API / schema / SSE / DB work — **source of truth** | Devs & researcher, only with a `CONTRACT CHANGE` note; reviewer checks impact on the other side |
| [docs/04-backend-design.md](docs/04-backend-design.md) | Any backend work | backend-researcher, backend-dev |
| [docs/05-implementation-plan.md](docs/05-implementation-plan.md) | To find your item (S/R/H IDs), its Depends, and stage acceptance | Humans claim (◐ + initials); ☑ only after reviewer APPROVE |
| [docs/06-agent-workflow.md](docs/06-agent-workflow.md) | Before running or acting as any agent role | Humans |
| [docs/research/](docs/research/README.md) | Backend research questions (RQ-n) and findings | backend-researcher |
| [docs/setup-guide.md](docs/setup-guide.md) | Env vars, keys, run modes | Anyone |
| [docs/decisions.md](docs/decisions.md) | Before re-opening a settled choice | Append-only, anyone |

## 3. Stack and layout

- **Frontend:** React 18 + TypeScript + Vite, Tailwind CSS, shadcn/ui, Zustand,
  `@vis.gl/react-google-maps`, `@microsoft/fetch-event-source`, `react-markdown`. Package manager: npm.
- **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLModel on SQLite (local file),
  `httpx`; SSE streaming; LLM behind a swappable provider adapter (`fake` default; TAMU AI via
  `openai_compat` first, Claude via `anthropic` as backup). venv + pip with `backend/requirements.txt`.

```
frontend/src/
  api/          ApiClient interface + http.ts   (components never call fetch directly)
  components/   layout/ history/ chat/ plan/ map/ checklist/ common/ (TagBadge…)
  store/        Zustand stores
  types/        TS types mirroring docs/03-contracts.md
  lib/          format.ts (dates, 12h time, °F, miles, money)
backend/app/
  main.py  api/  core/config.py  db/ (tables, repositories, seed.py)  schemas/
  llm/          provider protocol + adapters (fake, openai_compat, anthropic) + smoke.py
  agent/        orchestrator.py, tags.py, postprocess.py, prompts/
  tools/        weather.py, maps.py, hotels.py, links.py (+ mock providers)
backend/tests/      (+ fixtures/ with sample itineraries)
```
No keys? Run the backend with `LLM_PROVIDER=fake`; there is no frontend mock mode.

## 4. Commands

```bash
# backend (repo root, venv active — see docs/setup-guide.md)
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend      # http://localhost:8000/docs
pytest backend/tests

# frontend
cd frontend && npm install
npm run dev                                          # http://localhost:5173
npm run lint && npm run build
```

## 5. Hard rules

1. **Scope:** implement only the item IDs you were given (e.g. `S1.4`), at their stage. No
   drive-by refactors, no features from later stages.
2. **Contracts first:** `src/types/` and `app/schemas/` match `docs/03-contracts.md`. If a
   contract must change, change the doc in the same change and flag `CONTRACT CHANGE`.
3. **Frontend:** components talk to the backend only through `src/api/`.
4. **LLM:** all model calls go through `backend/app/llm/`; no provider SDK types elsewhere.
5. **Determinism:** letter tags, IDs, links and prices are produced by code (`agent/tags.py`,
   `agent/postprocess.py`, tool results) — never by LLM text.
6. **Tools** are plain Python functions with a mock provider; tests never hit the network.
7. **Secrets** only in git-ignored `.env` files; keep `.env.example` current. Only the
   referrer-restricted Google Maps browser key may reach the frontend.
8. **Simplicity:** no new frameworks or heavy dependencies (Redux, Celery, LangChain, Docker…)
   unless `docs/decisions.md` records the decision.
9. **Tests:** pytest for backend logic and routes (with `LLM_PROVIDER=fake`); Vitest only for
   non-trivial frontend logic.
10. **No git commits or pushes by agents.** Leave changes uncommitted; propose a commit message.

## 6. Agent roles (details: docs/06-agent-workflow.md)

| Role | Does | Never |
|---|---|---|
| **backend-researcher** | Answers one RQ: writes `docs/research/RQ-n-*.md`, updates `docs/04-backend-design.md` + `docs/decisions.md` | Edits code or docs 01/02 |
| **frontend-dev** | Implements frontend tasks from 05 | Edits backend or docs 01/02 |
| **backend-dev** | Implements backend tasks from 05 | Edits frontend or docs 01/02 |
| **code-reviewer** | Critiques every change (code *and* research/spec edits), re-runs checks, returns a verdict | Edits files |

Loop: **worker → code-reviewer → (fix → re-review, max 2 rounds) → human**. Claude Code
users run it with `/implement-task S1.4` or `/research RQ-4`. **H** items in 05 are for
humans; agents never run them.

## 7. Definition of done

- All acceptance criteria of the task(s) are met and verified.
- Lint, build and tests pass.
- Contract/design docs updated if behavior or interfaces changed.
- code-reviewer verdict is **APPROVE**.
- A suggested commit message is provided; a human commits and opens the PR.
