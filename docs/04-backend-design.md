# 04 — Backend Design

Owned by backend-researcher and backend-dev (see [AGENTS.md](../AGENTS.md)). Each section is
tagged:
- **[DECIDED]** — build it as written.
- **[PROPOSED → RQ-n]** — current best guess; the research question in
  [research/README.md](research/README.md) must confirm or replace it before the blocking
  task in [05-implementation-plan.md](05-implementation-plan.md) starts. When resolved, the
  researcher rewrites the section, flips the tag to [DECIDED], and links the research note.

API shapes, DB tables and the Itinerary schema live in [03-contracts.md](03-contracts.md);
this doc describes how the backend produces them.

**Stages.** The backend is built in stages ([05-implementation-plan.md](05-implementation-plan.md)).
Subsections numbered **x.0 "Stage 1 baseline"** (§3.0, §4.0, §5.0, §7.0) describe the minimal
version built first; the rest of each section is the full design that later stages grow into.
When a later stage changes a baseline, keep the baseline text short and mark what replaced it.

---

## 1. Overview [DECIDED]

```
┌──────────────────────── Browser (React + Vite) ────────────────────────┐
│ History sidebar │  Plan / Map / Checklist tabs   │   Chat panel        │
└────────┬────────────────────────┬──────────────────────────┬───────────┘
         │ REST (JSON)            │ Google Maps JS API        │ POST + SSE
         ▼                        ▼ (browser key)             ▼
┌──────────────────────────── FastAPI backend ───────────────────────────┐
│  api/sessions.py   api/chat.py   api/checklist.py                       │
│        │                 │                                              │
│   db/ (SQLModel)   agent/orchestrator.py ──▶ llm/ provider adapter      │
│   SQLite file            │ tool calls          (anthropic | fake | …)   │
│                          ▼                                              │
│     tools/weather.py  tools/maps.py  tools/hotels.py  tools/links.py    │
│     agent/tags.py      agent/postprocess.py                             │
└──────────┬──────────────────┬──────────────────┬────────────────────────┘
           ▼                  ▼                  ▼
      Open-Meteo        Google Places /      SerpApi Google Hotels
                        Geocoding / Routes   (fallback: Places lodging)
```

**One orchestrator + tool "sub-agents".** The "weather agent", "maps agent" and "hotels
agent" are deterministic Python tools called by a single LLM orchestrator via tool use — not
separate LLM agents or MCP servers. Each is an API lookup, so an LLM per domain would add
latency, cost and failure modes. The tool boundary is clean, so any tool can later become an
MCP server or an LLM sub-agent without changing the API.

## 2. Modules [DECIDED]

- `app/main.py` — app factory, CORS (`http://localhost:5173`), routers under `/api`, create tables on startup.
- `app/core/config.py` — `pydantic-settings` `Settings` from `.env` (variables in [setup-guide.md](setup-guide.md)).
- `app/core/text.py` — `normalize_name` (place/hotel matching key, §5.0), shared by `schemas/` and
  `agent/` so schemas never import from the agent layer.
