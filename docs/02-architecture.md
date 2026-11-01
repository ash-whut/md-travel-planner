# 02 — Architecture

## 1. High-level picture

```
┌──────────────────────── Browser (React + Vite) ────────────────────────┐
│ History sidebar │  Plan / Map / Checklist tabs   │   Chat panel        │
│                 │  (renders Itinerary JSON)      │   (SSE stream)      │
└────────┬────────────────────────┬──────────────────────────┬───────────┘
         │ REST (JSON)            │ Google Maps JS API        │ POST + SSE
         ▼                        ▼ (browser key)             ▼
┌──────────────────────────── FastAPI backend ───────────────────────────┐
│  api/sessions.py   api/chat.py   api/checklist.py                       │
│        │                 │                                              │
│        ▼                 ▼                                              │
│   db/ (SQLModel)   agent/orchestrator.py ──▶ llm/ provider adapter      │
│   SQLite file            │ tool calls          (anthropic | fake | …)   │
│   (local, no cloud)      ▼                                              │
│     tools/weather.py  tools/maps.py  tools/hotels.py  tools/links.py    │
│     agent/tags.py (letter tags)   agent/postprocess.py (validate/links)  │
└──────────┬──────────────────┬──────────────────┬────────────────────────┘
           ▼                  ▼                  ▼
      Open-Meteo        Google Places /      SerpApi Google Hotels
      (no key)          Geocoding / Routes   (fallback: Places lodging)
```

## 2. Why this stack

| Concern | Choice | Reason |
|---|---|---|
| Backend | **FastAPI** | Standard for Python LLM backends: async, streaming, Pydantic validation, auto OpenAPI docs at `/docs`. Lighter than Django; better streaming than Flask. |
| Frontend | **React + TS + Vite** | 3-pane layout, disabled tabs, interactive map and streaming chat need a real SPA. Python-only UI kits (Streamlit/Gradio) can't do this layout well. Best AI-agent fluency. |
| UI kit | Tailwind + shadcn/ui | Copy-in components; no heavy design system. |
| State | Zustand | Tiny, no boilerplate. |
| DB | **SQLite** via SQLModel | See §2.1. |
| Streaming | SSE (`sse-starlette`) | One-way stream fits chat; simpler than WebSockets. Client: `@microsoft/fetch-event-source` (native `EventSource` can't POST). |
| LLM | Provider adapter, Anthropic first | Swappable by env var (05 §2). |
| Map | Google Maps JS via `@vis.gl/react-google-maps` | Requirement; Google's official React wrapper. |

### 2.1 Why SQLite is enough
- Our data is small and simple: a session row, its chat messages (text), and itinerary
  versions (one JSON document each, ~10–50 KB). Even 1,000 sessions is a few tens of MB.
  SQLite handles databases up to terabytes and is used in production by many apps.
- SQLite stores JSON in text columns and can query it with JSON functions; SQLModel
  serializes Pydantic models to these columns transparently.
- It's a **local file** (`backend/travel.db`) — no cloud account, no server, nothing to install
  (ships with Python).
- Limits that don't matter for us: many concurrent writers (we have one user), and sharing
  one DB across machines (each teammate has their own local DB; a seed script gives
  everyone the same demo data).
- **Upgrade path:** if we ever deploy for multiple users, change `DATABASE_URL` to Postgres;
  SQLModel/SQLAlchemy code stays the same.

## 3. Backend modules

- `app/main.py` — app factory, CORS (`http://localhost:5173`), routers under `/api`, create tables on startup.
- `app/core/config.py` — `pydantic-settings` `Settings` from `.env` (full list in setup-guide.md).
- `app/db/` — engine, tables (`Session`, `Message`, `Itinerary`, `ApiCache`), repository functions, `seed.py`.
- `app/schemas/` — Pydantic models from 03-contracts (`TripProfile`, `Itinerary`, `ItineraryDraft`, DTOs, SSE payloads).
- `app/api/` — thin routes.
- `app/llm/` — provider protocol + adapters (05 §2).
- `app/agent/orchestrator.py` — tool loop and phases; exposes
  `run_chat_turn(session_id, text) -> AsyncIterator[SseEvent]` and `run_generation(session_id, change_request) -> AsyncIterator[SseEvent]`.
- `app/agent/tags.py` — deterministic letter-tag assignment (03 §2.2 tag rules).
- `app/agent/postprocess.py` — draft → Itinerary: IDs, tags, links, prices, checklist, validation.
- `app/agent/prompts/` — system prompt `.md` files (byte-stable for caching).
- `app/tools/` — one module per "sub-agent" + mock providers. No LLM knowledge.

## 4. Frontend modules

- `src/api/client.ts` — `ApiClient` interface; `http.ts` real; `mock.ts` in-memory (selected by `VITE_USE_MOCKS`).
- `src/store/` — `useSessionsStore`, `useChatStore`, `usePlanStore` (itinerary, tab, selected day/place).
- `src/lib/format.ts` — dates, 12h times, °F, miles, money.
- `src/components/` — see 04-ui-spec §2.

## 5. Key flows

### 5.1 Chat turn
1. UI appends user message, opens `POST /api/sessions/{id}/messages` stream.
2. Backend saves it; orchestrator streams `token`s; tool calls → `status`; profile changes → `profile`.
3. If the model calls `generate_itinerary`, generation runs in the same stream → `itinerary`.
4. Assistant message saved → `done`.

### 5.2 Generation / edit
1. Research loop with tools (`status` per call).
2. Structured `ItineraryDraft` from the LLM (for edits: given previous itinerary + change request).
3. `postprocess.py`: tags (stable vs. previous versions), IDs, links, hotel prices with `price_as_of`, checklist, validation (+1 repair attempt).
4. Persist new version → `itinerary` event.

### 5.3 Reopen session
`GET /api/sessions/{id}` → messages + latest itinerary + profile; tabs enable if itinerary exists.

## 6. Configuration & secrets

- `backend/.env` + `backend/.env.example`; `frontend/.env.local` + `frontend/.env.example`.
- Two Google keys: browser key (Maps JavaScript API, HTTP-referrer restricted) and server key (Places/Geocoding/Routes, API restricted).
- Running without any keys: `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock`, `VITE_USE_MOCKS=false` → full stack works on fixtures.
- Setup steps: [setup-guide.md](setup-guide.md).

## 7. Error handling

- Tools return `{"ok": false, "error": …}`; passed to the LLM as error tool results.
- SSE `error` event; UI shows inline with Retry.
- A new itinerary version is written only after validation passes.

## 8. Testing strategy

- **Tools:** unit tests on recorded fixtures (no network); `pytest -m live` smoke tests.
- **Tags / postprocess:** unit tests incl. stability across versions and retired letters.
- **API:** `TestClient` with `LLM_PROVIDER=fake`.
- **Agent quality:** `backend/tests/scenarios/` personas run manually with a real model.
- **Frontend:** manual QA in mock mode; Vitest for stores/format helpers.

## 9. Future-proofing (don't build now)

- Tools → MCP servers (FastMCP) or LLM sub-agents without changing the orchestrator contract.
- `ApiClient` abstraction allows auth headers / another backend in one place.
- Postgres via `DATABASE_URL` for deployment.
