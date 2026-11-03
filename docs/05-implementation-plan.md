# 05 — Implementation Plan

The MVP is built in **stages**, and each stage ends in something we can demo. Inside a stage the work is one shared checklist of small items. There are no per-person tracks: whoever has time that day claims the next item.

Every code or spec change made by an agent goes through code-reviewer before anyone commits it. The loop is described in [06-agent-workflow.md](06-agent-workflow.md).

## How to work this list

1. **Pick an item.** Take any ☐ item in the earliest stage that isn't finished, as long as every item in its **Depends** column is ☑.
2. **Claim it.** Set the item to `◐ <initials>`, then commit and push that one-line change so nobody else starts it.
3. **Run it.** How depends on the item's type:
   - **FE / BE item** (Claude Code): `/implement-task S1.4`. For a range, `/implement-task S1.5-S1.6`.
   - **Research item:** `/research RQ-4`.
   - **H item:** a human does it. Agents don't run H items.
   - **Other tools:** use the manual prompt in [06-agent-workflow.md](06-agent-workflow.md) §6.
4. **Finish it.** On reviewer APPROVE, the item is marked `☑` and you add your initials. Then review the diff, commit with the suggested message, and open the PR.

**Status:** ☐ todo · ◐ in progress (with initials) · ☑ done (only after reviewer APPROVE).

**Agent:**

| Code | Who does the item |
|---|---|
| FE | frontend-dev |
| BE | backend-dev |
| RS | backend-researcher |
| H | a human |

**Every stage's acceptance includes:**
- code-reviewer APPROVE on each item;
- `npm run lint && npm run build` passing;
- `pytest backend/tests` passing.

**A research (R) item is accepted when:**
- a research note exists, with sources and the date each was accessed;
- the matching 04 section has been rewritten and tagged [DECIDED], and it extends the stage baselines rather than replacing them silently;
- a decisions.md entry has been added;
- any `CONTRACT CHANGE` is flagged, along with its effect on the frontend;
- code-reviewer has approved it, and a human has read the diff.

---

## Stages at a glance

| Stage | What you can demo | Research needed first | Keys needed |
|---|---|---|---|
| **1 — Talking skeleton** | The chat streams real LLM replies. "Generate plan" asks the LLM for a day-by-day plan with letter tags. Map and Checklist tabs are visible but disabled. | none (baseline in 04 §3.0, §4.0, §5.0, §7.0) | none with the fake LLM; a TAMU AI key (or Claude key) for a real LLM |
| **2 — Places on the map** | Places in the plan are looked up on Google. The Map tab shows lettered markers and a list. Clicking a tag in the plan focuses the map on it. | RQ-4 | Google browser key, Map ID, server key |
| **3 — Live tools & smarter chat** | Weather, hotels with prices, and booking links. The chat fills in the trip profile. Chat edits like "replace C" keep the other tags stable. The Checklist tab works, and so does the Stop button. | RQ-1, RQ-3, RQ-5, RQ-6, RQ-7 | + SerpApi |
| **4 — Memory** | Every page load starts a new trip. A history sidebar opens, renames and deletes past trips. Trips get auto-titles. | — | — |
| **5 — Polish & demo** | Error and retry paths, responsive layout, logging, demo script, a check from a clean clone. | — | — |

---

## Stage 1 — Talking skeleton  ☐

Stage 1 has no tools: no weather, no maps, no hotels. The LLM drafts the plan from the chat alone. Code assigns the letter tags. Coordinates, prices and weather stay `null` for now.

Backend rules for this stage are in 04-backend-design §3.0, §4.0, §5.0 and §7.0. The endpoints and events it uses are listed in 03-contracts §3–§4, in the "Stage" column.