- `app/db/` — engine, tables (`Session`, `Message`, `Itinerary`, `ApiCache`), plain repository functions, `seed.py` (loads the same demo sessions as the frontend fixtures).
  - `tables.py`: classes `SessionRow`, `MessageRow`, `ItineraryRow` (tables `session`, `message`,
    `itinerary`; the `Row` suffix avoids clashing with SQLModel's `Session` and the DTOs).
    `itinerary` is unique on `(session_id, version)`. JSON columns aren't change-tracked:
    assign a new value instead of mutating in place.
  - `engine.py`: `make_engine(url)` (SQLite: `check_same_thread=False` and
    `PRAGMA foreign_keys=ON` on every connection, needed for cascade deletes), cached
    `get_engine()`, `init_db()` (run by the FastAPI lifespan), `get_session()` dependency.
  - `repositories.py`: plain functions taking an open `Session` and committing their own
    writes — `create_session(db, llm_provider, greeting)` (session + greeting message),
    `get_session_row`, `list_messages` (by `created_at`, ties by SQLite `rowid` = insertion
    order), `get_latest_itinerary` (highest `version`), `get_session_detail(db, id,
    current_provider)` → `SessionDetail | None` (`chat_enabled` = stored `llm_provider` equals
    the configured one). With no `relationship()` between tables, flush a parent row before
    adding children in the same transaction.
    `add_messages(db, session_id, messages)` saves display messages and bumps the session's
    `updated_at` in one commit. `add_itinerary(db, session_id, itinerary, message)` (S1.10) saves
    an itinerary version (row `id` = `itinerary.id`) with the assistant message announcing it,
    sets `status = planned` and bumps `updated_at`, in one commit.
- `app/api/sessions.py` (Stage 1): `POST /sessions` → `200` + `SessionDetail` whose only
  message is the fixed greeting (`app/agent/fixed_messages.py: GREETING`, no LLM call);
  `GET /sessions/{id}` → `SessionDetail` or `404 {"detail": "Session not found"}`. Until
  profile extraction (Stage 3) `trip_profile` is stored as `{}` and returned with
  `missing_required: []`.
- `app/api/chat.py` (Stage 1, S1.8): `POST /sessions/{id}/messages` with body
  `MessageCreate {content}` (trimmed, 1–4000 chars) → `404` if the session doesn't exist, else
  `EventSourceResponse(orchestrator.run_chat_turn(engine, settings, id, content))`. The route
  takes `get_engine` as a dependency (tests override it with a tmp DB) and holds no DB session
  while streaming. `main.py` turns request validation errors into `400 {"detail": "field: msg"}`
  (03 §3) instead of FastAPI's 422.
  `POST /sessions/{id}/generate` (S1.10, same file) → same `404`, else
  `EventSourceResponse(orchestrator.run_generation(engine, settings, id))`; the `{}` body is not
  read (an empty body works too).
- `app/schemas/` — Pydantic models from 03-contracts (`TripProfile`, `Itinerary`, `ItineraryDraft`, DTOs, SSE payloads) incl. validators.
- `app/api/` — thin routes: validate → repo/orchestrator → respond/stream.
- `app/llm/` — provider layer (§3).
- `app/agent/orchestrator.py` — tool loop and phases; exposes
  `run_chat_turn(session_id, text) -> AsyncIterator[SseEvent]` and
  `run_generation(session_id, change_request) -> AsyncIterator[SseEvent]` (Stage 1:
  `run_chat_turn(engine, settings, session_id, text)` and `run_generation(engine, settings,
  session_id)`, no `change_request`).
- `app/agent/tags.py` — letter-tag assignment (03 §2.2 tag rules).
- `app/agent/postprocess.py` — `ItineraryDraft` → `Itinerary`.
- `app/agent/prompts/` — system prompt `.md` files (byte-stable for prompt caching).
- `app/tools/` — one module per "sub-agent" + mock providers; no LLM knowledge.

## 3. LLM provider layer

### 3.0 Stage 1 baseline — text + JSON, no tools [DECIDED]

```
backend/app/llm/
  base.py                    LLMProvider protocol (below)
  fake_provider.py           default; canned streamed replies + fixture draft; no key
  openai_compat_provider.py  TAMU AI (first real LLM) or any OpenAI-compatible endpoint
  anthropic_provider.py      optional backup (Claude via the official SDK)
  factory.py                 get_provider(settings) by LLM_PROVIDER
  smoke.py                   `python -m app.llm.smoke` — manual live check, not run by pytest
```

```python
class LLMProvider(Protocol):
    name: str                                     # "fake" | "openai_compat" | "anthropic"
    def stream_text(self, *, system: str, messages: list[ChatMessage]) -> AsyncIterator[str]
    async def generate_json(self, *, system: str, messages: list[ChatMessage],
                            schema: type[T]) -> T  # T: pydantic BaseModel

ChatMessage = {"role": "user" | "assistant", "content": str}
```
- Messages are built from the `message` table (display messages). `session.agent_transcript`
  is stored as `[]` and `session.llm_provider` is set, until Stage 3 adds tools.
- **openai_compat (TAMU AI):** official `openai` SDK, `AsyncOpenAI(base_url=LLM_BASE_URL,
  api_key=LLM_API_KEY)`. **Always `chat.completions.create(stream=True)`** — TAMU AI returns no
  usable non-streaming response (verified 2026-11-02, setup-guide §6.2). Stream handling must
  tolerate its quirks: skip chunks with no `choices` or empty `delta.content`, ignore
  `reasoning_content` / `thinking_blocks`, stop at the first `[DONE]` (the SDK does this).
- **`generate_json` (openai_compat):** don't rely on `response_format` (unverified on TAMU AI).
  Put the Pydantic model's JSON schema in the system prompt ("reply with only a JSON object
  matching this schema"), stream and collect the full text, extract the JSON object (a fenced
  block only if it parses as an object, else the first `{` that decodes to a complete object),
  validate with Pydantic; on failure retry once with the validation errors
  appended; then raise.
  TAMU AI facts (base URL, model IDs, JSON-schema support) are confirmed by a human (05 H1.2).
  Base URL `https://chat-api.tamu.ai/openai` (verified); default model `protected.Claude-Opus-5`
  (also `protected.gpt-5.5`). `chat.tamu.ai` itself is behind a NetID login and can't be called
  from the backend. JSON-schema support is still to be confirmed — keep the prompt-JSON fallback.
  Details (S1.6): `OpenAICompatProvider(base_url, api_key, model, timeout=60, max_retries=2)`;
  the SDK retries connection errors/429/5xx itself. Only non-empty `delta.content` of choice 0
  is yielded; a stream with no text at all raises `LLMError("empty reply", retryable=True)`, and
  a `data:` line that isn't JSON raises `LLMError("LLM stream was malformed.", retryable=True)`.
  In `generate_json` a whitespace-only reply raises `LLMError("LLM returned an empty reply.",
  retryable=True)` at once (S1.10): it is not sent back as a blank `assistant` turn, which some
  endpoints reject with HTTP 400 (that would surface as the misleading "check LLM_BASE_URL"
  error). No `max_tokens` is sent, so the endpoint's own default output limit applies.
  The retry sends the bad reply back as an `assistant` message plus a `user` message listing the
  validation errors (`field: msg`). Prompt-based JSON verified live on `protected.Claude-Opus-5`
  (2026-11-02, `python -m app.llm.smoke`). The factory raises `LLMError(retryable=False)` naming
  any missing `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`.
