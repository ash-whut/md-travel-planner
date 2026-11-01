# 04 — UI Spec

Desktop-first single-page app. Visual tone: clean, light, friendly (aimed at 15–35 year-olds;
modern, not corporate). Neutral grays + one accent color + a per-day palette (used on day
cards and map markers). Light mode for MVP. Units °F / miles; times shown 12h ("11:00 AM").

## 1. Layout

```
┌────────────┬──────────────────────────────────┬──────────────────────────────────┐
│ HISTORY    │  [ Plan ] [ Map ] [ Checklist ]  │  Chat                            │
│ + New trip │ ──────────────────────────────── │ ──────────────────────────────── │
│            │  ┌ Day 1 · Sat, Mar 6 ─── ☀ 72° ┐│  assistant bubble                │
│ ▸ Austin…  │  │ 11:00 AM (A) Franklin BBQ    ││            user bubble           │
│ ▸ Dallas…  │  │ 2:00 PM  (B) Zilker Park     ││  ⟳ Checking weather for Austin…  │
│ ▸ New trip │  │ 7:00 PM  (C) Rainey St       ││  assistant bubble (streaming)    │
│            │  └──────────────────────────────┘│                                  │
│            │  ┌ Day 2 · Sun, Mar 7 ──────────┐│ ┌──────────────────────────────┐ │
│  « collapse│  │ …                            ││ │ Edit by letter — e.g. 'rep…' │ │
└────────────┴──────────────────────────────────┴──────────────────────────────────┘
  240px,        flexible                           50% of viewport (min 380px)
  collapsible
  to 56px rail
```

- Chat = right 50% of viewport. History sidebar + plan area share the left half.
- Sidebar collapses to an icon rail (state in localStorage).
- < 1024px: top toggle "Plan | Chat", one visible at a time.

## 2. Component tree

```
<App>
  <AppShell>
    <HistorySidebar>                // never disabled
      <NewTripButton/>
      <SessionList> <SessionListItem/> </SessionList>   // title, relative date, status dot; ⋯ menu: Rename, Delete
      <CollapseToggle/>
    </HistorySidebar>
    <PlanPanel>
      <PlanTabs/>                    // Map & Checklist disabled w/ tooltip until itinerary exists
      <PlanView/> | <MapView/> | <ChecklistView/>
    </PlanPanel>
    <ChatPanel>
      <ChatHeader/>                  // session title (click to rename), "Generate plan" button (label "Regenerate" once planned)
      <MessageList> <MessageBubble/> <StatusLine/> <ErrorBubble/> <VersionMarker/> </MessageList>
      <ChatInput/>
    </ChatPanel>
  </AppShell>
  <ConfirmDialog/> <Toaster/>
</App>
```

## 3. Location tag badge (shared component)

`<TagBadge tag="C" dayColor="…"/>` — a small filled circle (pill for 2-letter tags) with the
letter, background = day color of the place's first appearance; hotels use a dark badge with
a bed icon + "H1". Same component is used in PlanView, map markers, and the map side list,
so the user can match them visually. Clicking a badge in PlanView → Map tab focused on that place.
Hover → tooltip "Refer to this as 'C' in chat".

## 4. Tab details

### 4.1 Plan tab
**Empty state (no itinerary):**
- Icon + "Your trip plan will appear here."
- `TripProfileCard` (read-only): chips for known slots ("📍 Austin", "📅 Mar 6–8",
  "👥 3", "🎯 food, music"), dashed muted chips for missing required ones ("🏠 From where?").
- **Generate plan** button (always enabled; tooltip notes defaults will be assumed if info is missing).
- During generation: 3 skeleton day cards + current status label.

**With an itinerary:**
- `ItineraryHeader`: title, dates, travelers, per-person cost range, weather summary,
  collapsible Assumptions, version badge ("v2 · updated 2 min ago").
- `LodgingCard`(s): H1 badge, name, nights, total price + "per night", "Prices as of Nov 1, 6:04 PM — may change", links.
- `DayCard` per day (all expanded for ≤ 4 days; otherwise first two expanded):
  - Header: "Day 1 · Sat, Mar 6 — Arrival, East Side eats", city, weather chip ("☀ 72° / 51°", "avg" label when climate-based), day color stripe on the left.
  - Ordered list of `ItineraryItem`: time range · `TagBadge` · kind icon · title · 1–2 line description · cost · "Needs booking" badge (→ Checklist item).
  - Between items: transit connector ("🚗 12 min · 3.4 mi").

### 4.2 Map tab
- Full-height Google Map (`@vis.gl/react-google-maps`, `AdvancedMarker` + a custom `TagBadge` pin).
- Day filter chips: All, Day 1…N. Selecting a day fits bounds to that day's places and draws
  its polyline (straight segments for MVP). "All" shows every place, polylines per day in day colors.
- Side list (overlay, collapsible): items of the selected day with tag badges; hover/click ↔ marker highlight + InfoWindow (tag, name, day, time, Google Maps link).
- Missing Maps key → placeholder card pointing to `docs/setup-guide.md`.

### 4.3 Checklist tab
- Progress bar "3 of 9 done".
- Sections in order: Flights, Lodging, Activities & tickets, Local transport, Documents, Packing. Empty sections hidden.
- `ChecklistItem`: checkbox (optimistic PATCH), title (with tag if related to a place), date,
  details, recommended option, link buttons (new tab, `rel="noopener noreferrer"`), **Book for me** → "Booking assistance is coming soon." dialog.
- Prices show "as of {time}" in muted text.

## 5. History behavior

- New trip → `POST /sessions`; becomes active; greeting shown; Plan empty state.
- Click → `GET /sessions/{id}`; skeleton while loading; active item highlighted.
- Rename: inline input; Enter saves, Esc cancels; 1–80 chars.
- Delete: confirm "Delete '{title}'? This can't be undone." Deleting the active session switches to the next most recent (or creates one).
- Switching sessions while streaming aborts the stream first.
- `title` SSE event updates the list live.
- If `chat_enabled=false` (session made with another LLM provider): show the history and plan read-only with a banner "Start a new trip to keep chatting."

## 6. Chat behavior

- Auto-scroll while streaming unless user scrolled up (then "↓ New messages" pill).
- Status lines shown in the transcript, not persisted (MVP).
- `VersionMarker`: a thin divider "Plan updated to v2" after messages with `itinerary_version`.
- Input placeholder: before plan "Tell me about your trip…"; after plan "Edit by letter — e.g. 'replace C with a museum'".
- On `itinerary` event: switch to Plan tab, briefly pulse newly enabled tabs.

## 7. Disabled tab styling

40% opacity, `cursor: not-allowed`, `aria-disabled="true"`, tooltip "Generate a plan to unlock the map/checklist". Skipped by keyboard focus.

## 8. Mock mode (Phase 1)

With `VITE_USE_MOCKS=true` the full UI works with no backend:
- `fixtures/`: 3 sessions — empty intake, mid-intake (partial profile), planned (3-day Austin
  trip, real coordinates, tags A–K, H1 with price, checklist).
- Mock `sendMessage` streams canned replies (~30 chars / 40 ms), emits status + profile
  events; "generate" or the button → status events then fixture itinerary v1.
- Mock edit: a message containing a tag like "replace C" returns fixture v2 where C is
  replaced by a new place tagged L (demonstrates tag stability) + a change summary.
- Create/rename/delete mutate in-memory state (mirrored to localStorage).