| ID | Agent | Item | Depends | Status |
|---|---|---|---|---|
| H1.1 | H | Commit the docs and create your working branch. | — | ☐ |
| H1.2 | H | **Get a TAMU AI API key and test it** (setup-guide §6.2). Steps:<br>1. chat.tamu.ai → profile icon → Settings → Account → API Keys → create/copy a key.<br>2. Run the PowerShell test in setup-guide §6.2 to find which base URL on `chat-api.tamu.ai` accepts the key, list the model IDs, and send one chat message.<br>3. After S1.1 exists, put the key in `backend/.env` only (git-ignored).<br>4. Write the base URL and model names in setup-guide §6.2. **Never write the key there.** | — | ☐ |
| H1.3 | H | *(Optional backup.)* Claude Console API key with a monthly spend limit (setup-guide §6.1). | — | ☐ |
| S1.1 | BE | **Repo and backend skeleton.**<br>• Root `.gitignore`: Python, Node, `.env*` except `.env.example`, `*.db`, `.venv/`.<br>• `backend/` layout per AGENTS.md §3.<br>• `requirements.txt`: fastapi, uvicorn[standard], pydantic-settings, sqlmodel, sse-starlette, httpx, openai, anthropic, pytest, pytest-asyncio.<br>• `app/main.py`: CORS for `http://localhost:5173` and `GET /api/health`.<br>• `core/config.py`: `Settings`, with `LLM_PROVIDER` defaulting to `fake`.<br>• `backend/.env.example`.<br>• One passing test. | — | ☑ |
| S1.2 | FE | **Frontend skeleton.**<br>• `frontend/` created with Vite React-TS, plus Tailwind.<br>• shadcn/ui components: Button, Tabs, Tooltip, ScrollArea, Textarea, Skeleton, Sonner.<br>• ESLint and Prettier.<br>• `@/` import alias.<br>• `frontend/.env.example` containing `VITE_API_BASE_URL`. | — | ☑ |
| S1.3 | BE | **Database and schemas.**<br>• SQLModel tables `session`, `message` and `itinerary` (03 §1). Skip `api_cache` until Stage 2.<br>• Pydantic models from 03 §2: `SessionSummary`, `SessionDetail`, `Message`, `Itinerary` with its validators, and the SSE payloads.<br>• Tests using a good and a bad fixture, `backend/tests/fixtures/itinerary_austin*.json`. | S1.1 | ☑ |
| S1.4 | BE | **Session routes.**<br>• `POST /api/sessions` creates a session plus a fixed greeting message.<br>• `GET /api/sessions/{id}` returns the session, or 404.<br>• Tests. | S1.3 | ☑ |
| S1.5 | BE | **LLM layer v0 (04 §3.0).**<br>• `llm/base.py`: a protocol with `stream_text` and `generate_json`.<br>• `fake_provider.py`: streams a canned reply in chunks, and returns a draft built from a fixture.<br>• `factory.py`: picks the provider from `LLM_PROVIDER`.<br>• Tests. | S1.1 | ☑ |
| S1.6 | BE | **TAMU AI adapter, `openai_compat_provider.py` (04 §3.0).**<br>• Uses `AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)`.<br>• **Always streams** (TAMU AI has no usable non-streaming response); skips empty and filler chunks and ignores thinking fields (04 §3.0).<br>• `generate_json` puts the JSON schema in the prompt, collects the streamed text, extracts the JSON object, validates it with Pydantic, and retries once with the validation errors.<br>• Unit-test the chunk handling with a recorded TAMU stream fixture.<br>• `python -m app.llm.smoke` prints one streamed reply and one small JSON object. It is not run by pytest. | S1.5 | ☑ |
| S1.7 | BE | *(Optional.)* **`anthropic_provider.py`.** Load the `claude-api` skill first. Implement `stream_text` and `generate_json` using native structured output. | S1.5 | ☐ |
| S1.8 | BE | **Chat endpoint `POST /api/sessions/{id}/messages` (SSE).**<br>• Events, in order: `message_start` → `token`* → `done`; or `error` in place of `done`.<br>• Saves the user message and the assistant message.<br>• The LLM's context is `agent/prompts/system.md` (v0, 04 §4.0) plus the message history.<br>• Tests with the fake provider: event order and persistence.<br>• **Review notes (carry-over):** turn an `LLMError` from `get_provider`/`get_llm` (e.g. provider not configured) into an SSE `error` event, not a 500; never show `str(err)` to users, send a friendly message plus `retryable`; reuse `repositories.list_messages` for history; move the `client` fixture from `tests/test_sessions.py` into `tests/conftest.py`, keeping its warning (no `with TestClient(app)`, which would create `backend/travel.db`); optionally cache the provider per process. | S1.4, S1.5 | ☑ |
| S1.9 | BE | **Draft-to-itinerary step (04 §5.0).**<br>• `schemas`: the `ItineraryDraft` model.<br>• `agent/tags.py` v1: first-time tag assignment only.<br>• `agent/postprocess.py` v0: turns a draft into a valid `Itinerary`.<br>• Unit tests: tag order, H1/H2, AA after Z, a checklist item for each `booking_required` item, and validation passing.<br>• **Review notes (carry-over):** add `backend/app/llm/fixtures/itinerary_draft.json` for the fake provider; keep `ItineraryDraft`'s top-level fields required with no defaults (consider `extra="forbid"`), because `extract_json` can return an inner object from a truncated reply and that must fail validation (add a test that a bare place object fails); define the checklist ID scheme (`chk-lodging-H1`, `chk-booking-<item id>`) in 04 §5.0. | S1.3 | ☑ |
| S1.10 | BE | **Generate endpoint `POST /api/sessions/{id}/generate` (SSE).**<br>• Events, in order: `message_start` → `status` ("Drafting your itinerary…") → `itinerary` → `token` (a short fixed summary) → `done`.<br>• Builds the draft from the chat history using `prompts/generate.md`, then runs postprocess.<br>• Saves the result as the next itinerary version and sets the session status to `planned`.<br>• If validation fails, retry once. If it fails again, send `error`.<br>• Tests with the fake provider.<br>• **Review notes (carry-over):** check a full draft from TAMU isn't cut off (no `max_tokens` is set), and that a truncated reply ends in the retry/error path; show only friendly error text, never `str(err)`. Also: give the generate path the same empty-reply guard that chat now has (S1.8 cleanup); in `prompts/generate.md`, state the lodging date rules the draft validator enforces (check_in on/after start_date; check_out on/before end_date, so the last day is departure with no hotel night; stays must not overlap) so the single retry is rarely spent on them. | S1.8, S1.9 | ☑ |
| S1.11 | FE | **Types and API client.**<br>• `src/types/`: the Stage 1 subset of 03.<br>• `src/lib/format.ts`.<br>• `src/api/client.ts` interface, plus `http.ts` implementing `createSession`, `getSession`, `sendMessage` and `generate`. Streams use `@microsoft/fetch-event-source` with an AbortController.<br>• **Review notes (carry-over):** every field marked `null` in 03 §2.2 is nullable in the TS types; TripProfile scalars come back as `null` (not missing), `budget_level` defaults to `budget`, `missing_required` is `[]` until Stage 3. Add the missing `null` markers to 03 §2.1 as a flagged clarification. Also (03 notes from S1.8/S1.10): `status` events have no `end` state in Stage 1; invalid bodies return `400 {detail}`, not 422; `generate` sends an empty `{}` body; the fixed `token` text after `itinerary` is a saved assistant message whose id is `message_id`. | S1.2 | ☑ |
| S1.12 | FE | **Store and layout.**<br>• Zustand store holding the session, messages, streaming state, itinerary and generation state.<br>• `AppShell`: the Plan area on the left, with tabs Plan / Map / Checklist. Map and Checklist are disabled, with a "Coming soon" tooltip. Chat is on the right.<br>• Every page load calls `POST /sessions`, so each load is a new trip.<br>• **Review notes (carry-over):** clear the status line when `itinerary` or `error` arrives; on a generate `error`, keep the current plan on screen. | S1.11 | ☑ |
| S1.13 | FE | **`ChatPanel`.**<br>• Markdown message bubbles.<br>• Enter sends; Shift+Enter adds a new line.<br>• Assistant text appears as it streams in.<br>• A status line.<br>• Input disabled while a reply is streaming.<br>• Error message with a Retry button.<br>• Scrolls to the newest message automatically.<br>• **Review notes (carry-over):** a chat turn is saved only on `done`. On `error`, keep the user's bubble, drop any partial assistant text (some `token`s can arrive before `error`), and have Retry resend the same `content`. Show only the server's friendly `error.message`. The S1.12 store (`useTripStore`) already does this: render `messages`, then `pendingUserMessage`, then `streamingText` while `streaming`, plus `statusLabel`; show the Retry button only when `error.retryable` (it calls `retry()`). Replace the `ChatPanel` placeholder. | S1.12 | ☑ |
| S1.14 | FE | **Plan empty state and generation.**<br>• Empty-state text with a "Generate plan" button. The button is enabled once there is at least one user message and nothing is streaming.<br>• While generating: a skeleton and the status label.<br>• The `itinerary` event shows the plan.<br>• A `ChatHeader` button labelled "Generate plan", which becomes "Regenerate" once a plan exists (02 §2); regenerating creates the next version.<br>• **Review notes (carry-over):** the fixed `token` after `itinerary` ("…click **Regenerate** to update it.") is shown as an assistant bubble; it is also in `SessionDetail.messages` after a reload. | S1.12 | ☑ |
| S1.15 | FE | **`PlanView`.**<br>• Header: title, dates, travelers, summary, cost estimate and assumptions.<br>• `LodgingCard`: shows "Price not available yet" when the price is null.<br>• `DayCard`s containing `ItineraryItem`s, each with a `TagBadge`, 12-hour times and tips.<br>• Weather and transit lines are hidden when null.<br>• **Review notes (carry-over):** label the trip cost range and per-item costs as rough estimates (they are LLM guesses in Stage 1; see the decisions open question). | S1.14 | ☐ |
| H1.4 | H | **End-to-end check.**<br>• Run the app once with `LLM_PROVIDER=fake` and once with the TAMU key.<br>• Add a five-line demo script to the README.<br>• Commit.<br>• TAMU checks (from S1.10): (1) chat "3 days in Austin from Houston, 2 friends, food + music" → Generate: city and length match, last day has no hotel, tags A, B, C… + H1; (2) look in the uvicorn log for "after one retry" warnings (frequent ones mean `generate.md` needs tuning); (3) try a 5–7 day, 2-city trip: two "not a valid ItineraryDraft" warnings mean TAMU cut the reply off (fix: shorter draft or an explicit larger output limit, not more retries); (4) note how long a generate takes (timeout is 60 s between chunks). | all S1 | ☐ |

