# 05 — Agents & Integrations

> Before implementing the Anthropic provider, load the `claude-api` skill. SDK details
> below were current when written (Nov 2026) but the skill is authoritative.
> Account / key setup for every service here: [setup-guide.md](setup-guide.md).

## 1. Agent design: one orchestrator + tool "sub-agents"

**Decision:** for the MVP, the "weather agent", "maps agent" and "hotels agent" are
**deterministic Python tools** called by a single LLM orchestrator via tool use — not
separate LLM agents and not separate MCP servers.

Why: each domain task is an API lookup, not open-ended reasoning; an LLM per domain adds
latency, cost and failure modes. Tools are typed, testable, and cheap. The tool boundary is
clean, so any tool can later become an MCP server or an LLM sub-agent.

```
              ┌──────────── Orchestrator (LLM via provider adapter) ────────────┐
user turn ──▶ │ system prompt + trip profile + current itinerary + transcript    │ ──▶ streamed reply
              │ tools:                                                          │
              │  update_trip_profile            (state)                         │
              │  get_weather                    (weather "agent")               │
              │  geocode, search_places, get_travel_times   (maps "agent")      │
              │  search_hotels                  (hotels "agent")                │
              │  generate_itinerary             (hand-off: create / edit plan)  │
              └─────────────────────────────────────────────────────────────────┘
```

## 2. Swappable LLM provider

The team may switch to a university-provided LLM or a different key, so **no Anthropic
types leak outside the provider adapter.**

```
backend/app/llm/
  base.py           LLMProvider protocol + normalized event/ToolSpec types
  anthropic_provider.py   implemented (default)
  fake_provider.py        scripted responses, no key needed (dev/tests/demo fallback)
  openai_compat_provider.py  stub — implement when the university endpoint is known
  factory.py        get_provider(settings) by LLM_PROVIDER
```

**Interface (spec, not final code):**
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
- `ToolSpec` = name, description, Pydantic input model. Each adapter converts it to its own
  tool format (Anthropic `input_schema` + `strict: true`; OpenAI `function` + `parameters`).
- The **orchestrator owns the tool loop** (call `stream_turn` → run tool calls concurrently →
  `append_tool_results` → repeat until no tool calls, max 25 iterations). This keeps the loop
  provider-neutral and lets us emit `status` events around each tool.
- `transcript` is provider-native and append-only; the adapter appends the assistant message
  itself (raw content blocks) when the turn ends. Stored in `session.agent_transcript` with
  `session.llm_provider`.

**Config (`backend/.env`):**
| var | example | notes |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` \| `fake` \| `openai_compat` | |
| `LLM_MODEL` | `claude-opus-5-5` | main orchestrator model |
| `LLM_FAST_MODEL` | `claude-haiku-5-5` | session titles |
| `LLM_API_KEY` | `sk-ant-…` | provider key (adapter may also read `ANTHROPIC_API_KEY`) |
| `LLM_BASE_URL` | empty / `https://llm.example.edu/v1` | for gateways / OpenAI-compatible endpoints |

### 2.1 Anthropic adapter settings
| Setting | Value |
|---|---|
| SDK | official `anthropic` Python SDK, `AsyncAnthropic` |
| Model | `claude-opus-5-5` default; `claude-sonnet-5-5` is a cheaper drop-in |
| Thinking | adaptive (cannot be disabled on Opus 5.5 — control with effort) |
| Effort (`output_config.effort`) | chat: `low`; generation/edit: `high`. Set explicitly. |
| Streaming | `client.messages.stream(...)`; forward text deltas |
| Structured output | `client.messages.parse(...)` / `output_config.format` with the Pydantic model |
| Refusals | check `stop_reason`; enable server-side `fallbacks: "default"` per the skill |
| Caching | static system prompt + tools first, with a cache breakpoint; dynamic context in messages |
| Constraints | no forced `tool_choice` (`auto` + `strict: true`), no assistant prefill, no `temperature`/`top_p`, append-only transcript (pass thinking blocks back unchanged) |

### 2.2 OpenAI-compatible adapter (later)
Many university gateways expose an OpenAI-compatible Chat Completions API. Implement with
the `openai` SDK using `base_url`: tools → `functions`; structured → `response_format`
JSON schema (or tool-call fallback if unsupported). Only build once the endpoint and its
supported features are confirmed.

### 2.3 Fake adapter
Deterministic scripted flow: asks 2 intake questions, calls `update_trip_profile`, and on
generate composes an itinerary from fixture data (still runs real tag assignment and
validation). Lets teammates without keys run the full app.

## 3. Conversation phases

### 3.1 Intake (status = `intake`)
- Goal: fill required `TripProfile` slots (01 §4 F2) in ~3–5 turns.
- When the user states facts, call `update_trip_profile` with only changed fields (server
  merges, recomputes `missing_required`, emits `profile`).
- Ask ≤ 2 questions per turn, priority: destination → dates → travelers → origin → interests.
  Don't ask about budget unless the user hints; default `budget`.
- Enforce scope politely: > 2 cities → ask which 2; > 7 days → offer the first 7.
- If the user has only a vibe, suggest 3 concrete cities (one line each) and let them pick.
- All required filled → summarize in one line and offer to generate.
- User asks to generate (any phrasing) → call `generate_itinerary`.

### 3.2 Generation (button or `generate_itinerary`)
1. **Research loop** (tools, effort `high`): weather for the full range; geocode cities;
   `search_places` for each interest; `search_hotels` once per city **for the whole stay**,
   sorted by price; travel times for clustered stops. Cap ~15 tool calls.
2. **Composition** — one `structured()` call producing `ItineraryDraft` (Itinerary minus
   tags/ids/links/version). Places are referenced by `place_id` from tool results; the model
   may add generic untagged items ("Coffee near your hotel").
