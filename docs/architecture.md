# Architecture

How the code is organised and how a chat turn becomes a plan. The guiding rule is to **keep it
simple**: plain functions, one obvious place for each thing, and no performance work until
the MVP is feature-complete.

## 1. Big picture
```
┌──────────────── Browser: React + TS + Vite (frontend/) ────────────────┐
│ HistoryRail │ Plan / Map / Book tabs │ ChatPanel                         │
│             │ (render Itinerary JSON) │ (POST + SSE stream)              │
└──────┬──────┴────────────┬────────────┴──────────────┬──────────────────┘
       │ REST (JSON)       │ OSM map tiles             │ SSE
       ▼                   ▼ (Leaflet, no key)         ▼
┌──────────────────────── FastAPI backend (backend/app/) ────────────────┐
│ api/  sessions.py  chat.py  bookings.py          (thin routes)          │
│ agent/ turn.py  ─▶ understand (LLM JSON) ─▶ reply (LLM stream)          │
│        pipeline.py ─▶ gather (tools) ─▶ compose (LLM JSON) ─▶ postprocess│
│        tags.py  postprocess.py  prompts/*.md                            │
│ llm/   base.py  fake_provider.py  openai_compat_provider.py  factory.py │
│ tools/ weather.py  places.py  hotels.py  links.py   (+ mock JSON)       │
│ db/    engine, tables, repo.py       → SQLite file backend/travel.db    │
└────────────────────────────────────────────────────────────────────────┘
        │ Open-Meteo        │ Geoapify / Nominatim     │ SerpApi (hotels)
```

## 2. Stack
| Part | Choice | Why |
|---|---|---|
| Backend | Python 3.11+, **FastAPI**, Uvicorn, Pydantic v2, pydantic-settings | Easy async streaming, validation, auto docs at `/docs` |
| DB | **SQLite** via **SQLModel** | A local file and nothing to install. Our data is tiny (chat text + JSON plans) |
| Streaming | `sse-starlette` (server), `@microsoft/fetch-event-source` (client) | One-way stream; works with POST |
| HTTP to APIs | `httpx` | Simple, easy to mock in tests |
| LLM | `openai` SDK against the **TAMU AI** OpenAI-compatible endpoint; `fake` provider offline | Free for us; the fake provider makes tests and offline dev key-free |
| Frontend | React 18 + TypeScript + Vite, **Tailwind**, **Zustand**, `lucide-react`, `react-markdown` | Already used by the v0; small, readable |
| Map | **Leaflet** + `react-leaflet` + OpenStreetMap tiles | Free, no key, no card; already in the v0 |
| Tests | **pytest** (backend), **Vitest + React Testing Library** (frontend) | Every step adds tests |

No Redux, LangChain, Celery or Docker. shadcn/ui is optional (plain Tailwind is fine).

## 3. Backend layout
```
backend/
  requirements.txt
  app/
    main.py            app factory, CORS (http://localhost:5173), routers under /api, create tables
    core/config.py     Settings from backend/.env (pydantic-settings)
    db/                engine.py, tables.py, repo.py (plain functions: create_session, add_message, save_itinerary…)
    schemas/           Pydantic models from contracts.md (profile.py, itinerary.py, dto.py, turn.py)
    api/               sessions.py, chat.py, bookings.py — thin: validate, call agent/ or repo, return
    llm/               base.py, fake_provider.py, openai_compat_provider.py, factory.py
    agent/
      turn.py          one chat turn: understand → (generate | reply) → SSE events
      understand.py    TurnAnalysis JSON call + profile merge + missing_required
      pipeline.py      generation: gather → compose → postprocess → save
      postprocess.py   draft → Itinerary (tags, ids, weather, coords, prices, links, bookings, validation)
      tags.py          letter tags (contracts §3)
      context.py       builds the per-turn context text (today's date, profile, compact itinerary)
      prompts/         system.md, understand.md, compose.md (plain markdown files)
      sse.py           tiny helpers to build SSE events
    tools/             weather.py, places.py, hotels.py, links.py, common.py (mock switch, cache, errors)
      mocks/           recorded JSON responses used in mock mode and tests
  tests/               test_*.py mirroring app modules; fixtures/ with JSON
```

## 4. How a chat turn works (no LLM tool-calling)
We **don't** rely on the model's tool/function calling. Code decides what to run, which keeps
it simple, testable, and working with any model.

`POST /sessions/{id}/messages`, implemented in `agent/turn.py`:
1. Save the user message and emit `message_start`.
2. **Understand:** one `complete_json` call returns a `TurnAnalysis` (contracts §2.4). Merge
   `profile_updates` into the session profile, recompute `missing_required`, and emit `profile`
   if it changed. Auto-title once the city and dates are known (plain code, no LLM), and emit
   `title`.
3. Then, by `action`:
   - `chat`: stream a reply with `stream_text`. The context includes the profile and the
     compact itinerary, plus the forecast once the weather step exists. Emit `token`s.
   - `generate` / `edit`: run the **pipeline** (§4.1) and emit `status` lines and
     `itinerary`. Then stream a short reply: a 1–3 line summary using `[C]` tags.
4. Save the assistant message (with `itinerary_version` if a plan was made) and emit `done`.
   Any exception → `error` (the previous plan is untouched).

### 4.1 Generation pipeline (`agent/pipeline.py`)
1. **Gather:** code calls the tools directly, depending on which steps exist:
   - `weather.get_forecast(city, dates)`;
   - `places.search(city, interest)` for each interest;
   - `hotels.search(city, dates, travelers)`.
   Each call emits a `status` start/end line. A failed tool returns an error result, and the
   pipeline continues without that data.