**Stage 1 is accepted when:**
- **With `LLM_PROVIDER=fake`, from a clean clone:**
  - the page opens a new trip showing the greeting;
  - a sent message streams back a reply;
  - **Generate plan** shows the status, then day cards with letters A, B, C… and H1;
  - Map and Checklist are visible but disabled.
- **With `LLM_PROVIDER=openai_compat` and the TAMU key:**
  - the replies respond to what was typed;
  - the plan matches the destination and trip length discussed in the chat.
- Reloading the page starts a new, empty trip.

---

## Stage 2 — Places on the map  ☐

| ID | Agent | Item | Depends | Status |
|---|---|---|---|---|
| H2.1 | H | **Google Cloud project** (setup-guide §6.3).<br>• Enable Maps JavaScript API and Places API (New).<br>• Create a browser key, a server key and a Map ID.<br>• Set quotas and a $1 budget alert.<br>• Share the keys privately. | — | ☐ |
| R2.1 | RS | **RQ-4:** Google Maps free usage caps, which Places field masks fall into which billing tier, and recommended quotas. | — | ☐ |
| S2.1 | BE | **`tools/maps.py` with `find_place(name, city)`.**<br>• Calls Places Text Search (New) with a field mask set per RQ-4.<br>• Has a mock provider.<br>• Results are cached in the `api_cache` table.<br>• Tests run against recorded fixtures. | R2.1, all S1 | ☐ |
| S2.2 | BE | **Postprocess looks up each place, the lodging and the cities**, running the lookups concurrently.<br>• Fills in coordinates, `place_id`, address, rating, and a maps link that uses the `place_id`.<br>• If a lookup fails, those fields stay null.<br>• `TOOL_PROVIDER_MODE` switches between mock and live.<br>• Tests. | S2.1 | ☐ |
| S2.3 | FE | **`MapView`, using `@vis.gl/react-google-maps`.**<br>• The Map tab is enabled once a plan exists.<br>• Each place gets an `AdvancedMarker` showing its tag badge, colored by day. Hotel markers show H1/H2.<br>• The map fits all markers in view.<br>• A side list of places; clicking a list entry highlights its marker and the reverse.<br>• Info windows.<br>• Places without coordinates are listed as "not on map".<br>• A placeholder appears when the Maps key is missing. | S2.2 | ☐ |
| S2.4 | FE | **Show on map:** clicking a tag in the plan opens the Map tab focused on that place. | S2.3 | ☐ |
| S2.5 | FE | *(Optional.)* Day filter chips and straight lines connecting each day's stops. | S2.3 | ☐ |