- **anthropic:** official `anthropic` SDK per §3.1 (load the `claude-api` skill first); never
  route Claude through an OpenAI-compatible shim.
- **fake:** streams a fixed reply in ~30-char chunks; `generate_json` returns an
  `ItineraryDraft` loaded from a fixture so the whole flow (tags, validation, UI) runs with no key.
  Details (S1.5): the reply is deterministic — it quotes the last user message and asks the next
  of a few fixed follow-ups (by user-message count), ending with "click **Generate plan**";
  `FakeProvider(chunk_size=30, delay=0.03)` sleeps `delay` s between chunks (tests pass `0`).
  `generate_json` is generic: it loads `app/llm/fixtures/<snake_case schema name>.json`
  (`ItineraryDraft` → `itinerary_draft.json`, added in S1.9; `fixtures_dir` is overridable for
  tests) and validates it with the schema.
- **Errors:** adapters raise only `LLMError(message, retryable=True)` from `base.py` — including
  invalid model output after the retry (the Pydantic `ValidationError` is chained as `__cause__`)
  and misconfiguration (`retryable=False`: missing fake fixture, provider not built yet, missing
  `LLM_*` settings, HTTP 401/403 "check LLM_API_KEY", HTTP 400/404/422 "check LLM_BASE_URL and
  LLM_MODEL"). HTTP 429/5xx, timeouts, connection errors and invalid real-model output are
  `retryable=True`. Routes
  map it to SSE `error` `{message, retryable}` with a friendly message (§9), never `str(err)`.
- **`factory.py`:** `get_provider(settings)` plus a tiny FastAPI dependency `get_llm()` (uses
  `get_settings`, so tests pick the provider by overriding `get_settings`).

### Full design — tool calling (Stage 3) [PROPOSED → RQ-1, RQ-2]

Stage 3 extends §3.0 with tool calling. The team may switch LLM providers (TAMU AI, Claude,
others), so **no provider SDK types leak outside the adapter.** Same files as §3.0; `base.py`
gains normalized event / `ToolSpec` types and each adapter gains the methods below.

Proposed interface (spec, not final code):
```python
class LLMProvider(Protocol):
    name: str                                  # "anthropic" | "fake" | "openai_compat"
    async def stream_turn(self, *, system: str, transcript: list, tools: list[ToolSpec],
                          effort: Literal["low", "medium", "high"]) -> AsyncIterator[LLMEvent]
    async def structured(self, *, system: str, transcript: list,
                         schema: type[BaseModel], effort: str) -> BaseModel
    def append_user(self, transcript: list, text: str) -> None
    def append_tool_results(self, transcript: list, results: list[ToolResult]) -> None

LLMEvent = TextDelta(text) | ToolCall(id, name, input: dict) | TurnEnd(stop_reason, has_tool_calls)
```
- `ToolSpec` = name, description, Pydantic input model; each adapter converts it to its own format.
- The **orchestrator owns the tool loop** (`stream_turn` → run tool calls concurrently →
  `append_tool_results` → repeat until no tool calls; max 25 iterations), emitting `status`
  SSE events around each tool.
- `transcript` is provider-native and append-only; stored in `session.agent_transcript` with
  `session.llm_provider`. Sessions from another provider are read-only for chat.
- RQ-1 decides whether to extend the §3.0 hand-rolled adapters or adopt a library (e.g.
  PydanticAI, LiteLLM) that already normalizes providers, streaming, tools and structured
  output. Whatever it picks must keep `stream_text` / `generate_json` callers working or
  migrate them in the same change.

**Config:** `LLM_PROVIDER` (`fake` default | `openai_compat` | `anthropic`), `LLM_MODEL`
(e.g. `protected.Claude-Opus-5` on TAMU AI, or `claude-opus-5-5` direct), `LLM_FAST_MODEL` (titles, Stage 4),
`LLM_API_KEY`, `LLM_BASE_URL` (required for `openai_compat`).

### 3.1 Anthropic adapter settings
| Setting | Value |
|---|---|
| SDK | official `anthropic` Python SDK, `AsyncAnthropic` (load the `claude-api` skill first) |
| Model | `claude-opus-5-5`; `claude-sonnet-5-5` as cheaper drop-in |
| Thinking | adaptive (cannot be disabled on Opus 5.5 — control with effort) |
| Effort (`output_config.effort`) | chat `low`; generation/edit `high`; always set explicitly |
| Streaming | `client.messages.stream(...)`; forward text deltas |
| Structured output | `client.messages.parse(...)` / `output_config.format` with the Pydantic model |
| Refusals | check `stop_reason`; enable server-side `fallbacks: "default"` per the skill |
| Caching | static system prompt + tools first with a cache breakpoint; dynamic context in messages |
| Constraints | no forced `tool_choice` (use `auto` + `strict: true`), no assistant prefill, no `temperature`/`top_p`, append-only transcript (thinking blocks passed back unchanged) |

### 3.2 OpenAI-compatible adapter — tools (Stage 3) [PROPOSED → RQ-2]
The Stage 1 adapter (§3.0) gains tools → functions and structured output via `response_format`
JSON schema (or a tool-call fallback). Requires the endpoint to support tool calling — to be
confirmed against TAMU AI (05 H1.2) before S3.1.

### 3.3 Fake adapter (Stage 3)
Extends the §3.0 fake: asks 2 intake questions, calls `update_trip_profile`, and on generate
composes an itinerary from fixture data (still runs real tagging and validation). Lets
teammates without keys run the full stack.

## 4. Orchestrator phases

### 4.0 Stage 1 baseline — chat and generate without tools [DECIDED]
- **Chat** (`run_chat_turn`): `message_start` → build the provider (`get_provider`) →
  `stream_text(system=prompts/system.md, messages=history + new user message)` → `token`
  events → save the user **and** assistant messages together (`add_messages`) → `done`.
  Details (S1.8): history is `list_messages` minus the code-written greeting(s) before the first
  user message, so every provider sees a conversation that starts with the user. Any `LLMError`
  (including "provider not configured" from the factory) or unexpected exception → log it and
  send `error` instead of `done`, with a fixed friendly message (never `str(err)`):
  `retryable=true` → "couldn't get a reply… try again"; `retryable=false` → "the AI model isn't
  set up correctly… check backend/.env". A reply with no text (empty or whitespace only) is a
  retryable `LLMError` too. A failed turn saves nothing, so Retry re-sends the same text. The provider is built per turn (not cached), so an SDK client is never reused across
  event loops.
- **Generate** (`run_generation`): `status` "Drafting your itinerary…" →
  `generate_json(system=prompts/generate.md, messages=history, schema=ItineraryDraft)` →
  §5.0 postprocess → validate → persist next `itinerary.version`, `session.status = planned` →
  `itinerary` event → short fixed assistant message (`PLAN_READY`, text in Details below)
  streamed as `token` and saved → `done`. Validation failure → one retry with the
  errors → `error`, previous version kept.
  Details (S1.10):
  - **Retry = the provider's one built-in retry, nothing more.** `ItineraryDraft`'s validator
    checks everything the LLM can get wrong (§5.0), so `generate_json`'s retry (bad reply + its
    validation errors sent back once) is the "retry once"; the orchestrator adds no retry of its
    own. At most 2 LLM calls per click. A truncated reply fails draft validation the same way
    (`extra="forbid"`, required top-level fields), so it takes the retry → `error` path. If
    postprocess still raises, that is a code bug: log it and send `error` (no extra LLM call).
  - Messages: history as in chat (greeting dropped) plus a final code-written `user` turn,
    `generation_request(today)` = "Today is Monday, 2026-11-02. Draft the itinerary now from our
    conversation above." It carries today's date (for "next weekend") while `generate.md` stays
    byte-stable, and makes the conversation end with the user, as every provider requires.
  - Events: `message_start` → (provider built; misconfiguration → `error`, as in chat) →
    `status {label: "Drafting your itinerary…", tool: null, state: "start"}` (no `end`: the
    `itinerary` or `error` event ends the phase) → `generate_json` → postprocess with version =
    latest + 1 (Stage 1 regenerates from scratch; no tag carry-over yet) → `add_itinerary` saves
    the version, the assistant message (`id` = `message_start.message_id`, `content` =
    `fixed_messages.PLAN_READY`, `itinerary_version` set) and `status = planned` together →
    `itinerary` → one `token` with the same fixed text → `done`.
  - The fixed text is "Here's a draft itinerary. Tell me what you'd like to change, then click
    **Regenerate** to update it." (Stage 1 chat doesn't edit the plan; Stage 3 replaces
    it with an LLM change summary.) No user message is saved: the button isn't a chat message.
  - Any `LLMError` or exception → log it, send `error` with the same fixed friendly texts as
    chat (never `str(err)`); nothing is saved, the previous version and status stay.
