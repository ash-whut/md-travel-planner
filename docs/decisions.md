# Decisions

Short records of settled choices, so nobody (human or agent) re-opens them by accident.
Add new ones at the bottom with a date. To change one, add a new entry that says which one it
replaces.

| # | Decision | Why |
|---|---|---|
| D1 | **Spec-driven, agent-built.** `AGENTS.md` holds the rules; `docs/` holds spec, architecture, contracts, plan. Agents build numbered steps from `docs/plan.md` with a coder → tester → reviewer loop (`/build-steps`). | Agents write most of the code; one shared source of truth keeps them consistent. |
| D2 | **Small numbered steps, every step tested.** The full check (pytest, Vitest, lint, build) must pass before a step is done. The human commits a batch of steps as one commit; agents never commit. | Later steps must not silently break earlier ones; humans stay in control of history. |
| D3 | **Simple over fast.** No performance work, concurrency or extra frameworks until all MVP features work. | Course project; readable code for 4 teammates matters more. |
| D4 | **Stack:** FastAPI + SQLModel/SQLite backend; React + TS + Vite + Tailwind + Zustand frontend. shadcn/ui optional. | Standard, light, good for streaming; SQLite is a local file with nothing to install. |
| D5 | **The v0 UI is the visual base** (vertical Plan/Map/Book tabs, draggable divider, history rail, "Why this?", stepper, "+" picker, light theme). | Already built and agreed by the team (`docs/preview/`). |
| D6 | **Free services only, no credit card:** TAMU AI (LLM), Open-Meteo (weather + city geocoding), Geoapify (places/geocoding) with Nominatim fallback, Leaflet + OSM tiles (map), SerpApi free plan (hotel prices). No Google Maps Platform. | Google requires billing; we want zero cost. |
| D7 | **LLM: TAMU AI via an OpenAI-compatible adapter first;** `fake` provider for offline dev and tests. Provider SDKs only in `app/llm/`. Other adapters (e.g. Anthropic) later if needed. | Free for us; adapter keeps it swappable. |
| D8 | **No LLM tool-calling.** Each turn = one JSON "understand" call (profile updates + action) and then either a streamed reply or the generation pipeline (code calls tools → one JSON compose call → postprocess). | Works with any model, easy to test, no fragile tool loops. |
| D9 | **A letter tag on every stop** (home, airports, hotel, places), assigned by code, stable across versions, retired letters never reused. No H1/H2. | Matches the v0; one simple rule for users. |
| D10 | **Facts come from code/tools, never from LLM text:** tags, coordinates, weather, hotel prices, links. LLM-only costs are labeled "AI estimate". | Grounded, honest plan. |
| D11 | **Editing via chat; each edit = a new full version.** Changed items are marked with `updated_in_version` and highlighted. | Simple to build; the highlight shows what changed. |
| D12 | **Flights are link-only in the MVP** (Google Flights deep link, "check link"). Real fares are a stretch step. | No free flight API worth the effort right now. |
| D13 | **No stored provider transcripts;** context is rebuilt each turn from messages + profile + compact itinerary. | Provider-neutral, simpler DB. |
| D14 | **No separate frontend mock mode;** run the backend with `LLM_PROVIDER=fake` + `TOOL_PROVIDER_MODE=mock`. `?demo=1` loads the fixture trip for screenshots. | One code path for the UI. |
| D15 | **MVP audience & scope:** ages 15–35, adults, 2–4 day trips (max 7), 1–2 cities, budget by default, one hotel per city, °F / miles. | Covers the common case. |
| D16 | **TAMU AI settings (verified 2026-11-06, step 10):** base URL `https://chat-api.tamu.ai/openai`, model `protected.Claude-Opus-5`, key starts with `sk-`. Streaming is truly incremental. JSON mode (`response_format: json_object`) and strict `json_schema` both work. **The adapter must send `stream=False` explicitly for non-streamed calls:** if `stream` is left out, the server streams anyway, and the `openai` SDK returns a raw string. Stream chunks can have empty `content` (two interleaved chunk ids), so skip empty deltas. | Found by a throwaway SDK check; step 12 builds on it. |

## Open questions
- TAMU AI rate limits (not measured in step 10).
- Geoapify free-plan limits and attribution wording (step 32); SerpApi current free quota (step 37).
