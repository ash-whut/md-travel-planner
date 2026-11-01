# 06 — Implementation Plan

Build in phases. Each phase ends in a runnable, demoable state. Hand the coding agent one
phase (or a few tasks) at a time; it stops after the acceptance criteria pass and reports.

**Prompt template for the coding agent:**
> Read CLAUDE.md, then docs/06-implementation-plan.md Phase N and every doc it references.
> Implement tasks N.x–N.y only. Verify each acceptance criterion (run the commands), update
> docs if you changed a contract, mark the tasks ☑ here, then stop and summarize what you
> did, what you verified, and any open questions.

Status legend: ☐ todo · ◐ in progress · ☑ done (+ owner initials)

---

## Milestone 1 (first demo, ~1 day): Phase 0 + Phase 1
A clickable UI on mock data: history, streaming chat, day cards with letter tags, map,
checklist, and a mock "replace C" edit. No keys or backend needed.

## Team tracks (once Phase 0 is merged)
Contracts-first lets people work in parallel without blocking each other:

| Track | Phases / tasks | Touches |
|---|---|---|
| A — Shell & chat | 1.3–1.5, later 2.5 | `frontend/src/components/{layout,history,chat}`, stores |
| B — Plan & checklist | 1.6–1.8 | `frontend/src/components/{plan,checklist}` |
| C — Map | 1.9 | `frontend/src/components/map` |
| D — Backend & agent | 2.x → 5.x | `backend/` |

Shared files (`src/types/`, `src/api/`, `src/fixtures/`, `03-contracts.md`): change them in
small, separate PRs and tell the team. See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Phase 0 — Scaffolding ☐
| # | Task |
|---|---|
| 0.1 | Root: `.gitignore` (Python, Node, `.env*` except `.env.example`, `*.db`, `.venv/`), README quick start. |
| 0.2 | `frontend/`: Vite React-TS; Tailwind; shadcn/ui init (Button, Tabs, Dialog, Tooltip, ScrollArea, Checkbox, DropdownMenu, Input, Skeleton, Sonner); ESLint + Prettier; `@/` alias. |
| 0.3 | `backend/`: layout from CLAUDE.md; `requirements.txt` (fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlmodel, sse-starlette, httpx, anthropic, pytest, pytest-asyncio); `/api/health`; CORS. |
| 0.4 | `.env.example` files for both sides (variables in setup-guide.md). |

**Accept:** `npm run dev` shows the app; `uvicorn` serves `/api/health`; `pytest` runs 1 test; lint passes.

---

## Phase 1 — UI shell on mocks ☐
| # | Task |
|---|---|
| 1.1 | `src/types/` mirroring 03-contracts. `src/lib/format.ts` (12h times, °F, miles, money, dates). |
| 1.2 | `src/api/client.ts` interface + `mock.ts` (04 §8) + fixtures: 3 sessions; planned 3-day Austin trip with real coords, tags A–K, H1 with price/as-of, checklist; v2 fixture for the "replace C" mock edit. `http.ts` stub. |
| 1.3 | Zustand stores (sessions, chat, plan). |
| 1.4 | `AppShell` 3-pane layout; collapsible `HistorySidebar` (new, select, inline rename, delete w/ confirm). |
| 1.5 | `ChatPanel`: markdown messages, streaming, status lines, version markers, Send/Stop, auto-scroll, error + Retry, placeholder switch after plan exists. |
| 1.6 | `PlanTabs` with disabled state + tooltips; Plan empty state with `TripProfileCard` + Generate button + generation skeleton. |
| 1.7 | `TagBadge` component; `PlanView`: header, assumptions, `LodgingCard`, `DayCard`s, `ItineraryItem`s with tags, transit connectors, weather chip, booking badge. |
| 1.8 | `ChecklistView`: grouped sections, progress, optimistic checkbox, links, "as of" prices, "Book for me" → coming soon. |
| 1.9 | `MapView`: tag-badge markers colored per day, H1/H2 hotel markers, day filter chips, fit-bounds, polylines, info windows, side list ↔ marker sync; missing-key placeholder; "show on map" from PlanView. |
| 1.10 | Polish: empty/loading states, focus styles, aria labels, < 1024px Plan/Chat toggle. |

**Accept (mock mode):**
- Create/open/rename/delete sessions; deleting the active one switches correctly.
- Messages stream with status lines; Stop works; input disabled while streaming.
- Map/Checklist disabled with tooltip until a plan exists; Generate → statuses → plan → tabs enabled.
- Letters on day cards match letters on map markers; clicking a tag opens the map on that place.
- Sending "replace C" on the planned session shows v2: C gone, new place is L, all other letters unchanged, version marker in chat.
- `npm run build` and `npm run lint` pass.

---