**Accept:**
- After generating a plan, the Map tab shows markers whose letters match the day cards.
- Clicking a tag in the plan focuses the map on that place.
- Checklist is still disabled.

---

## Stage 3 — Live tools & smarter chat  ☐

| ID | Agent | Item | Depends | Status |
|---|---|---|---|---|
| R3.1 | RS | RQ-1: how to run the tool loop and swap LLM providers. Must extend the 04 §3.0 baseline. | — | ☐ |
| R3.2 | RS | RQ-6: streaming and runtime — stopping a reply mid-stream, a per-session lock, and how async code talks to SQLite. | — | ☐ |
| R3.3 | RS | RQ-5: Open-Meteo weather. | — | ☐ |
| R3.4 | RS | RQ-3: where hotel prices come from. | — | ☐ |
| R3.5 | RS | RQ-7: deep-link formats for booking sites. | — | ☐ |
| S3.1 | BE | **Tool loop.**<br>• Upgrade the providers to `stream_turn` with tools, per RQ-1 and 04 §3.<br>• Store `agent_transcript`.<br>• The orchestrator runs the loop and sends a `status` event around each tool call. | R3.1 | ☐ |
| S3.2 | BE | **`update_trip_profile` tool.**<br>• Merges new trip facts into the profile and computes `missing_required`.<br>• Sends a `profile` event.<br>• Prompt v1 with the intake rules (04 §4.1). | S3.1 | ☐ |
| S3.3 | FE | **Trip profile card.** Show the "What I know so far" strip / `TripProfileCard` in the Plan empty state, and update it from `profile` events. | S3.2 | ☐ |
| S3.4 | BE | **Weather.** `tools/weather.py` (04 §6.2) fills in the per-day weather. | R3.3, S3.1 | ☐ |
| S3.5 | BE | **Hotels.** `tools/hotels.py` (04 §6.4) adds prices with their as-of time, and alternatives. | R3.4, S3.1 | ☐ |
| S3.6 | BE | **Booking links and checklist.**<br>• `tools/links.py` (04 §6.6).<br>• Full checklist generation.<br>• `PATCH /checklist/{item_id}`, carrying each item's checked state over to the next version. | R3.5, S3.1 | ☐ |
| S3.7 | FE | **Checklist tab.**<br>• Enable the tab.<br>• `ChecklistView`: grouped sections, progress, checkboxes that update before the server confirms, links, prices with their "as of" time.<br>• "Book for me" shows "coming soon".<br>• Weather chips and prices on the day cards. | S3.4, S3.5, S3.6 | ☐ |
| S3.8 | BE | **Generation with tools.** Generation runs a research loop using the tools (04 §4.2). | S3.4, S3.5 | ☐ |
| S3.9 | BE | **Chat editing (04 §4.3).**<br>• `tags.py` v2: tags stay stable across versions.<br>• The chat context includes a compact form of the itinerary.<br>• Change-only regeneration.<br>• A short change summary, with `itinerary_version` set on the message. | S3.8 | ☐ |
| S3.10 | FE | **Version markers in the chat.** The plan updates when an edit happens in chat.<br>• **Review notes (carry-over from S1.12):** chat edits will now send `itinerary` on the chat stream. In `tripStore.ts`, the "error after `itinerary`" branch must then also move `pendingUserMessage` into `messages`, because the server has already saved the user's message (today only generate sends `itinerary`, and it clears `pendingUserMessage` first). | S3.9 | ☐ |
| S3.11 | BE | **Stop and lock.**<br>• Stop on client disconnect and save the partial reply.<br>• A per-session lock returns 409 if a second request arrives while one is streaming (per RQ-6). | R3.2 | ☐ |
| S3.12 | FE | **Stop button**, plus handling for "stopped" and 409 responses. | S3.11 | ☐ |
| S3.13 | BE | **Scenario scripts** in `backend/tests/scenarios/`:<br>• a solo weekend in Austin;<br>• NOLA with friends;<br>• Dallas + Fort Worth;<br>• "beach weekend" with no destination named;<br>• a run of edits. | S3.9 | ☐ |

