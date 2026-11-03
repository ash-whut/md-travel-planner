# Frontend (v0 mock UI)

Clickable v0 of the planner UI, built from the Phase 2 hand-drawn sketches. Runs entirely on
canned data in `src/fixtures.ts` (the sketch's College Station → San Jose trip); no backend or
API keys needed.

```bash
npm install
npm run dev        # http://localhost:5173
```

## What's in it

- **Plan / Map / Book** vertical tabs on the left pane; Map and Book have an [X] back to Plan.
- **Chat** on the right with tag chips inside messages, status lines, version markers, and a
  "+" stop picker that inserts a tag.
- **Draggable divider** between the panes; collapsible history rail on the far left.
- Plan entries: tag · place chip · action · `Est: $ | duration`, "Needs booking" badge,
  "Why this?" (reason + source), and the entry changed in the latest version highlighted.
- Clicking a tag anywhere jumps to that entry (or focuses its pin on the map).
- Map uses Leaflet + OpenStreetMap tiles for now (the spec calls for Google Maps later).

## Screenshot states

URL params open a specific state, so screenshots are reproducible:
`?tab=map`, `?tab=map&day=2`, `?tab=book`, `?tab=book&confirm=flight`, `?why=F`, `?picker=1`,
`?history=1`.

This is not yet the Phase 1 build from `docs/06-implementation-plan.md` (no Zustand stores,
`ApiClient`, shadcn/ui, or contract types). Treat it as a visual reference.