2. **Compose:** one `complete_json` call → `ItineraryDraft`. The prompt includes the profile,
   the gathered results (each with a short id the draft can cite as `place_ref`), and, for an
   edit, the previous itinerary + `change_request` with "change only what was asked".
3. **Postprocess** (pure functions, the most-tested code):
   - assign tags;
   - copy coordinates, addresses, prices and weather **from tool results** (never from LLM
     text);
   - estimate travel between stops;
   - build links and bookings;
   - set `updated_in_version`;
   - validate.
   If validation fails, run one repair attempt: compose again with the errors.
4. Save as a new version, set the session to `planned`, and emit `itinerary`.

## 5. External services (all free, no card)
| Service | Used for | Key | Limits / notes |
|---|---|---|---|
| **TAMU AI** (`chat-api.tamu.ai`, OpenAI-compatible) | the LLM | TAMU account key | Check the model id and JSON-output support (step 10) |
| **Open-Meteo** forecast + archive + geocoding | weather; city coordinates | none | Free for non-commercial use; credit "Weather data by Open-Meteo.com" |
| **Geoapify** Places + Geocoding | place suggestions, addresses, coordinates | free account, no card | About 3,000 requests/day on the free plan |
| **Nominatim** (OpenStreetMap) | geocoding fallback | none | ≤ 1 request/second; send a descriptive User-Agent (app name) |
| **OpenStreetMap tiles** | map background (Leaflet) | none | Light use only; keep the "© OpenStreetMap" attribution |
| **SerpApi** Google Hotels | hotel prices | free account | Small monthly quota, so cache results 6 h. Without a key → hotels without prices |

Real flight fares (SerpApi Google Flights) and an Anthropic adapter are optional extras for
after the MVP.

## 6. LLM layer (`app/llm/`)
Provider SDKs are imported **only** here.
```python
class LLMProvider(Protocol):
    name: str
    def stream_text(self, system: str, messages: list[dict]) -> AsyncIterator[str]: ...
    async def complete_json(self, system: str, messages: list[dict], schema: type[T]) -> T: ...
# messages = [{"role": "user" | "assistant", "content": "..."}]
```
- `fake_provider.py`: deterministic and offline.
  - `stream_text` yields canned text in chunks.
  - `complete_json` returns a scripted `TurnAnalysis`, using simple keyword rules ("plan",
    "generate" → generate; a `[X]` tag or "replace" with a plan present → edit).
  - For `ItineraryDraft` it returns fixture drafts (the San Jose trip v1 / v2).
- `openai_compat_provider.py`: `AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)`.
  - `stream_text` uses `stream=True`.
  - `complete_json` asks for JSON (`response_format` if the endpoint supports it, else
    "reply with JSON only" + the schema in the prompt). It parses with Pydantic and retries
    once on a parse error.
- `factory.py`: `get_provider(settings)` by `LLM_PROVIDER`.

## 7. Tools (`app/tools/`)
- Plain **synchronous** functions with typed inputs and outputs, using `httpx.Client` and a
  10 s timeout. The agent calls them with `await asyncio.to_thread(...)`.
- They never raise to the caller. They return `{"ok": false, "error": "..."}` (a small
  `ToolResult` model).
- `TOOL_PROVIDER_MODE=mock` returns recorded JSON from `tools/mocks/`. Tests always use mock
  mode. Live smoke tests are marked `@pytest.mark.live` and skipped by default.
- `common.py`: the mock switch, the `api_cache` get/set, and error helpers. Only quota-limited
  calls must be cached (hotels). Caching the others is fine but optional.

## 8. Frontend layout
```
frontend/src/
  types/        TS types mirroring contracts.md
  api/          client.ts (ApiClient interface), http.ts (REST + SSE). Components never call fetch.
  store/        Zustand: useTripStore (session, messages, itinerary, streaming state), useHistoryStore
  lib/          format.ts (12h time, °F, miles, money, dates), tags.ts (parse [C] tokens, diff helpers), map.ts
  components/   App shell + v0 components: HistoryRail, PlanView, MapView, BookView, ChatPanel, TagBadge…
  fixtures/     contract-shaped JSON (San Jose v1/v2) for tests and empty-backend dev
  test/         setup + shared test utils
```
`VITE_API_BASE_URL` points at the backend (default `http://localhost:8000/api`). There is no
separate frontend mock mode: run the backend with `LLM_PROVIDER=fake` + `TOOL_PROVIDER_MODE=mock`.

## 9. Configuration
- `backend/.env` (git-ignored; template `backend/.env.example`): `LLM_PROVIDER`, `LLM_MODEL`,
  `LLM_API_KEY`, `LLM_BASE_URL`, `TOOL_PROVIDER_MODE`, `GEOAPIFY_KEY`, `SERPAPI_KEY`,
  `DATABASE_URL` (optional).
- `frontend/.env.local` (git-ignored; template `frontend/.env.example`): `VITE_API_BASE_URL`.
- No key ever reaches the browser. The map needs none.

## 10. Testing approach
- **Backend:** pytest, with `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock` and a temporary
  SQLite DB per test (fixture in `tests/conftest.py`).
  - Unit tests for pure logic: tags, postprocess, profile merge, links, format.
  - Tool tests run on recorded JSON.
  - Route tests use FastAPI `TestClient`, including SSE event order.
- **Frontend:** Vitest + React Testing Library (jsdom). Unit tests for `lib/` and stores;
  component tests for key behaviour (renders a fixture plan, tag click, disabled tabs). Leaflet
  is mocked in tests.
- **Full check** (must pass before a step counts as done): `pytest backend/tests`,
  `npm test`, `npm run lint`, `npm run build`.
