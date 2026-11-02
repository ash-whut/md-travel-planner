# md-travel-planner

A chat-driven AI travel planner for short trips: describe your trip in a chat, get a
day-by-day itinerary with lettered places, a map of every stop, and a checklist of what to
book. Edit the plan by chatting ("replace C with a museum").

**Status:** planning complete; building **Stage 1 — talking skeleton** (chat with a real LLM +
an LLM-drafted plan). See the [checklist](docs/05-implementation-plan.md). No code yet.

## Getting started
See [docs/setup-guide.md](docs/setup-guide.md). With `LLM_PROVIDER=fake` the app runs with no
keys; TAMU AI (or Claude) gives real replies.

## Docs
- [AGENTS.md](AGENTS.md) — rules for every coding agent and a quick project orientation (start here)
- [CONTRIBUTING.md](CONTRIBUTING.md) — team branch/PR workflow with agents
- [docs/01-product-spec.md](docs/01-product-spec.md) — features, scope, success criteria
- [docs/02-ui-spec.md](docs/02-ui-spec.md) — layout, components, interactions, frontend structure
- [docs/03-contracts.md](docs/03-contracts.md) — API, SSE events, DB tables, Itinerary schema, tag rules
- [docs/04-backend-design.md](docs/04-backend-design.md) — orchestrator, LLM provider layer, tools, runtime
- [docs/05-implementation-plan.md](docs/05-implementation-plan.md) — staged checklist of small items (claim one, run an agent)
- [docs/06-agent-workflow.md](docs/06-agent-workflow.md) — research → implement → review loop
- [docs/research/](docs/research/README.md) — backend research questions and findings
- [docs/setup-guide.md](docs/setup-guide.md) — install, env vars, accounts & API keys
- [docs/decisions.md](docs/decisions.md) — decisions and open questions

## Stack
FastAPI · SQLite (SQLModel) · swappable LLM (TAMU AI first, Claude backup) · React + TypeScript + Vite · Tailwind + shadcn/ui · Google Maps · Open-Meteo