- No trip-profile extraction yet (`trip_profile` stays empty); the user clicks **Generate plan**.
- **`prompts/system.md` v0:** friendly, concise planner for budget travelers aged 15–35;
  scope 2–4 days (max 7) and 1–2 cities; ≤ 2 questions per turn, priority destination →
  dates/length → travelers → origin → interests; never claim to have booked anything; never
  quote prices as facts; once destination and length are known, suggest clicking
  **Generate plan**; don't paste a full itinerary in chat.
- **`prompts/generate.md` v0:** compose an `ItineraryDraft` from the conversation; dates
  missing → assume the upcoming weekend and say so in `assumptions`; real, well-known places
  only, by name (and address if confident); no hotel prices or coordinates; cheap options, one hotel
  per city, ≈ 3–4 main stops per day, sensible meal times. Details (S1.10): other gaps get
  stated defaults (3 days, 1 traveler, budget; no destination → a popular budget-friendly US
  city), all listed in `assumptions`; the prompt spells out the day rules and the lodging date
  rules the draft validator enforces (check-in ≥ start, check-out ≤ end with the last day as
  departure, check-out > check-in, no overlaps, distinct names) and how to use `lodging_ref`, so
  the single retry is rarely spent on them. `est_cost` / `cost_estimate` are rough per-person
  LLM estimates or `null` (the Stage 1 header shows the range, S1.15); hotel prices come only
  from the hotel tool (Stage 3). The JSON schema itself is added by the provider, not the prompt.

