# Backend Research Agenda

The UI is settled by the team; research covers **backend design only**. Each research
question (RQ) resolves a `[PROPOSED → RQ-n]` section of
[04-backend-design.md](../04-backend-design.md). Run one with `/research RQ-n` (Claude Code)
or the manual prompt in [06-agent-workflow.md](../06-agent-workflow.md) §6.

**Constraints every recommendation must respect:** free tier (LLM is the only paid part),
local-only (no cloud DB/hosting), simplicity (4 students, limited time), LLM provider must
stay swappable, MVP scope from [01-product-spec.md](../01-product-spec.md).

**Stage 1 needs no research** — its minimal design is decided in the "Stage 1 baseline"
subsections of 04 (§3.0, §4.0, §5.0, §7.0). Research must **extend** those baselines.

## Agenda

| RQ | Plan item | Status | Question | Resolves (04 §) | Blocks |
|---|---|---|---|---|---|
| RQ-4 | R2.1 | ☐ open | **Google Maps Platform.** Current free monthly caps per SKU for Maps JS (dynamic maps), Advanced Markers/Map ID, Places API (New) Text Search (which field-mask fields trigger which SKU), Geocoding, Routes `computeRouteMatrix`. Recommended field masks and quotas. Is an OSM-based fallback worth building? | §6.3 | S2.1 (Stage 2) |
| RQ-1 | R3.1 | ☐ open | **Orchestration & provider swap.** Extend the Stage 1 adapters (§3.0) with our own tool loop, or adopt a library (PydanticAI, LiteLLM, Anthropic Tool Runner, others)? Needs: streaming text, tool calls with our own status events, structured output (Pydantic), Anthropic + OpenAI-compatible endpoints (TAMU AI), append-only transcripts, readable code. Recommend one, with a minimal code sketch of the loop. | §3 "Full design" | S3.1 (Stage 3) |
| RQ-6 | R3.2 | ☐ open | **Streaming & runtime.** `sse-starlette` vs FastAPI-native SSE (if available in current FastAPI); reliable client-disconnect detection and cancelling the LLM stream; SQLite access from async routes (sync SQLModel in threadpool vs async driver); per-session lock pattern. | §7.1 | S3.11 (Stage 3) |
| RQ-5 | R3.3 | ☐ open | **Weather.** Open-Meteo forecast horizon, Archive API suitability for "climate average" of future dates (or a better endpoint), units params, rate limits, attribution/licensing. | §6.2 | S3.4 |
| RQ-3 | R3.4 | ☐ open | **Hotel prices.** Verify SerpApi Google Hotels (current free quota, request params incl. sort-by-price, response fields: per-night/total price, coordinates, rating, link). Compare 2–3 alternatives (e.g. Amadeus status, RapidAPI Booking APIs, LiteAPI). ToS for our use. Caching/quota strategy for 4 devs. | §6.4 | S3.5 |
| RQ-7 | R3.5 | ☐ open | **Deep links.** Verify current URL formats for Google Flights, Skyscanner, Booking.com, Google Hotels, Google Maps (03 §5): do they pre-fill origin/destination/dates/guests? | §6.6 | S3.6 |
| RQ-2 | H1.2 | ◐ partly answered | **University LLM (TAMU AI).** Findings below. TAMU's API docs are still a work in progress, so a **human** with a key confirms the details (05 H1.2); the researcher may then write `RQ-2-tamu-ai.md` from what the human found. Still open for Stage 3: does the endpoint support **tool calling**? | §3.0, §3.2 | S1.6 live check; S3.1 |

### RQ-2 findings so far (2026-11-02)
- TAMUS AI Chat (chat.tamu.ai / tamus.ai) is the university-approved AI platform for staff,
  faculty, researchers and students; NetID login; offers OpenAI GPT, Anthropic Claude Sonnet
  and Google Gemini models; has a daily usage allowance — VERIFIED:
  [TAMU KB](https://service.tamu.edu/TDClient/36/Portal/KB/PrintArticle?ID=1300),
  [TAMU IT service page](https://www.it.tamu.edu/services/services-by-category/communication-and-collaboration/tamu-ai-chat.html).
- The docs list an "API Integration — obtain an API key and integrate TAMUS AI into your
  applications" section — VERIFIED: [docs.it.tamu.edu/ai](https://docs.it.tamu.edu/ai).
  The API docs themselves are still a work in progress (per a teammate, 2026-11-02).
- API keys are created at chat.tamu.ai → profile icon → Settings → Account → API Keys —
  VERIFIED by a teammate (2026-11-02). This matches Open WebUI, which exposes an
  OpenAI-compatible API (`/api/models`, `/api/chat/completions`).
- `https://chat-api.tamu.ai` is the API host: `/openai/models`, `/api/models` and
  `/openai/chat/completions` return `401 {"message":"Bearer token required (cf)"}` without a
  key — VERIFIED (curl, 2026-11-02). `https://chat.tamu.ai/api/*` redirects to the NetID
  (Cloudflare Access) login — not usable from a backend — VERIFIED (curl, 2026-11-02).
- Base URL `https://chat-api.tamu.ai/openai` accepts a key from the API Keys page; `GET /models`
  returns `protected.Claude-Opus-5`, `protected.Claude Opus 4.1`, `protected.gpt-5.5` —
  VERIFIED by a teammate (2026-11-02).
- Unknown: tool calling, JSON-schema `response_format`, rate limits, data policy for API use.

The researcher updates the Status column (☐ open → ☑ decided) when the reviewer approves.

## Note template — `docs/research/RQ-n-<slug>.md`

```markdown
# RQ-n — <title>
Date: YYYY-MM-DD · Researcher: backend-researcher (+ human reviewer)

## Question
<copied from agenda, plus any clarifications>

## Options considered
| Option | Fit for our constraints | Pros | Cons | Cost / limits |

## Findings
- <claim> — source: <url> (accessed YYYY-MM-DD) — VERIFIED | UNVERIFIED
- …

## Recommendation
<one choice> — why. Fallback: <second choice> and when to switch.

## Impact
- 04-backend-design.md: <sections changed>
- 03-contracts.md: CONTRACT CHANGE yes/no — <details, frontend impact>
- 05-implementation-plan.md: <tasks affected, e.g. new dependency for 0.3>
- setup-guide.md: <accounts/keys/env vars to add or change>

## Risks & open questions
```