**Accept:**
- Asking about the weather triggers the weather tool, shows a status line, and gives an answer in °F.
- Hotel prices show their as-of time.
- "replace C" produces a new version where only C changes and every other letter stays the same.
- Checklist checkmarks survive edits.
- Stop works.

---

## Stage 4 — Memory  ☐

| ID | Agent | Item | Depends | Status |
|---|---|---|---|---|
| S4.1 | BE | **More session routes.**<br>• `GET /sessions`, newest first.<br>• `PATCH /sessions/{id}` for renaming.<br>• `DELETE /sessions/{id}`, which deletes everything belonging to the session.<br>• Tests. | all S1 | ☐ |
| S4.2 | BE | **Auto-titles.** Title the trip using `LLM_FAST_MODEL` and send a `title` event (04 §4.4). | S4.1 | ☐ |
| S4.3 | BE | **Provider check and demo data.**<br>• `chat_enabled` is false when the session was made with a different LLM provider.<br>• `db/seed.py` loads demo sessions. | S4.1 | ☐ |
| S4.4 | FE | **`HistorySidebar`.**<br>• Collapsible, listing trips newest first.<br>• Open a trip, rename it inline, and delete it after a confirmation.<br>• Every page load still starts a new trip.<br>• Read-only banner when `chat_enabled` is false.<br>• **Review notes (carry-over from S1.12):** Stage 1 uses one store (`store/tripStore.ts`), not the three stores in 02 §9. Either split out a sessions store here, or record the single-store choice in decisions.md. | S4.1 | ☐ |