The phases below (§4.1–4.5) are the full design for Stage 3+ [DECIDED].

### 4.1 Intake (status = `intake`)
- Fill required `TripProfile` slots (01 §4 F2) in ~3–5 turns; ≤ 2 questions per turn;
  priority destination → dates → travelers → origin → interests; budget defaults to `budget`.
- On new facts, call `update_trip_profile` with changed fields only (server merges,
  recomputes `missing_required`, emits `profile`).
- Enforce scope politely: > 2 cities → pick 2; > 7 days → offer the first 7.
- Vibe only → suggest 3 concrete cities.
- All required filled → one-line summary + offer to generate. Any "generate" phrasing → `generate_itinerary`.

### 4.2 Generation (button or `generate_itinerary`)
1. **Research loop** (tools, effort `high`): weather for the full range; geocode cities;
   `search_places` per interest; `search_hotels` once per city **for the whole stay**,
   cheapest first; travel times for clustered stops. Cap ~15 tool calls.
2. **Composition:** one `structured()` call → `ItineraryDraft` (Itinerary minus
   tags/ids/links/version/prices). Places referenced by `place_id` from tool results; generic
   untagged items allowed ("Coffee near your hotel").
3. **Post-processing** (§5), persist new version, status `planned`, emit `itinerary`.

