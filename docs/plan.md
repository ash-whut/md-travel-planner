# Build plan (numbered steps)

The whole project, as small numbered steps in build order. Each step says exactly what gets
built, which files it touches, which tests it adds, and when it counts as done.

**How to use**
- Pick the next open steps and claim them by writing ◐ + your initials in the heading.
- Run `/build-steps <numbers>` in Claude Code (see [README](../README.md#how-to-develop)). It
  builds, tests and reviews them, then you commit them as one commit.
- Every step leaves the app runnable offline (`LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock`),
  and the test suite only grows.
- **Full check:** `pytest backend/tests` · `npm test` · `npm run lint` · `npm run build`. It must
  be green before a step is ☑. Checks that don't exist yet are skipped. For example, there is no
  pytest before step 2.
- `[HUMAN]` steps need a person (an account, a key, or a manual check). Agents stop there.
- Steps marked *FE* or *BE* can be done in parallel by different people once their
  dependencies are done.

Status: ☐ todo · ◐ in progress (initials) · ☑ done

| Milestone | Steps | You can demo |
|---|---|---|
| A. Foundation | 1–9 | v0 UI on contract types + a running backend skeleton |
| B. Chat | 10–17 | real chat with TAMU AI, streaming, stop, profile stepper |
| C. Plan view | 18–24 | "make the plan" → AI-drafted day cards with letters |
| D. Edit by letter | 25–27 | "replace [F]…" → v2 with stable letters + highlight |
| E. Weather | 28–31 | real °F weather per day |
| F. Places + Map | 32–36 | real places with coordinates; Map tab works |
| G. Hotels | 37–41 | real hotel price "as of"; flights as links |
| H. Book | 42–43 | Book tab with links, approval and booked status |
| I. History | 44–45 | history rail: list, open, rename, delete |
| J. Polish | 46–47 | demo-ready |
| Stretch | 48–49 | booking help, real flight fares |

---

## A. Foundation

### 1 · Env templates — ☑
- **Builds:** `backend/.env.example` and `frontend/.env.example` with every variable from
  [architecture §9](architecture.md), a comment per variable, and safe defaults
  (`LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock`). The root `.gitignore` already exists.
- **Files:** `backend/.env.example`, `frontend/.env.example`
- **Tests:** none (config only).
- **Done when:** both templates exist; `git status` doesn't list `backend/.env` or `*.db`.
- **Notes:** Both templates added; the local backend/.env is stale (old Google Maps keys), so copy the new template over it.

### 2 · Backend skeleton — ☑ *BE*
- **Builds:** `requirements.txt`, a FastAPI app factory with CORS for `http://localhost:5173`,
  a `Settings` class reading `backend/.env`, and `GET /api/health`.
- **Files:** `backend/requirements.txt` (fastapi, uvicorn[standard], pydantic,
  pydantic-settings, sqlmodel, sse-starlette, httpx, openai, pytest),
  `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/api/health.py`,
  `backend/tests/conftest.py`, `backend/tests/test_health.py`, `backend/pytest.ini` or
  `pyproject.toml` (sets `pythonpath`, registers the `live` marker and skips it by default)
- **Tests:** health returns `{ok, llm_provider, tool_mode}`; conftest forces fake/mock settings.
- **Done when:** `uvicorn app.main:app --app-dir backend` serves `/api/health`; `pytest` is green.
- **Notes:** App factory, Settings (extra=ignore, env beats .env) and health are in; 20 tests. A stray pytest-asyncio in .venv only causes a warning.

### 3 · Database tables + repository — ☑ *BE*
- **Builds:** a SQLite engine (default file `backend/travel.db`), `session` + `message`
  tables (contracts §1), tables created on startup, and plain repository functions.
- **Files:** `backend/app/db/engine.py`, `db/tables.py`, `db/repo.py` (`create_session`,
  `get_session`, `add_message`, `list_messages`, `update_profile`), `tests/conftest.py`
  (temp-DB fixture), `tests/test_repo.py`
- **Tests:** create/get session; messages come back in order; profile update saved;
  `updated_at` bumps on a new message.
- **Done when:** repo tests pass on a temp DB; the app starts and creates the file.
- **Notes:** SQLModel tables + repo with tz-aware UTC and FK cascade; autouse temp DB in conftest. The old prototype backend/travel.db has a different schema, so delete it.

### 4 · Sessions API (create + get) — ☑ *BE*
- **Builds:** `POST /api/sessions` (new session + a fixed greeting assistant message
  "Hi, where do you want to go?") and `GET /api/sessions/{id}` returning `SessionDetail`
  (contracts §2.6, `itinerary: null` for now).
- **Files:** `backend/app/schemas/profile.py` (TripProfile fields, all optional),
  `schemas/dto.py`, `api/sessions.py`, `tests/test_sessions_api.py`
- **Tests:** create → 200 with greeting; get → same data; unknown id → 404.
- **Done when:** both routes work in `/docs`; tests green.
- **Notes:** POST/GET sessions + TripProfile; budget_level is stored as null (budget is assumed at compose time), and missing_required stays [] until step 16.

### 5 · LLM layer + fake provider — ☑ *BE*
- **Builds:** the `LLMProvider` protocol (architecture §6), a fake provider whose
  `stream_text` yields canned chunks and whose `complete_json` raises a clear error for
  schemas it doesn't know yet, and `get_provider(settings)`.
- **Files:** `backend/app/llm/base.py`, `llm/fake_provider.py`, `llm/factory.py`,
  `tests/test_llm_fake.py`
- **Tests:** fake streams several chunks that join to the canned text; the factory returns
  fake for `LLM_PROVIDER=fake` and errors clearly on an unknown name.
- **Done when:** tests green; no provider SDK is imported outside `app/llm/`.
- **Notes:** LLMProvider protocol + word-chunk FakeProvider; the factory rejects openai_compat until step 12. Async tests use asyncio.run (no pytest-asyncio).

### 6 · Frontend test + lint tooling — ☑ *FE*
- **Builds:** Vitest + React Testing Library + jsdom, ESLint (typescript-eslint +
  react-hooks), `npm test` and `npm run lint` scripts, and a test setup that mocks
  `react-leaflet`.
- **Files:** `frontend/package.json`, `frontend/vite.config.ts` (test block),
  `frontend/eslint.config.js`, `frontend/src/test/setup.ts`, `frontend/src/App.test.tsx`
- **Tests:** smoke test: `<App/>` renders the Plan tab and the Chat header.
- **Done when:** `npm test`, `npm run lint`, `npm run build` all pass (fix lint errors in the
  v0 code if any).
- **Notes:** Vitest+RTL+jsdom and ESLint flat config; setup.ts mocks react-leaflet and stubs scrollIntoView and ResizeObserver. The v0 code had no lint errors. Known warning: a button nested in a button (TagBadge in the MapView stop list).

### 7 · Contract types + format helpers — ☑ *FE*
- **Builds:** TypeScript types mirroring contracts §2 + the SSE event types, and the formatting
  helpers the UI uses everywhere.
- **Files:** `frontend/src/types/index.ts`, `frontend/src/lib/format.ts`,
  `frontend/src/lib/format.test.ts`
- **Tests:** `formatTime("09:15")` → "9:15 AM"; `formatDate("2027-03-05")` → "Fri, Mar 5";
  date range "Mar 5–7"; money "$300"; duration 90 → "1.5 hr"; nights; °F; miles.
- **Done when:** tests green; types compile.
- **Notes:** types/index.ts mirrors contracts §2, §4 and §5 (checked with satisfies); format.ts parses dates by hand so the timezone can never shift the day.

### 8 · Contract-shaped fixtures; v0 components use contract types — ☑ *FE*
- **Builds:** the v0 San Jose trip rewritten as contract JSON (`sanjose-v1.json`, and
  `sanjose-v2.json` where F is replaced and has `updated_in_version: 2`). PlanView, MapView,
  BookView, ChatPanel and TagBadge take contract-typed props. The old `src/types.ts` and
  `src/fixtures.ts` are removed. **No visual change** (compare with `docs/preview/`). The
  `?tab=…` demo params keep working.
- **Files:** `frontend/src/fixtures/*.json`, `frontend/src/components/*.tsx`,
  `frontend/src/App.tsx`, component tests
- **Tests:** PlanView renders letters A–E, G–L (F retired, its replacement is L per D9) and "Updated in v2" from v2; BookView renders 4 cards;
  MapView lists stops and "off map" stops.
- **Done when:** tests green; the UI looks like the screenshots. These fixtures are also loaded
  by backend tests (one shared copy).
- **Notes:** Fixtures are in frontend/src/fixtures/ (the shared copy). Following D9 (human choice), v2 replaces F with [L]; the preview still shows F. Off-map line now reads "Off map: A, B". Version dividers render above the message (step 26 says after, so settle it there).

### 9 · ApiClient + Zustand store; app loads a real session — ☑ *FE*
- **Builds:** an `ApiClient` interface + `http.ts` (`createSession`, `getSession` for now) and
  `useTripStore` (session, messages, profile, itinerary, streaming flag, status lines, an
  `applyEvent` reducer). On start, the app reads the session id from localStorage → `getSession`,
  or else `createSession`. Components read from the store. `?demo=1` loads the San Jose fixture
  into the store, which keeps screenshots reproducible.
- **Files:** `frontend/src/api/client.ts`, `api/http.ts`, `store/useTripStore.ts`,
  `store/useTripStore.test.ts`, `App.tsx`, `demoParams.ts`
- **Tests:** store actions/reducer; App with a fake ApiClient creates a session when none is
  stored and reuses a stored id.
- **Done when:** with the backend running, the page shows the greeting from the backend;
  `?demo=1` shows the full v0 trip.
- **Notes:** ApiClient + httpClient, useTripStore with a pure reduceEvent for all §5 events; a stored id that 404s creates a new session. Demo params need ?demo=1 to show the fixture. Not yet tried in a browser against uvicorn.

## B. Chat

### 10 · [HUMAN] Verify the TAMU AI API — ☑
- **Builds:** nothing in code. A teammate with a TAMU login confirms:
  - the base URL (`https://chat-api.tamu.ai`?);
  - the exact model id;
  - that streaming works;
  - whether `response_format` JSON / JSON-schema is supported.
  They fill in `backend/.env` and write the findings into [decisions.md](decisions.md).
- **Done when:** a short `openai` SDK snippet streams a reply and returns valid JSON for a tiny
  schema.
- **Notes:** All 4 checks pass (plain reply, streaming, JSON mode, strict JSON schema); details in decisions D16. Non-streamed calls must pass `stream=False` explicitly.

### 11 · Chat endpoint over SSE (fake LLM) — ☑ *BE*
- **Builds:** `POST /api/sessions/{id}/messages`. It saves the user message, emits
  `message_start`, streams `token`s from `stream_text`, saves the assistant message, and emits
  `done`. Any exception → an `error` event (the user message is kept).
- **Files:** `backend/app/api/chat.py`, `agent/sse.py`, `agent/turn.py`,
  `tests/test_chat_api.py`
- **Tests:** event order `message_start → token… → done`; both messages are in the DB; unknown
  session → 404; a provider that raises → an `error` event.
- **Done when:** tests green; curl shows the stream.
- **Notes:** SSE chat in; `get_llm` is a dependency (override it in tests), and `add_message` takes an optional id. A bad or blank body gives 422 (now in contracts §4).

### 12 · OpenAI-compatible provider (TAMU AI) — ☑ *BE* (needs 10)
- **Builds:** `openai_compat_provider.py` with `stream_text` (`stream=True`) and
  `complete_json` (uses `response_format` if step 10 said it's supported, else a "JSON only"
  instruction; parses with Pydantic and retries once). Registered in the factory.
- **Files:** `backend/app/llm/openai_compat_provider.py`, `llm/factory.py`,
  `tests/test_llm_openai_compat.py`
- **Tests:** with a stubbed client object (no network): stream chunks joined; JSON parsed into
  a model; a bad JSON then a good JSON → success after the retry. One `@pytest.mark.live` test.
- **Done when:** tests green; a manual chat with `LLM_PROVIDER=openai_compat` streams a real reply.
- **Notes:** Provider takes an injectable `client=`; the json_schema is non-strict because Pydantic schemas don't meet strict rules, and the reply is validated anyway. The live test (`pytest -m live`) passes against TAMU AI.

### 13 · System prompt + per-turn context — ☑ *BE*
- **Builds:** `prompts/system.md` (friendly budget planner; intake rules; ≤ 2 questions per turn;
  scope limits; short replies; use `[C]` tags; never claim to book) and `context.py`, which
  builds the system text with today's date and the current profile.
- **Files:** `backend/app/agent/prompts/system.md`, `agent/context.py`, `agent/turn.py`,
  `tests/test_context.py`
- **Tests:** the context contains today's date and known profile fields; the prompt file loads.
- **Done when:** tests green; with the real LLM the agent asks about destination/dates naturally.
- **Notes:** `build_system(profile, today=)` adds a "# Context" block. The prompt already mentions the Generate button (step 23), and the real-LLM tone hasn't been checked by hand yet.

### 14 · Frontend chat wired to the backend — ☑ *FE* (needs 9, 11)
- **Builds:**
  - `sendMessage` in `http.ts` via `@microsoft/fetch-event-source`;
  - the store handles `message_start`, `token`, `done` and `error`;
  - ChatPanel sends (Enter / Shift+Enter), shows the streaming bubble with markdown
    (`react-markdown`), and disables the input while streaming;
  - errors show inline with Retry, and the panel auto-scrolls.
- **Files:** `frontend/src/api/http.ts`, `store/useTripStore.ts`,
  `components/ChatPanel.tsx`, tests
- **Tests:** the reducer builds the assistant message from a token sequence; error → error
  bubble; the input is disabled while streaming; Retry resends.
- **Done when:** chatting in the browser with the fake LLM works; a reload shows the history.
- **Notes:** SSE via fetch-event-source (auto-retry off) and react-markdown. Retry resends the text, so the backend saves the user message twice (open decision). Not yet tried in a browser.

### 15 · Stop button — ☑ *BE+FE*
- **Builds:** Stop aborts the stream (AbortController). The backend notices the disconnect or
  cancellation and saves the partial text with " *(stopped)*".
- **Files:** `components/ChatPanel.tsx`, `api/http.ts`, `backend/app/agent/turn.py`, tests
- **Tests:** BE: closing the turn generator early saves partial text + the marker. FE: Stop
  calls abort and re-enables the input.
- **Done when:** Stop works mid-reply in the browser.
- **Notes:** `turn.py` saves partial + marker on close/cancel; the store's `stop()` adds the same marker locally. Not yet tried in a browser.

### 16 · Understand step + trip profile — ☑ *BE*
- **Builds:**
  - full `TripProfile` + `missing_required()`;
  - `TurnAnalysis` (contracts §2.4);
  - `understand.py`, which makes one `complete_json` call per user turn and merges
    `profile_updates` (only the given fields; lists replaced);
  - `turn.py` emits `profile` when the profile changed;
  - a scripted fake `TurnAnalysis` that walks through the San Jose demo.
  Only `action=chat` is handled for now.
- **Files:** `backend/app/schemas/profile.py`, `schemas/turn.py`, `agent/understand.py`,
  `agent/prompts/understand.md`, `llm/fake_provider.py`, `agent/turn.py`,
  `tests/test_understand.py`
- **Tests:** merge rules; `missing_required` for empty/partial/full; the `profile` event is
  emitted only on change; the profile is saved to the DB.
- **Done when:** tests green; with the real LLM, telling it "San Jose, first weekend of March"
  fills those fields.
- **Notes:** Per D17, `budget_level` stays null and a failed understand call falls back to plain chat. `missing_required` is recomputed whenever a profile is returned (`load_profile`), and the fake LLM scripts the San Jose demo by keywords.

### 17 · Profile chips + chat-header stepper — ☑ *FE* (needs 16)
- **Builds:** `lib/profile.ts` (`stepperState(profile, hasPlan)`, `profileChips(profile)`). The
  stepper (Profile — Trip details — Plan) in the chat header, and profile chips in the plan
  header / empty state, all driven by `profile` events.
- **Files:** `frontend/src/lib/profile.ts`, `components/ChatPanel.tsx`,
  `components/PlanView.tsx`, tests
- **Tests:** stepper states for empty/partial/full profile; chip labels; missing items shown
  muted.
- **Done when:** the stepper ticks as you chat.
- **Notes:** The stepper reads the server's `missing_required` instead of re-deriving the field rules; `ProfileChips` is exported from PlanView. Not yet tried in a browser.

## C. Plan view (LLM only, no external tools yet)

### 18 · Itinerary + draft schemas with validation — ☐ *BE*
- **Builds:** Pydantic models for `Itinerary` (stops, lodging, days, items, bookings, weather,
  money) and `ItineraryDraft` (contracts §2.3), plus the validation rules from contracts §2.2.
- **Files:** `backend/app/schemas/itinerary.py`, `tests/test_itinerary_schema.py`
- **Tests:** `frontend/src/fixtures/sanjose-v1.json` and `-v2.json` validate. Each of these
  fails: a day gap, unsorted items, an unknown `stop_tag`, > 2 cities, > 7 days, bad lat/lng.
- **Done when:** tests green.
- **Notes:** Schema tests load the shared fixtures from `frontend/src/fixtures/*.json`.

### 19 · Letter tags — ☐ *BE*
- **Builds:** `tags.py`: the letter sequence (A…Z, AA…), name normalization, and
  `assign_tags(draft, previous_versions)` implementing contracts §3.
- **Files:** `backend/app/agent/tags.py`, `tests/test_tags.py`
- **Tests:** v1 order by day/time; the same stop twice → one tag; a kept stop keeps its letter
  in v2; a new stop gets the next letter after the highest used; a removed letter is never
  reused; Z → AA; a `place_id` match beats a name difference.
- **Done when:** tests green.
- **Notes:** —

### 20 · Itinerary storage — ☐ *BE*
- **Builds:** the `itinerary` table and repo functions (`save_itinerary` with the next version,
  `get_latest_itinerary`, `list_itineraries`). `GET /sessions/{id}` now returns the latest
  itinerary.
- **Files:** `backend/app/db/tables.py`, `db/repo.py`, `api/sessions.py`, tests
- **Tests:** versions increment per session; latest is returned; GET includes it.
- **Done when:** tests green.
- **Notes:** Change `SessionDetail.itinerary` in `schemas/dto.py` from `None` to `Itinerary | None`.

### 21 · Postprocess (draft → itinerary) — ☐ *BE*
- **Builds:** `build_itinerary(draft, previous_versions, profile)`:
  - tags, item ids (`d1-i1`…), version;
  - stops copied with coordinates `null`;
  - `cost_source: "ai_estimate"`, `source: "AI suggestion"` when missing;
  - weather `null`, bookings `[]`;
  - `updated_in_version` (contracts §3).
  It then validates and returns the itinerary or a list of errors.
- **Files:** `backend/app/agent/postprocess.py`, `tests/test_postprocess.py`,
  `tests/fixtures/draft_*.json`
- **Tests:** a good draft → a valid itinerary with expected letters; a v2 draft →
  `updated_in_version` only on the changed item; a bad draft → errors, no exception.
- **Done when:** tests green.
- **Notes:** —

### 22 · Compose call (+ one repair try) — ☐ *BE*
- **Builds:** `prompts/compose.md` (planning heuristics: budget first, cluster stops, 3–4 main
  stops a day, light travel days, sensible meal times, an assumptions list, no invented
  weather/coordinates) and `pipeline.compose(...)` → `ItineraryDraft` via `complete_json`. If
  postprocess returns errors, compose once more with the errors included. The fake provider
  returns `llm/fake_data/draft_sanjose_v1.json`.
- **Files:** `backend/app/agent/pipeline.py`, `agent/prompts/compose.md`,
  `llm/fake_provider.py`, `llm/fake_data/*.json`, `tests/test_pipeline.py`
- **Tests:** the fake path gives a valid itinerary; a fake that returns a bad then a good draft
  → success after 1 repair; bad twice → a clear failure.
- **Done when:** tests green.
- **Notes:** —

### 23 · Generate endpoint + "make the plan" from chat — ☐ *BE*
- **Builds:** `run_generation(session, change_request=None)`:
  - emits `status` ("Drafting your plan…"), saves the new version, sets the session to
    `planned`, and emits `itinerary`;
  - `POST /sessions/{id}/generate` uses it;
  - in `turn.py`, `action=generate` runs it and then streams a short summary reply whose
    message gets `itinerary_version`.
  A failure → `error`, and the previous plan is untouched.
- **Files:** `backend/app/agent/pipeline.py`, `agent/turn.py`, `api/chat.py`,
  `tests/test_generate_api.py`
- **Tests:** SSE order (`itinerary` before `done`); v1 saved; status `planned`; on failure no
  version is saved and `error` is emitted.
- **Done when:** tests green; "just make the plan" in chat produces a plan with the fake LLM.
- **Notes:** `TurnAnalysis.action` `generate`/`edit` are parsed by step 16 but every action runs as chat; route them in `turn.py` here (edit in step 25). `prompts/system.md` now says making the plan "is not available in the app yet", so the model stops faking it. Replace that bullet here with the real flow ("click **Generate** or say 'make the plan'"), and put the current plan in the context so the "a plan exists only if the context includes one" rule holds.

### 24 · Plan tab from real data — ☐ *FE* (needs 14, 23)
- **Builds:**
  - PlanView renders the store itinerary;
  - the empty state + a Generate button (`api.generate`, same event handling);
  - skeleton day cards with the current status line while generating;
  - "Why this?" shows `why` + `source`;
  - Map/Book tabs disabled with the tooltip "Generate a plan to unlock";
  - an `itinerary` event switches to the Plan tab;
  - a reload shows the saved plan.
- **Files:** `frontend/src/components/PlanView.tsx`, `App.tsx`, `api/http.ts`, store, tests
- **Tests:** empty state → Generate calls the API; skeleton while generating; renders the
  fixture plan; disabled tabs are not clickable and have aria-disabled.
- **Done when:** in the browser: chat → generate → day cards with letters (fake and TAMU AI).
- **Notes:** —

## D. Edit by letter

### 25 · Edit path with stable letters — ☐ *BE*
- **Builds:**
  - `context.compact_itinerary(it)` (`Day 1 (Fri Mar 5): 06:00 [A] Home · 09:15 [B] IAH …`),
    added to every turn's context;
  - `action=edit` runs `run_generation` with the previous itinerary + `change_request`, and
    compose is told to change only what was asked;
  - the reply is a 1–3 line change summary using tags;
  - the fake returns the v2 draft.
- **Files:** `backend/app/agent/context.py`, `agent/turn.py`, `agent/pipeline.py`,
  `agent/prompts/compose.md`, `llm/fake_data/draft_sanjose_v2.json`, `tests/test_edit.py`
- **Tests:** v2 keeps every letter except the replaced stop; the new stop gets the next letter;
  `updated_in_version = 2` only on changed items; the assistant message has
  `itinerary_version = 2`; the compact listing format.
- **Done when:** tests green; "replace [F] with something vegan" works in the browser.
- **Notes:** —

### 26 · Version markers + "Updated in vN" — ☐ *FE* (needs 24)
- **Builds:** chat version markers ("Plan created · v1", "Plan updated · v2") after messages
  with `itinerary_version`, the header version badge, and the highlight bar + badge for items
  where `updated_in_version === itinerary.version > 1`.
- **Files:** `frontend/src/components/ChatPanel.tsx`, `components/PlanView.tsx`, tests
- **Tests:** markers render at the right places; only changed items are highlighted; there is no
  highlight on v1.
- **Done when:** tests green; it matches the preview.
- **Notes:** Step 8 draws the version divider above the message, but this step says after; settle it here. Also replace the hard-coded "updated just now" badge in PlanView.

### 27 · Tag chips in chat + stop picker — ☐ *FE*
- **Builds:**
  - `lib/tags.ts` `parseTagTokens(text)` → text/tag segments;
  - ChatPanel renders `[C]` as TagBadge chips inside markdown;
  - clicking a chip selects the tag (Plan scrolls + flashes the entry, Map focuses the pin);
  - the "+" picker lists stops and inserts `[C] `;
  - the placeholder switches once a plan exists.
- **Files:** `frontend/src/lib/tags.ts`, `lib/tags.test.ts`, `components/ChatPanel.tsx`, store
- **Tests:** the parser handles `[A]`, `[AA]` and adjacent tags, and ignores `[abc]` and
  markdown links; the picker inserts at the cursor; a chip click sets the selected tag.
- **Done when:** tests green.
- **Notes:** Move `dayColor`/`firstDayByTag` from TagBadge.tsx into `lib/tags.ts`, and replace `withTagChips` in ChatPanel (it and `AssistantMarkdown` duplicate the tag regex; fold both into `lib/tags.ts`, and handle LLM text that is already a link like `[A](url)`, which today becomes a chip plus a stray "(url)"). `?picker=1` still works without `?demo=1`; gate it when the picker is rewritten.

## E. Weather (first real tool)

### 28 · Tool helpers + cache — ☐ *BE*
- **Builds:** `tools/common.py`:
  - the `ToolResult` (`ok`, `data`, `error`);
  - `is_mock()` and `load_mock(name)` from `tools/mocks/`;
  - the `api_cache` table + `cache_get` / `cache_set` with TTL.
  Also a `status()` helper in the pipeline that emits start/end/error around a tool call.
- **Files:** `backend/app/tools/common.py`, `tools/mocks/`, `db/tables.py`,
  `agent/pipeline.py`, `tests/test_tools_common.py`
- **Tests:** cache hit and expiry; mock loading; status emits start+end, or start+error on
  failure.
- **Done when:** tests green.
- **Notes:** —

### 29 · Weather tool (Open-Meteo) — ☐ *BE*
- **Builds:** `weather.py`:
  - `geocode_city(name)` via Open-Meteo geocoding;
  - `get_weather(lat, lng, start, end)`: the forecast API within 16 days, else the climate
    average (the same dates over the last 3 years from the archive API);
  - °F, and WMO code → condition + icon;
  - a per-day list with `source`.
  It has mock JSON.
- **Files:** `backend/app/tools/weather.py`, `tools/mocks/weather_*.json`,
  `tests/test_weather.py`
- **Tests:** forecast vs climate chosen by date; WMO mapping; mock mode; an HTTP error
  (httpx `MockTransport`) → `ok: false`; one live test.
- **Done when:** tests green.
- **Notes:** —

### 30 · Weather in the plan and in chat — ☐ *BE*
- **Builds:**
  - the pipeline gather step geocodes cities (fills `cities[].lat/lng`) and fetches weather;
  - postprocess fills `days[].weather` and a code-built `weather_summary`;
  - status lines show "Checking weather for San Jose · Mar 5–7";
  - when the profile has a city + dates, the chat context includes the forecast, so "what's the
    weather?" is answered from real data.
- **Files:** `backend/app/agent/pipeline.py`, `agent/postprocess.py`, `agent/context.py`, tests
- **Tests:** weather comes from tool data, not the draft; a tool failure → weather `null`, the
  plan is still saved, and an assumption is added; the context contains the forecast.
- **Done when:** tests green.
- **Notes:** —

### 31 · Weather chips + status lines in the UI — ☐ *FE*
- **Builds:** a day weather chip ("☀ 66° / 48°", "avg" when climate), a header summary chip
  (hidden when null), chat status lines from `status` events (spinner → ✓, ✕ on error), and the
  "Weather data by Open-Meteo.com" credit.
- **Files:** `frontend/src/components/PlanView.tsx`, `components/ChatPanel.tsx`, store, tests
- **Tests:** the chip renders/hides; "avg" label; status line state changes.
- **Done when:** tests green.
- **Notes:** —

## F. Places + Map view

### 32 · [HUMAN] Geoapify key — ☐
- **Builds:** create a free Geoapify account (no card), make an API key, put `GEOAPIFY_KEY` in
  `backend/.env`, and confirm the free-plan limits in the README.
- **Done when:** a places request with the key returns results.
- **Notes:** —

### 33 · Places tool (Geoapify + Nominatim) — ☐ *BE*
- **Builds:** `places.py`:
  - `geocode(query)` (Geoapify, falling back to Nominatim with a descriptive User-Agent);
  - `search(lat, lng, interest, limit=8)`, which maps interests → Geoapify categories (a table
    in code) and normalizes results to `{id, name, address, lat, lng, category, rating}`.
  It has mock JSON.
- **Files:** `backend/app/tools/places.py`, `tools/mocks/places_*.json`,
  `tests/test_places.py`
- **Tests:** interest → category mapping (and the default); normalization; no key → Nominatim
  path; error → `ok: false`.
- **Done when:** tests green.
- **Notes:** —

### 34 · Real places in the plan — ☐ *BE*
- **Builds:**
  - gather searches places per interest;
  - the compose prompt lists results with short refs (`p1`, `p2`…);
  - postprocess copies `place_id`, address and coordinates from the referenced result;
  - stops without a ref (home, airports) are geocoded by name + city;
  - an unknown ref is ignored (the stop stays without coordinates);
  - tag matching now uses `place_id`;
  - `source` is "Geoapify".
- **Files:** `backend/app/agent/pipeline.py`, `agent/postprocess.py`,
  `agent/prompts/compose.md`, tests
- **Tests:** coordinates come from tools even if the draft has numbers; airport geocoded; a bad
  ref is handled; v2 tag stability by `place_id`.
- **Done when:** tests green.
- **Notes:** —

### 35 · Travel estimates between stops — ☐ *BE*
- **Builds:** postprocess sets `transit_from_previous` from the haversine distance and a simple
  speed per mode (walk 3 mph, transit 12 mph, drive/rideshare 25 mph), with
  `estimated: true`, when both stops have coordinates.
- **Files:** `backend/app/agent/postprocess.py`, `tests/test_travel.py`
- **Tests:** a known distance; a missing coordinate → `null`; the first item of a day → `null`.
- **Done when:** tests green.
- **Notes:** —

### 36 · Map tab from real data — ☐ *FE*
- **Builds:**
  - `lib/map.ts` (`stopsForDay`, `dayColorForTag`, `polylineForDay`, `offMapStops`, `bounds`);
  - MapView from the store: day chips, TagBadge pins coloured by day, dashed polylines, the
    Stops list, "Off map: …", tag ↔ pin focus, OSM attribution;
  - the Map tab is enabled when any stop has coordinates.
- **Files:** `frontend/src/lib/map.ts`, `lib/map.test.ts`, `components/MapView.tsx`, `App.tsx`
- **Tests:** helper functions; MapView (mocked leaflet) lists the right stops per day; the tab
  enable rule.
- **Done when:** a generated plan shows on the map.
- **Notes:** —

## G. Hotels (+ flights note)

### 37 · [HUMAN] SerpApi key — ☐
- **Builds:** create a free SerpApi account, put `SERPAPI_KEY` in `backend/.env`, and note the
  monthly quota in the README.
- **Done when:** one Google Hotels search returns prices.
- **Notes:** —

### 38 · Hotels tool (SerpApi Google Hotels) — ☐ *BE*
- **Builds:** `hotels.search(city, check_in, check_out, adults, budget_level)`:
  - the `google_hotels` engine sorted by lowest price;
  - normalized to name, coordinates, rating, per night, total, link;
  - `price_as_of` = now, cached 6 h.
  No key or quota left → places lodging results with no price (`price_source: "none"`). It has
  mock JSON.
- **Files:** `backend/app/tools/hotels.py`, `tools/mocks/hotels_*.json`, `tests/test_hotels.py`
- **Tests:** normalization; the cache prevents a second call; the fallback path; error →
  `ok: false`.
- **Done when:** tests green.
- **Notes:** —

### 39 · Hotel in the plan — ☐ *BE*
- **Builds:**
  - gather searches hotels once per city for the whole stay;
  - compose picks one by ref;
  - postprocess builds the `lodging` entry (prices + `price_as_of` from the tool, never from
    the draft);
  - the hotel is a lettered stop, and its item shows nights + per-night cost with source
    "SerpApi Google Hotels · as of …".
- **Files:** `backend/app/agent/pipeline.py`, `agent/postprocess.py`, tests
- **Tests:** tool price wins over a draft price; no-price fallback → `null` + "check link".
- **Done when:** tests green.
- **Notes:** —

### 40 · Deep links + flights as links — ☐ *BE*
- **Builds:**
  - `links.py` (contracts §6);
  - postprocess sets `map_url` per stop and lodging links;
  - flight items get `est_cost: null` ("check link") plus a Google Flights link kept for
    bookings.
  *Real flight fares come later (step 49).*
- **Files:** `backend/app/tools/links.py`, `agent/postprocess.py`, `tests/test_links.py`
- **Tests:** URL encoding; date formats; links attached to the right stops.
- **Done when:** tests green.
- **Notes:** —

### 41 · Hotel + flight display — ☐ *FE*
- **Builds:** entries show "check link" when `est_cost` is null; the hotel shows per night +
  nights + "as of {time}"; "Why this?" shows the source; map links open in a new tab.
- **Files:** `frontend/src/components/PlanView.tsx`, `lib/format.ts`, tests
- **Tests:** null cost → "check link"; the as-of format.
- **Done when:** tests green.
- **Notes:** —

## H. Book view

### 42 · Bookings in the plan + PATCH — ☐ *BE*
- **Builds:**
  - postprocess `build_bookings`:
    - flight = origin airport tag → destination airport tag, round trip, Google Flights link;
    - one lodging booking per hotel (total, as of, links);
    - one per `booking_required` activity (tickets link);
  - items get `booking_id`;
  - `status` is carried over from the previous version by id;
  - `PATCH /sessions/{id}/bookings/{booking_id}` updates the latest itinerary in place.
- **Files:** `backend/app/agent/postprocess.py`, `api/bookings.py`, `db/repo.py`,
  `tests/test_bookings.py`
- **Tests:** the expected bookings for the fixture; carry-over across v1 → v2; PATCH persists;
  unknown id → 404.
- **Done when:** tests green.
- **Notes:** —

### 43 · Book tab from real data — ☐ *FE*
- **Builds:**
  - BookView from the store with the "N of M booked" progress bar;
  - Book → the approval dialog → opens the link (`noopener noreferrer`);
  - "Mark booked" → `api.patchBooking`, optimistic with a revert on error;
  - the Book tab is enabled when bookings exist.
- **Files:** `frontend/src/components/BookView.tsx`, `api/http.ts`, store, tests
- **Tests:** progress count; the dialog flow; optimistic update + revert.
- **Done when:** tests green.
- **Notes:** —

## I. History

### 44 · History backend + auto-title — ☐ *BE*
- **Builds:**
  - `GET /sessions` (newest first), `PATCH /sessions/{id}` (title → `title_is_custom`),
    `DELETE /sessions/{id}` (cascade);
  - an auto-title in `turn.py` once the profile has a city + dates and the title isn't custom
    ("San Jose · Mar 5–7", built by code) → a `title` event.
- **Files:** `backend/app/api/sessions.py`, `db/repo.py`, `agent/turn.py`,
  `tests/test_history_api.py`
- **Tests:** list order; rename sets custom and stops auto-titling; delete removes messages and
  itineraries; the title event fires once.
- **Done when:** tests green.
- **Notes:** —

### 45 · History rail wired up — ☐ *FE*
- **Builds:**
  - `useHistoryStore`;
  - HistoryRail: list (title, relative date), New trip, open (aborts any stream first), inline
    rename (Enter/Esc, 1–80 chars), delete with confirm (switches to the next trip, or a new
    one);
  - on start, opens the most recent trip when no id is stored;
  - `title` events update the list.
- **Files:** `frontend/src/store/useHistoryStore.ts`, `components/HistoryRail.tsx`,
  `api/http.ts`, tests
- **Tests:** rename/delete flows; deleting the active trip switches; title update.
- **Done when:** history persists across a backend restart.
- **Notes:** —

## J. Polish & demo

### 46 · Error + loading pass — ☐ *FE+BE*
- **Builds:**
  - every API call has a loading and an error state;
  - a "Backend not reachable" banner;
  - Retry resends the last message;
  - a failed generation shows a toast and keeps the old plan;
  - aria labels on icon buttons and visible focus.
- **Files:** components, store, `backend/app/agent/turn.py` (friendly error texts), tests
- **Tests:** unreachable banner; Retry; the old plan is kept after a failure.
- **Done when:** tests green; a manual run with the backend stopped behaves sensibly.
- **Notes:** Retry (step 14) resends the text, so the backend saves the user message twice; fix it with a retry flag or a server-side dedupe (needs a contract line or a decision row). Also decide two edge cases. If a turn errors mid-stream, the browser keeps the partial reply but the server doesn't save it, so a reload drops it. If Stop lands right after `message_start`, the server saves a reply that is only " *(stopped)*", and it appears after a reload.

### 47 · Demo readiness — ☐ *HUMAN+agent*
- **Builds:**
  - manual scenario scripts in `backend/tests/scenarios/` (solo weekend, 3 friends 3 days, 2
    cities, vibe-only "beach weekend", and the edit sequence "replace [F]", "move [E] to
    day 2", "cheaper hotel");
  - a README demo walkthrough;
  - a clean-clone setup check.
- **Done when:** a teammate runs the demo from a clean clone by following the README.
- **Notes:** —

## Stretch (after the MVP works end to end)

### 48 · "Book for me" assistance — ☐
- **Builds:** on a booking card, the agent writes a ready-to-copy booking summary (names, dates,
  travelers, room/flight choice) and opens the prefilled provider link. Approval is always
  required. No payments.
- **Notes:** —

### 49 · Real flight fares — ☐
- **Builds:** `tools/flights.py` via SerpApi Google Flights (same key, cached). Flight items and
  bookings get a fare estimate + "as of".
- **Notes:** —

**Later (not planned yet):** performance (caching everything, real routing, parallel tool
calls), diff-aware edits, drag-and-drop editing, editable profile chips, export (PDF/.ics),
mobile layout, an Anthropic adapter, MCP wrappers for tools, auth + deployment.
