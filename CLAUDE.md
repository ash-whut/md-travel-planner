# CLAUDE.md — Agent Guide for md-travel-planner

Loaded automatically by Claude Code each session. Short, stable rules here; detail in `docs/`.
This is a 4-person student project (CSCE 634 IUI) — keep code simple and readable for teammates.

## What we are building

A single-user, chat-driven planner for short trips (2–4 days, 1–2 cities, budget-minded
travelers aged 15–35). The user chats with a planning agent (right half of the screen); the
agent produces a structured itinerary rendered on the left as day cards, a Google Map, and
a booking checklist. Every place gets a stable **letter tag** (A, B, C… hotels H1/H2) that
the user uses to edit the plan via chat ("replace C"). Past sessions live in a history
sidebar (open / rename / delete). Units: °F, miles.

## Read before coding

| Doc | Read when |
|---|---|
| [docs/01-product-spec.md](docs/01-product-spec.md) | Always, once per session — scope, features, out-of-scope |
| [docs/02-architecture.md](docs/02-architecture.md) | Structural changes, new modules or dependencies |
| [docs/03-contracts.md](docs/03-contracts.md) | **Source of truth**: REST/SSE API, DB tables, Itinerary schema, tag rules |
| [docs/04-ui-spec.md](docs/04-ui-spec.md) | Any frontend work |
| [docs/05-agents-and-integrations.md](docs/05-agents-and-integrations.md) | LLM provider, prompts, tools, external APIs |
| [docs/06-implementation-plan.md](docs/06-implementation-plan.md) | Find the current phase, tasks, acceptance criteria |
| [docs/setup-guide.md](docs/setup-guide.md) | Env vars, keys, run modes |
| [docs/decisions.md](docs/decisions.md) | Before re-opening a settled choice; append new decisions |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branch/PR workflow |

## Stack (decided — see docs/decisions.md before changing)

- **Frontend:** React 18 + TypeScript + Vite, Tailwind CSS, shadcn/ui, Zustand,
  `@vis.gl/react-google-maps`, `@microsoft/fetch-event-source`, `react-markdown`.
- **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLModel on SQLite (local file),
  `sse-starlette`, `httpx`. LLM behind a provider adapter (`anthropic` SDK first).
- **Packages:** backend venv + `pip` (`backend/requirements.txt`); frontend `npm`.

## Repository layout (target)

```
frontend/src/
  api/          ApiClient interface, http.ts, mock.ts
  components/   layout/ history/ chat/ plan/ map/ checklist/ common/ (TagBadge…)
  store/        Zustand stores
  types/        TS types mirroring docs/03-contracts.md
  lib/          format.ts (dates, 12h time, °F, miles, money)
  fixtures/     mock sessions / itineraries
backend/app/
  main.py       app factory, CORS, routers
  api/          sessions.py, chat.py, checklist.py
  core/         config.py (pydantic-settings)
  db/           engine, tables, repositories, seed.py
  schemas/      Pydantic models (TripProfile, Itinerary, ItineraryDraft, DTOs)
  llm/          base.py (protocol), anthropic_provider.py, fake_provider.py, openai_compat_provider.py, factory.py
  agent/        orchestrator.py, tags.py, postprocess.py, sse.py, prompts/
  tools/        weather.py, maps.py, hotels.py, links.py (+ mock providers)
backend/tests/
docs/
```

## Commands

```bash
# backend (repo root, venv active — see docs/setup-guide.md)
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend      # http://localhost:8000/docs
pytest backend/tests

# frontend
cd frontend && npm install
npm run dev                                          # http://localhost:5173
npm run build && npm run lint
```

## Working rules

1. **Work phase by phase** from `docs/06-implementation-plan.md`. Do only the requested
   tasks; verify acceptance criteria; mark tasks ☑; stop and summarize.
2. **Contracts first.** `docs/03-contracts.md` defines API and schemas; `src/types/` and
   `app/schemas/` must match. Change the doc in the same change.
3. **UI first against mocks.** Components never call `fetch` directly — always `src/api/`.
4. **Simplicity.** No extra frameworks (no Redux, Celery, LangChain, Docker) unless
   `docs/decisions.md` adds them. Code should be easy for teammates to read.
5. **Secrets** only in git-ignored `.env` files; keep `.env.example` current. LLM and server
   keys never reach the browser; only the referrer-restricted Maps browser key does.
6. **LLM code goes through `app/llm/`.** No provider SDK types outside the adapters. Before
   writing or changing the Anthropic adapter, load the `claude-api` skill (model IDs,
   streaming, structured outputs change often — don't rely on memory).
7. **Tags are assigned by code** (`agent/tags.py`), never by the LLM. Prices and weather come
   from tool results, never from LLM text.
8. **Tools** are plain Python functions with a mock provider, so tests and offline dev never
   hit the network. Cache live calls in `api_cache`.
9. **Tests:** pytest for backend (tools, tags, postprocess, routes with `LLM_PROVIDER=fake`).
   Frontend: Vitest only for non-trivial logic.
10. Record non-trivial decisions in `docs/decisions.md`.
