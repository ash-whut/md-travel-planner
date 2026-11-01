# md-travel-planner

A chat-driven AI travel planner for short trips: describe your trip in a chat, get a
day-by-day itinerary with lettered places, a map of every stop, and a checklist of what to
book. Edit the plan by chatting ("replace C with a museum").

**Status:** planning. No code yet.

## Getting started
See [docs/setup-guide.md](docs/setup-guide.md). The UI runs on mock data with no keys.

## Docs
- [CLAUDE.md](CLAUDE.md) — rules and context for the coding agent (start here)
- [CONTRIBUTING.md](CONTRIBUTING.md) — team branch/PR workflow
- [docs/setup-guide.md](docs/setup-guide.md) — install, env vars, accounts & API keys
- [docs/01-product-spec.md](docs/01-product-spec.md) — features, scope, success criteria
- [docs/02-architecture.md](docs/02-architecture.md) — stack and system design
- [docs/03-contracts.md](docs/03-contracts.md) — API, SSE events, DB tables, Itinerary schema
- [docs/04-ui-spec.md](docs/04-ui-spec.md) — layout, components, interactions
- [docs/05-agents-and-integrations.md](docs/05-agents-and-integrations.md) — orchestrator, tools, external APIs
- [docs/06-implementation-plan.md](docs/06-implementation-plan.md) — phased build plan
- [docs/decisions.md](docs/decisions.md) — decisions and open questions

## Stack
FastAPI · SQLite (SQLModel) · swappable LLM (Claude first) · React + TypeScript + Vite · Tailwind + shadcn/ui · Google Maps · Open-Meteo
