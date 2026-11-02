# Decisions Log

Short ADR-style entries. Append new ones at the bottom (next D-number); don't rewrite
history — supersede. Status: **Final** or **Pending RQ-n** (may change after research).

---

### D1 — Spec-driven development (2026-11-01) · Final
Agent-readable specs in `docs/` + a phased plan with acceptance criteria; agents implement one
task/phase at a time. Rejected: single mega-prompt (drifts); heavy spec frameworks (too much ceremony).

### D2 — Stack: FastAPI + React/TS/Vite (2026-11-01) · Final
Details in [AGENTS.md](../AGENTS.md) §3. Rejected: Flask (weaker async/streaming), Django
(too heavy), Streamlit/Gradio (can't do the 3-pane tabbed layout), Jinja + HTMX (map and
streaming chat get awkward).

### D3 — Sub-agents are tools for MVP (2026-11-01) · Final
Weather/maps/hotels are deterministic tools called by one LLM orchestrator. They're API
lookups; an LLM per domain adds cost/latency. Interface kept MCP-ready.

### D4 — UI first against a mock API (2026-11-01) · Superseded by D19
Frontend `ApiClient` with mock + http implementations; 03-contracts.md is shared.

### D5 — History as a collapsible left sidebar (2026-11-01) · Final
ChatGPT-style, collapsible to an icon rail. Alternative (4th tab) rejected: hides history while viewing a plan.

### D6 — Plan as day cards (2026-11-01) · Final
One card per day with a time-ordered list. Flowchart rejected: unreadable beyond ~10 nodes.

### D7 — Default LLM: Claude (2026-11-01) · Superseded by D20 (Claude is now the backup)
`claude-opus-5-5` for the orchestrator, `claude-haiku-5-5` for titles; `claude-sonnet-5-5`
as cheaper option via `LLM_MODEL`.

### D8 — Units: °F and miles (2026-11-01) · Final
Imperial throughout (stored and displayed). No metric toggle in MVP.

### D9 — Swappable LLM provider (2026-11-01) · Pending RQ-1
`backend/app/llm/` adapter layer selected by `LLM_PROVIDER` (`fake`, `openai_compat`,
`anthropic`; see D20); orchestrator owns the tool loop; transcripts provider-native, sessions tied
to their provider. Why: the team may move to a university LLM. RQ-1 may replace the
hand-rolled adapter with a library.

### D10 — Letter tags; editing via chat (2026-11-01) · Final
Every place gets a stable tag (A…Z, AA…; hotels H1/H2) assigned by code and kept across
versions; retired tags never reused. Edits via chat create a new full itinerary version.
Post-MVP: direct editing; diff-based updates with highlights.

### D11 — MVP audience & trip scope (2026-11-01) · Final
Ages 15–35, adults without kids, 2–4 day trips (max 7), 1–2 cities, budget by default, one
hotel per city for the whole stay chosen mainly by price.

### D12 — Hotel prices captured at generation time (2026-11-01) · Pending RQ-3
Prices stored with `price_as_of`; no live refresh. Proposed source: SerpApi Google Hotels;
fallback Google Places lodging without prices; cached in `api_cache`.

### D13 — Trip profile editable via chat only (2026-11-01) · Final
The "What I know so far" strip is read-only in MVP.

### D14 — Database: local SQLite (2026-11-01) · Final
Local file, no cloud; data is small (see 04-backend-design §8). Each teammate has their own
DB; `seed.py` provides shared demo data. Postgres via `DATABASE_URL` only if we deploy.

### D15 — Multi-agent workflow (2026-11-02) · Final
Roles: backend-researcher, frontend-dev, backend-dev, code-reviewer (critic), orchestrated by
the main session (lead). Every agent change — code or spec — passes code-reviewer; up to 2
automatic fix rounds, then a human decides. **Agents never commit**; humans commit and open
PRs. Research is scoped to backend design; the UI is settled by team consensus. Details:
[06-agent-workflow.md](06-agent-workflow.md).

### D16 — AGENTS.md is canonical (2026-11-02) · Final
All agent rules live in `AGENTS.md` (cross-tool standard); `CLAUDE.md` imports it and adds
Claude Code specifics only. Claude Code subagents in `.claude/agents/`, entry-point skills
`/implement-task` and `/research` in `.claude/skills/`.