### 4.3 Editing (status = `planned`)
- Each turn includes the current itinerary in compact form, e.g.
  `Day 1 (Sat Mar 6): 11:00 [A] Franklin Barbecue · 14:00 [B] Zilker Park …  Hotel [H1] Example Inn $89/nt`.
- Prompt explains tags; ambiguous/unknown references → ask.
- Plan-changing request → `generate_itinerary(change_request=…)`; composition gets the previous
  itinerary and the instruction **change only what was asked; keep everything else identical**.
  Tag stability is guaranteed by code (same `place_id` → same tag).
- Pure questions ("how far is B from C?") are answered without regenerating.
- After a new version: 1–3 line change summary using tags; `itinerary_version` set on the message.

### 4.4 Auto-title
After the first user message (while `title_is_custom = false`): one `LLM_FAST_MODEL` call →
≤ 40 chars ("Austin · Mar 6–8") → `title` event. Re-title once when city/dates first become known.

### 4.5 System prompt outline (`app/agent/prompts/system.md`)
1. Role: friendly, efficient planner for young budget-conscious travelers; concise; honest.
2. Today's date, profile and compact itinerary arrive as per-turn context (keeps the prompt cacheable).
3. Intake rules and MVP scope limits (§4.1).
4. Tool rules: never invent hotels, prices, hours or weather; prefer parallel calls; tolerate tool errors.
5. Planning heuristics: cheapest reasonable options; one hotel per city for the stay; cluster
   stops per day; balanced ≈ 3–4 main stops/day; light arrival/departure days; sensible meal
   times; favor free/cheap activities; indoor alternatives on rainy days; nightlife only if interested.
6. Tags and editing rules (§4.3).
7. Chat style: short paragraphs, light markdown; never paste the whole itinerary in chat.
8. Never claim to have booked anything.

## 5. Tags and post-processing [DECIDED]

### 5.0 Stage 1 baseline — `ItineraryDraft`, tags v1, postprocess v0
`ItineraryDraft` (what the LLM fills; Pydantic in `app/schemas/itinerary_draft.py`):
title, summary, start_date, end_date, travelers, cities[] `{name, region, country}`,
cost_estimate (per person, nullable), assumptions[], lodging[] (0–2) `{name, city, check_in,
check_out}`, days[] `{day_number, date, title, city, items[]}`; each item
`{kind, title, description, start_time, end_time, place: {name, category, address?} | null,
lodging_ref: "<lodging name>" | null, est_cost?, booking_required, tips?}`.
No tags, IDs, links, coordinates, prices or weather (extra keys on nested objects are ignored).
Details (S1.9):
- Every top-level field is required with no default (`cost_estimate` must be present, may be
  `null`) and `extra="forbid"`, so an inner object that `extract_json` pulls out of a truncated
  reply fails validation. Nested optional fields (`place`, `lodging_ref`, `est_cost`, `tips`,
  `address`) default to `null`, `booking_required` to `false`.
- `nights` is not asked of the LLM; code computes it from `check_out − check_in`.
- The draft's own validator checks everything the LLM can get wrong, so `generate_json`'s one
  retry covers it and postprocess can assume a consistent draft: day count/dates/`day_number`
  (the same `day_problems` helper `Itinerary` uses), `check_out > check_in`, hotel stays within
  the trip (`check_in ≥ start_date`, `check_out ≤ end_date`: the last day is the departure day
  with no hotel night, matching `days[].lodging_tag` below), hotel stays not overlapping
  (back-to-back is fine), distinct hotel names, and every `lodging_ref` matching a hotel name
  (normalized, as for tags).
- The fake provider's fixture `app/llm/fixtures/itinerary_draft.json` is the draft of
  `tests/fixtures/itinerary_austin.json`; postprocess turns one into the other exactly.

