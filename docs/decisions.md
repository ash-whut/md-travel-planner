# Decisions Log

Short ADR-style entries. Append new ones at the bottom; don't rewrite history — supersede.

---

### D1 — Development approach: spec-driven with agent context files (2026-11-01)
**Decision:** `CLAUDE.md` (always-loaded agent rules) + `docs/` specs (product, architecture,
contracts, UI, agents) + a phased implementation plan with acceptance criteria. The coding
agent implements one phase at a time.
**Alternatives:** single mega-prompt (drifts, no shared source of truth); heavier spec
frameworks such as GitHub Spec Kit / Kiro-style specs (more ceremony than a course project
needs). `AGENTS.md` is the cross-tool equivalent of `CLAUDE.md`; add one that points at
CLAUDE.md if other agents (Copilot, Cursor, Codex) are used.

### D2 — Stack: FastAPI + React/TS/Vite (2026-11-01)
**Decision:** see 02-architecture §2.
**Alternatives:** Flask (weaker async/streaming), Django (too heavy, no need for admin/ORM
migrations), Streamlit/Gradio (can't do the 3-pane tabbed layout well), Flask/FastAPI +
Jinja + HTMX (viable zero-JS-build option but map and streaming chat get awkward).

### D3 — Sub-agents are tools for MVP (2026-11-01)
**Decision:** weather/maps/hotels are deterministic tools called by one Claude orchestrator.
**Why:** they're API lookups; LLM-per-domain adds cost/latency. Interface kept MCP-ready.

### D4 — UI first against a mock API (2026-11-01)
**Decision:** frontend `ApiClient` interface with mock + http implementations; contracts in
03-contracts.md are shared.

### D5 — History as a collapsible left sidebar (2026-11-01)
**Decision:** ChatGPT-style sidebar left of the plan tabs, collapsible to an icon rail.
**Alternative:** a 4th "History" tab next to Plan/Map/Checklist (saves width, but hides the
history while viewing a plan). Revisit after Phase 1 if the left half feels cramped.

### D6 — Plan representation: vertical day timeline (2026-11-01)
**Decision:** day cards with time-ordered items. Flowchart rejected for MVP: trips are
mostly linear per day, and flowcharts get unreadable beyond ~10 nodes.

### D7 — LLM: Claude via Anthropic SDK, model by env (2026-11-01)
**Decision:** default `claude-opus-5-5` for the orchestrator, `claude-haiku-5-5` for titles.
Switch the main model to `claude-sonnet-5-5` via `LLM_MODEL` if cost becomes a concern.
*Partly superseded by D9 (provider is now swappable).*

### D8 — Units: °F and miles (2026-11-01)
**Decision:** imperial throughout (stored and displayed). No metric toggle in MVP.

### D9 — Swappable LLM provider (2026-11-01)
**Decision:** `backend/app/llm/` adapter layer (`anthropic`, `fake`, later `openai_compat`)
selected by `LLM_PROVIDER`. The orchestrator owns the tool loop (instead of the Anthropic
SDK Tool Runner) so it is provider-neutral. Transcripts are stored provider-native; sessions
are tied to the provider that created them.
**Why:** the team may move to a university-provided LLM or other keys.

### D10 — Letter tags for places; editing via chat (2026-11-01)
**Decision:** every place gets a stable tag (A, B, … AA; hotels H1/H2) assigned by code and
kept across versions; retired tags are not reused. Users edit the plan via chat referencing
tags; each edit creates a new full itinerary version.
**Post-MVP:** direct manipulation editing; diff-based partial updates with highlights.

### D11 — MVP audience & trip scope (2026-11-01)
**Decision:** ages 15–35, adults without kids, 2–4 day trips (max 7), 1–2 cities, budget by
default, one hotel per city for the whole stay chosen mainly by price.
**Why:** covers the common case; broader traveler types are post-MVP.

### D12 — Hotel prices captured at generation time (2026-11-01)
**Decision:** SerpApi Google Hotels for prices (free plan), stored with `price_as_of`; no live
refresh. Fallback: Google Places lodging without prices. Results cached in `api_cache`.

### D13 — Trip profile editable via chat only (2026-11-01)
**Decision:** the "What I know so far" strip is read-only in MVP.

### D14 — Database: local SQLite (2026-11-01)
**Decision:** keep SQLite (local file, no cloud). Chat history and itinerary JSON are small;
see 02-architecture §2.1. Each teammate has their own DB; `seed.py` provides shared demo data.
Postgres via `DATABASE_URL` only if we deploy for multiple users.

---

## Open questions
- Which university LLM endpoint (if any) will we use, and does it support tool calling + JSON-schema output?
- Who owns the shared Google Cloud project / Claude Console workspace?