**Accept:**
- Reloading the page gives a new trip.
- A past trip can be reopened from the sidebar, showing its chat and latest plan.
- Rename and delete work.
- Titles appear automatically.

---

## Stage 5 — Polish & demo  ☐

| ID | Agent | Item | Depends | Status |
|---|---|---|---|---|
| S5.1 | FE | **Loading and accessibility.**<br>• Check every empty, loading and error state.<br>• Focus styles and aria labels.<br>• A Plan/Chat toggle on screens narrower than 1024px. | — | ☐ |
| S5.2 | FE+BE | Make sure every retry path works. | — | ☐ |
| S5.3 | BE | **Per-turn logging:** tokens, tool calls, duration, and SerpApi quota used. | — | ☐ |
| S5.4 | FE | *(Optional.)* Real route lines from the Routes API. | — | ☐ |
| S5.5 | H | **Demo readiness.**<br>• README demo script.<br>• Follow setup-guide from a clean clone and confirm the app runs in under 15 minutes. | — | ☐ |
| S5.6 | BE | *(Optional.)* IUI study hooks: log tag-based edit requests, and thumbs up/down per plan version. | — | ☐ |

---

## Post-MVP backlog
- Diff-aware edits that highlight what changed
- Editing the plan directly in the Plan view
- Editable profile chips
- Flights agent
- "Book for me"
- Export to PDF or .ics
- Mobile layout
- Login and deployment
- MCP wrappers for the tools