## Phase 2 — Backend foundation + real wiring ☐
| # | Task |
|---|---|
| 2.1 | `core/config.py`; `db/` engine + tables (session, message, itinerary, api_cache) + repositories; create on startup. |
| 2.2 | `schemas/` Pydantic models incl. Itinerary validators. Tests with good/bad fixtures (export the frontend fixture as JSON to share). |
| 2.3 | `agent/tags.py` + tests (first assignment, stability across versions, retired letters never reused, AA after Z, H1/H2). |
| 2.4 | REST routes: sessions CRUD, checklist PATCH (+ status carry-over helper). |
| 2.5 | `llm/` protocol + `fake_provider.py`; orchestrator skeleton with the tool loop; SSE helpers; `/messages` + `/generate` routes; per-session lock (409); client-disconnect handling. |
| 2.6 | `db/seed.py` — loads demo sessions (same as frontend fixtures) into a fresh DB (`python -m app.db.seed`). |
| 2.7 | Frontend `http.ts`; run with `VITE_USE_MOCKS=false`. |
| 2.8 | API tests (`TestClient`, fake provider): CRUD, cascade delete, SSE order, 409. |

**Accept:** full UI works against the backend with `LLM_PROVIDER=fake`; data persists across restarts; `pytest` green.

---

## Phase 3 — Real LLM: intake chat ☐
| # | Task |
|---|---|
| 3.1 | Load `claude-api` skill. `llm/anthropic_provider.py` implementing the protocol (streaming, tool format conversion, structured output, effort/thinking, refusal handling, caching, append-only transcript). |
| 3.2 | `prompts/system.md` per 05 §4; per-turn context (today's date, profile, compact itinerary with tags). |
| 3.3 | `update_trip_profile` tool + merge + `missing_required` + `profile` event. |
| 3.4 | Auto-title via `LLM_FAST_MODEL` → `title` event. |
| 3.5 | Greeting on session create; error mapping → `error` SSE; partial text saved on abort; `chat_enabled` when provider differs. |
| 3.6 | `llm/openai_compat_provider.py` stub raising a clear "not implemented yet" error. |

**Accept:** a real conversation fills the profile in ≤ 5 turns; ≤ 2 questions per turn, no re-asking; title appears; scope limits enforced politely; reopening continues coherently.

---

## Phase 4 — Tool providers ("sub-agents") ☐
| # | Task |
|---|---|
| 4.1 | Tool base: Pydantic I/O, timeout, `api_cache`-backed caching, error envelope, mock switch. |
| 4.2 | `weather.py` (Open-Meteo forecast + climate fallback, °F, WMO mapping). |
| 4.3 | `maps.py` (geocode, search_places w/ field masks, travel times in miles + haversine fallback). |
| 4.4 | `hotels.py` (SerpApi Google Hotels, cheapest-first, whole-stay totals, `price_as_of`; Places lodging fallback). |
| 4.5 | `links.py` deep links. |
| 4.6 | Register tools; human-readable `status` labels; concurrent execution. |
| 4.7 | Tests on recorded fixtures; `pytest -m live` smoke tests. |

**Accept:** "what's the weather like there?" triggers `get_weather` with a status line and a grounded °F answer; tool tests pass offline; a repeat hotel search hits the cache (no quota used).

---

## Phase 5 — Generation & chat editing ☐
| # | Task |
|---|---|
| 5.1 | `generate_itinerary` tool + `/generate` → research loop. |
| 5.2 | `ItineraryDraft` structured composition. |
| 5.3 | `postprocess.py`: tags, IDs, links, prices, checklist, validation + repair, versioning, checklist carry-over. |
| 5.4 | Editing: compact itinerary in context, tag resolution rules in prompt, "change only what was asked" composition, change summary message, `itinerary_version` on message. |
| 5.5 | Scenario scripts in `backend/tests/scenarios/` (e.g. solo weekend Austin; 3 friends NOLA 3 days; 2 cities Dallas + Fort Worth 4 days; vibe-only "beach weekend"; edit sequence "replace C", "move E to day 2", "cheaper hotel"). |

**Accept:** fresh session → valid 3-day itinerary in < ~60 s with continuous statuses; hotel prices + as-of come from the tool; "replace C" yields v2 where only C changes and other letters persist; checklist checkmarks survive edits.

---

## Phase 6 — Hardening & demo polish ☐
| # | Task |
|---|---|
| 6.1 | Loading/error state audit; retry paths. |
| 6.2 | Per-turn logging: tokens, cache hits, tool calls, duration, SerpApi quota used. |
| 6.3 | Optional: real route polylines (Routes API). |
| 6.4 | README demo script; verify setup-guide from a clean clone. |
| 6.5 | Optional IUI study hooks (e.g. log tag-based edit requests, thumbs up/down on plan versions). |

**Accept:** clean clone + setup guide → working app in < 15 min; demo script runs end-to-end.

---

## Post-MVP backlog
Diff-aware edits with highlights · direct editing in Plan view · editable profile chips ·
flights agent · Book-for-me · OpenAI-compatible/university provider · export (PDF/.ics) ·
mobile · auth/deploy · MCP wrappers.