3. **Post-processing in code:** assign tags (03 §2.2 rules), IDs, version; build links via
   `tools/links.py`; attach hotel prices + `price_as_of` from the tool result (never from LLM
   text); add standard checklist items (flights out/back if origin known, lodging, booked
   activities, ID/documents, packing list from weather); validate; one repair attempt on
   failure; persist; set status `planned`; emit `itinerary`.

### 3.3 Editing (status = `planned`)
- Every turn includes the current itinerary in compact form, e.g.
  `Day 1 (Sat Mar 6): 11:00 [A] Franklin Barbecue · 14:00 [B] Zilker Park · …  Hotel [H1] Example Inn $89/nt`.
- System prompt explains tags: the user refers to places by letter; resolve them from this
  listing; if a reference is ambiguous or unknown, ask.
- If the request changes the plan → call `generate_itinerary(change_request=…)`. The
  composition step receives the previous itinerary and the instruction: **change only what
  was asked; keep every other item, time and place identical.** Tag stability is then
  guaranteed by code (same `place_id` → same tag).
- Questions that don't change the plan ("how far is B from C?") are answered without regenerating.
- After a new version, the agent writes a 1–3 line change summary using tags.

### 3.4 Auto-title
After the first user message (while `title_is_custom = false`): one `LLM_FAST_MODEL` call →
≤ 40 chars like "Austin · Mar 6–8" → `title` event. Re-title once when dates/city first become known.

## 4. System prompt outline (`app/agent/prompts/system.md`)

1. Role: friendly, efficient trip planner for young budget-conscious travelers; concise; honest about uncertainty.
2. Today's date and current profile/itinerary come in per-turn context (keeps system prompt cacheable).
3. Intake rules (§3.1) and MVP scope limits.
4. Tool rules: never invent hotels, prices, hours, or weather — use tools or say unknown; prefer parallel calls; tolerate tool errors.
5. Planning heuristics: cheapest reasonable options by default; one hotel per city for the whole stay; cluster stops geographically per day; balanced ≈ 3–4 main stops/day; light arrival/departure days; meals at sensible times; free/cheap activities favored; indoor alternatives on rainy days; nightlife only if interested.
6. Tags and editing rules (§3.3).
7. Chat style: short paragraphs, light markdown; never paste the whole itinerary in chat.
8. Never claim to have booked anything.

## 5. Tools — specs

All tools: async, Pydantic I/O, 10 s timeout, cached in the `api_cache` table, return
`{"ok": false, "error": "..."}` instead of raising, and have a **mock provider** used when
`TOOL_PROVIDER_MODE=mock` and in tests. All outputs imperial.

### 5.1 `update_trip_profile` (internal)
Input: partial `TripProfile`. Output: merged profile + `missing_required`.

### 5.2 `get_weather` — Open-Meteo (free, no key)
- Input: `lat`, `lng`, `start_date`, `end_date`.
- Within ~16 days → Forecast API (`api.open-meteo.com/v1/forecast`, daily
  `temperature_2m_max/min`, `precipitation_probability_max`, `weather_code`,
  `temperature_unit=fahrenheit`, `precipitation_unit=inch`, `timezone=auto`).
- Beyond → climate estimate: average the same calendar dates over the previous 3 years from
  the Archive API (`archive-api.open-meteo.com/v1/archive`). `source: "climate"`.
- Map WMO weather codes → text in code.

### 5.3 Maps — Google Maps Platform (server key)
- `geocode(query)` → `{name, address, lat, lng, place_id}` (Geocoding API).
- `search_places(query, lat, lng, radius_mi, max_results≤8)` → `{name, address, lat, lng,
  place_id, rating, user_rating_count, price_level, primary_type}` via **Places API (New)
  Text Search** with a minimal **field mask** (fields determine billing SKU).
- `get_travel_times(origins[], destinations[], mode)` → minutes + miles via **Routes API**
  `computeRouteMatrix`; fallback haversine ÷ mode speed, flagged `estimated: true`.
- Keep usage inside the monthly free caps; set quota limits (setup guide).

### 5.4 `search_hotels` — SerpApi Google Hotels (prices) → fallback Google Places
- Input: `city` (or lat/lng + area), `check_in`, `check_out`, `adults`, `budget_level`, `max_results≤5`.
- Primary: **SerpApi `google_hotels` engine** (`check_in_date`, `check_out_date`, `adults`,
  `currency=USD`, `gl=us`, `hl=en`, sort by lowest price, optional max price by budget level).
  Normalize: name, coordinates, rating, `rate_per_night`, `total_rate`, link, property token.
  Record `price_as_of = now()`.
- One search per city per generation; cached 6 h (free quota is small — see setup guide).
- Fallback (no `SERPAPI_KEY` or quota exhausted): Places Text Search `includedType=lodging`
  → no prices (`price_source: "none"`); UI shows "Price unavailable — check links".
- Choose the cheapest option with rating ≥ ~3.8 and a sensible location; return 2 alternatives.

### 5.5 `generate_itinerary` (control tool)
Input: `{ "change_request": string | null }`. Ends the chat loop and runs §3.2 in the same SSE stream.

### 5.6 `tools/links.py` (not exposed to the LLM)
Pure functions per 03 §5. Unit-tested.

## 6. Post-MVP notes
- **Diff-aware edits:** composition returns a patch (add/remove/move items) instead of a full itinerary; UI highlights changes.
- **Flights:** Duffel (test mode), SerpApi `google_flights`; could be a true LLM sub-agent comparing fare trade-offs.
- **MCP:** wrap `tools/*` with FastMCP for external clients.
- **Events/restaurants:** Ticketmaster Discovery API, Places `type=restaurant`.