`tags.py` v1 + `postprocess.py` v0 (`draft_to_itinerary(draft, *, version=1, itinerary_id=None,
created_at=None) -> Itinerary`, raises `ValidationError`):
1. Tags: items within a day are sorted by `start_time` (stable); walk days/items in order; each
   new place (matched by `core/text.normalize_name`: casefold, apostrophes `'`/`’` dropped, other
   punctuation turned into a space, whitespace collapsed)
   gets the next letter A…Z, AA…; lodging in check-in order gets H1/H2. Items with a
   `lodging_ref`, or whose `place` name matches a hotel, get the hotel's tag (not a letter).
   A place's first mention sets its name/category; a later mention may fill a missing address.
   `days[].lodging_tag` = the hotel with `check_in ≤ date < check_out` (null on departure day).
2. IDs `d{day}-i{n}` (after sorting), version number, `created_at`; itinerary `id` = new uuid
   unless given.
3. `maps_url` = Google Maps search link from `name + day city` (03 §5 format without
   `query_place_id`).
4. Null: lat/lng, place_id, rating, address if not given; lodging prices null with
   `price_source: "none"`, no `price_as_of`; `days[].weather = null`;
   `transit_from_previous = null`; `weather_summary = null`.
5. Checklist (hotels first, then bookings in day order; no links, `bookable_by_us: false`,
   `status: todo`):
   - per hotel: `id: "chk-lodging-<tag>"` (e.g. `chk-lodging-H1`), category `lodging`, title
     "Book <name> (<tag>)", details "<n> night(s), Mar 6–8." (or "Mar 30–Apr 1"), date = check-in.
   - per `booking_required` item: `id: "chk-booking-<item id>"` (e.g. `chk-booking-d2-i7`),
     category `activities`, title "Book <item title>", date = the day's date; the item's
     `checklist_item_id` points to it. A booking-required item on a hotel links to that hotel's
     `chk-lodging-<tag>` instead of adding a second entry.
6. Validate per 03 §2.2.

Stage 2 adds place lookups (§6.3) between steps 3 and 4. Stage 3 replaces this with the full
list below (cross-version tag stability, links, prices, weather, full checklist).

Full design — `postprocess.py` turns an `ItineraryDraft` into an `Itinerary`:
1. Assign place and lodging tags via `tags.py` (rules in 03 §2.2: first-appearance order,
   stable across versions by `place_id`/name+coords match, retired letters never reused, H1/H2).
2. Assign item/checklist IDs and the version number.
3. Build links via `tools/links.py`.
4. Attach hotel prices + `price_as_of` from the hotel tool result (never from LLM text).
5. Add standard checklist items: flights out/back (if origin known), lodging, booking-required
   activities, ID/documents, weather-based packing list.
6. Validate (03 §2.2); on failure one repair attempt with validation errors, else `error` event
   and keep the previous version.
7. Carry over checklist `status` for item IDs that still exist.

## 6. Tools

All tools: async, Pydantic I/O, 10 s timeout, cached in `api_cache`, return
`{"ok": false, "error": "..."}` instead of raising (passed to the LLM as error tool results),
mock provider when `TOOL_PROVIDER_MODE=mock`. All outputs imperial. Account setup:
[setup-guide.md](setup-guide.md).

### 6.1 `update_trip_profile` (internal) [DECIDED]
Input: partial `TripProfile`. Output: merged profile + `missing_required`.

### 6.2 `get_weather` — Open-Meteo [PROPOSED → RQ-5]
- Input: `lat`, `lng`, `start_date`, `end_date`. No API key.
- Within ~16 days → Forecast API (`api.open-meteo.com/v1/forecast`; daily
  `temperature_2m_max/min`, `precipitation_probability_max`, `weather_code`;
  `temperature_unit=fahrenheit`, `precipitation_unit=inch`, `timezone=auto`).
- Beyond → climate estimate: average of the same calendar dates over the previous 3 years
  from the Archive API (`archive-api.open-meteo.com/v1/archive`); `source: "climate"`.
- WMO weather codes → text in code. Attribution "Weather data by Open-Meteo.com" (CC BY 4.0).

### 6.3 Maps — Google Maps Platform [PROPOSED → RQ-4]
- **Stage 2 (first use):** `find_place(name, city)` → `{name, address, lat, lng, place_id,
  rating}` via Places API (New) Text Search with a minimal field mask; called by
  `postprocess.py` (not by the LLM) for every place, lodging and city, concurrently; cached in
  `api_cache`; a failed lookup leaves the fields `null`. Mock provider for
  `TOOL_PROVIDER_MODE=mock`.