### D17 — Researcher edits the backend spec directly (2026-11-02) · Final
backend-researcher writes `docs/research/RQ-n-*.md` and rewrites the matching
`[PROPOSED → RQ-n]` section of 04-backend-design.md; code-reviewer critiques the spec edit
like code; a human reads the diff before committing.

### D18 — Staged MVP; one shared checklist (2026-11-02) · Final
Build in stages, each demoable: 1 talking skeleton (chat + LLM-drafted plan, Map/Checklist
tabs disabled) → 2 places on the map → 3 live tools & smarter chat → 4 memory → 5 polish.
No per-person tracks: small items with a Depends column; whoever has time claims the next one
(◐ + initials). Why: tight deadline, variable availability, agents write most code.
Replaces the Phase/Milestone/Track plan. Details: [05-implementation-plan.md](05-implementation-plan.md).

### D19 — No frontend mock mode; the fake LLM covers offline work (2026-11-02) · Final
Dropped `VITE_USE_MOCKS`, `mock.ts` and frontend fixtures. Teammates without a key run the
backend with `LLM_PROVIDER=fake` (canned streamed replies + a sample itinerary). Why: one code
path, less code for agents to write and keep in sync. Supersedes the mock half of D4; the
`ApiClient` interface stays.

### D20 — TAMU AI first, via an OpenAI-compatible adapter (2026-11-02) · Pending H1.2
First real LLM = TAMUS AI (chat.tamu.ai; university-provided, free to students within a daily
allowance) through `openai_compat` using the official `openai` SDK and a configurable
`LLM_BASE_URL`. Claude via the official `anthropic` SDK is the backup. Pending a human
confirming the endpoint, model IDs and JSON support (05 H1.2); tool calling must be confirmed
before Stage 3. Findings: [research/README.md](research/README.md) RQ-2.

### D21 — Every page load starts a new trip; history comes in Stage 4 (2026-11-02) · Final
Planning is usually a fresh task, so opening the app always creates a new session; past trips
are reopened from the history sidebar (built in Stage 4, after tool integration). Stage 1–3
still persist sessions in SQLite.

### D22 — Stage 1 drafts plans without tools (2026-11-02) · Final
To prove the LLM integration early, Stage 1's "Generate plan" asks the LLM for an
`ItineraryDraft` from the chat alone. Code still assigns tags and IDs; coordinates, prices and
weather stay `null` (CONTRACT CHANGE in 03: those fields are nullable). Stage 2 adds place
lookups; Stage 3 adds the tool loop. Baseline: 04 §3.0, §4.0, §5.0, §7.0.

### D23 — Frontend toolchain: React 19, TypeScript 6, shadcn's `cn` package (2026-11-02) · Final
Found while scaffolding S1.2 (frontend-dev, confirmed by code-reviewer):
- **React 19** instead of 18. Current shadcn/ui components are plain function components that
  receive `ref` as a prop (no `forwardRef`); on React 18 that ref is dropped, which breaks Radix
  `asChild` compositions such as `<TooltipTrigger asChild><Button/></TooltipTrigger>` — needed
  for the disabled-tab tooltips in S1.12. Rejected: React 18 with hand-patched components.
- **TypeScript 6.0** instead of the Vite template's 7.x — typescript-eslint supports only
  `<6.1`. Strict mode is on (TS 6 default).
- **shadcn's `cn` npm package** (shadcn-ui/cn, 0.x) instead of `clsx` + `tailwind-merge`,
  because current `shadcn init` generates it. Expect churn while it is pre-1.0; swapping back
  is a one-file change in `src/lib/utils.ts` plus imports.
- Also from current shadcn defaults: Tailwind v4 (`@tailwindcss/vite`), Radix primitives,
  Nova preset (bundled Geist font), `shadcn` as a dependency (its CSS is imported).

---

## Open questions
- TAMU AI: base URL (`https://chat-api.tamu.ai/openai`), model IDs and streaming are confirmed;
  non-streaming calls return no usable response, so the adapter always streams (setup-guide
  §6.2). Still unknown: JSON-schema output (S1.6 uses prompt-JSON instead) and tool calling
  (needed before Stage 3).
- Who owns the shared Google Cloud project (needed from Stage 2) and the Claude Console
  workspace (only if we use the Claude backup)?