- **Stage 3 additions** (LLM tools):
- `geocode(query)` → `{name, address, lat, lng, place_id}` (Geocoding API).
- `search_places(query, lat, lng, radius_mi, max_results≤8)` → `{name, address, lat, lng,
  place_id, rating, user_rating_count, price_level, primary_type}` via Places API (New)
  Text Search with a minimal field mask (fields determine billing SKU).
- `get_travel_times(origins[], destinations[], mode)` → minutes + miles via Routes API
  `computeRouteMatrix`; fallback haversine ÷ mode speed, flagged `estimated: true`.
- Stay inside monthly free caps; quota limits per setup guide. Fallback provider if needed:
  Nominatim + Overpass/OpenTripMap + haversine.

### 6.4 `search_hotels` — SerpApi Google Hotels → Places fallback [PROPOSED → RQ-3]
- Input: `city` (or lat/lng + area), `check_in`, `check_out`, `adults`, `budget_level`, `max_results≤5`.
- Primary: SerpApi `google_hotels` engine (`check_in_date`, `check_out_date`, `adults`,
  `currency=USD`, `gl=us`, `hl=en`, sort by lowest price). Normalize name, coordinates,
  rating, rate per night, total rate, link; record `price_as_of = now()`.
- One search per city per generation; cached 6 h (small free quota).
- Fallback (no key / quota exhausted): Places Text Search `includedType=lodging`, no prices
  (`price_source: "none"`).
- Pick the cheapest option with rating ≥ ~3.8 and a sensible location; return 2 alternatives.

### 6.5 `generate_itinerary` (control tool) [DECIDED]
Input `{ "change_request": string | null }`. Ends the chat loop and runs §4.2 in the same SSE stream.

### 6.6 `tools/links.py` [PROPOSED → RQ-7]
Pure functions building deep links per 03 §5 (formats to be re-verified). Unit-tested. Not exposed to the LLM.

## 7. Streaming and runtime

### 7.0 Stage 1 baseline [DECIDED]
- SSE via `sse-starlette` `EventSourceResponse`; events per 03 §4 (Stage 1 subset).
- Sync SQLModel: open short `with Session(engine)` blocks inside the stream generator (read
  history; at the end save the user + assistant messages / itinerary together) — never hold a DB session
  across LLM awaits.
- No per-session lock and no server-side cancellation yet; the client may abort its fetch.
  If the generator is cancelled, or the turn ends in `error`, nothing from it is saved.

### 7.1 Full design (Stage 3) [PROPOSED → RQ-6]

- SSE via `sse-starlette` `EventSourceResponse`, events per 03 §4.
- Client abort → detect disconnect, cancel the LLM stream, save partial text with "*(stopped)*".
- One active stream per session (in-process `asyncio.Lock` per session id; second request → 409).
- DB access: sync SQLModel sessions run in FastAPI's threadpool (simplest); revisit if RQ-6
  recommends async SQLite.

## 8. Persistence: SQLite [DECIDED]

- Data is small: session rows, chat text, itinerary JSON (~10–50 KB per version). SQLite
  handles far more, stores JSON in text columns, ships with Python, and is a **local file**
  (`backend/travel.db`) — no cloud.
- One user → no concurrent-writer concerns. Each teammate has their own DB; `seed.py` gives
  everyone the same demo data.
- Upgrade path: Postgres via `DATABASE_URL`; SQLModel code unchanged.

## 9. Errors [DECIDED]

- Tool failures → error tool results; the agent continues and mentions the gap.
- Stream failures → SSE `error` `{message, retryable}`; UI offers Retry.
- A new itinerary version is written only after validation passes.

## 10. Backend testing [DECIDED]

- Tools: unit tests on recorded fixtures (no network); opt-in `pytest -m live` smoke tests.
- Tags / postprocess: first assignment, stability across versions, retired letters, AA after Z, H1/H2.
- API: FastAPI `TestClient` with `LLM_PROVIDER=fake` (CRUD, cascade delete, SSE order, 409).
- Agent quality: persona scripts in `backend/tests/scenarios/`, run manually with a real model.

## 11. Post-MVP notes

- Diff-aware edits: composition returns a patch; UI highlights changes.
- Flights: Duffel (test mode), SerpApi `google_flights`; possibly a true LLM sub-agent.
- MCP: wrap `tools/*` with FastMCP for external clients.
- Events/restaurants: Ticketmaster Discovery API, Places `type=restaurant`.
- Postgres + auth for multi-user deployment.
