# Product & UI spec

What we are building and how it should look and behave. The **v0 UI in `frontend/`** and the
screenshots in [preview/](preview/) are the visual reference. Data shapes are in
[contracts.md](contracts.md).

## 1. Summary
One user plans a short trip by chatting with an AI planner. The planner learns about the
traveler and the trip, then produces a day-by-day itinerary. The itinerary is shown three
ways: as a **Plan** (day cards), on a **Map** (lettered pins) and as a **Book** list (what to
book, with links). Every stop has a **letter tag** (A, B, C…). The user edits the plan by
chatting with those letters ("change [F] to something vegan"). Past trips live in a history
rail.

## 2. Users & scope (MVP)
| Dimension | Target | Outside the target |
|---|---|---|
| People | ages 15–35, solo or a small group of adults (1–6), no kids | still plans, with no special logic |
| Length | **2–4 days** (max 7) | > 7 days: explain the limit, offer the first 7 |
| Cities | **1–2** | > 2: ask which 2 |
| Budget | budget by default (cheapest reasonable) | "mid-range" / "nicer" on request |
| Lodging | one hotel per city for the whole stay, mainly by price | — |
| Units | °F, miles, US dates ("Fri, Mar 5"), 12h times | — |

## 3. Core flow
1. Opening the app shows the most recent trip, or a new one, with a greeting.
2. The agent asks 1–2 questions per turn: destination → dates → origin → travelers →
   interests. A typical intake is 3–5 turns. The profile chips in the Plan header fill in as
   details arrive.
3. The user clicks **Generate** or types "just make the plan". Missing details are filled with
   defaults, which are listed as **assumptions**.
4. The Plan tab shows the itinerary. Map and Book unlock.
5. The user edits by chat ("replace [H] with something outdoors"). A new version (v2, v3…)
   replaces the plan. Unchanged stops keep their letters, and the changed entry is highlighted
   "Updated in v2".
6. Old trips can be reopened, renamed or deleted from the history rail.

## 4. Layout (desktop-first, ≥ 1280 px, usable at 1024 px)
```
┌──┬──┬──────────────────────────────┬─┬──────────────────────────────┐
│H │P │ Plan / Map / Book content     │↔│ Chat           ✓Profile—✓Trip—✓Plan
│i │L │                               │ │  assistant bubble             │
│s │A │                               │ │            user bubble        │
│t │N │                               │ │  ✓ Checked weather…           │
│o │M │                               │ │  ── Plan updated · v2 ──      │
│r │A │                               │ │                               │
│y │P │                               │ │ [+] Edit by letter — e.g. …   │
└──┴──┴──────────────────────────────┴─┴──────────────────────────────┘
 rail  vertical tabs                 draggable divider
```
- **History rail** on the far left, collapsible.
- **Vertical tabs**: Plan / Map / Book. Map and Book have an ✕ that returns to Plan.
- A **draggable divider** between the plan pane and the chat.
- Light theme. Neutral grays, one accent (indigo), and a per-day colour used on tags and pins.

## 5. Features

### F1. Chat (right pane)
- Assistant text streams in token by token, with markdown.
- Status lines appear while the backend works ("Checking weather for San Jose · Mar 5–7").
- Version markers: "Plan created · v1", "Plan updated · v2".
- Enter sends and Shift+Enter adds a newline. The input is disabled while streaming, and
  **Stop** cancels.
- `[C]` tokens in messages render as clickable **tag chips**. A click jumps to that entry on the
  Plan, or to its pin if the Map is open.
- The **"+" stop picker** next to the input lists the stops and inserts a tag.
- Placeholder: "Tell me about your trip…" before a plan exists; "Edit by letter — e.g.
  'replace H with something outdoors'" after.
- Errors appear inline with **Retry**.

### F2. Intake & trip profile
- Required, asked unless already given:
  - destination (1–2 cities, or a vibe → the agent suggests 3);
  - dates (or duration + rough timing);
  - origin;
  - number of travelers (default 1);
  - interests (default popular highlights).
- Optional, asked only if it comes up naturally: budget (default budget), dietary needs,
  pace, transport, notes.
- The profile is read-only in the UI and corrected via chat. Plan-header chips show it
  ("📍 San Jose, CA", "🏠 College Station, TX", "📅 Mar 5–7", …).

### F3. Plan tab
- **Empty state:** "Your trip plan will appear here", a **Generate** button, and skeleton day
  cards with the current status while generating.
- **Header:** title, dates · travelers · per-person cost range, profile chips, weather summary
  chip, version badge ("v2 · updated Nov 1, 6:08 PM"), a **Regenerate** button (D20), and a
  collapsible "N assumptions made".
- **Day sections:** "Day 1 · Fri, Mar 5 — Travel day" + a weather chip ("☀ 66° / 48°", with
  "avg" when climate-based).
- **Entry rows:**
  - `TagBadge` + time;
  - a place chip with a kind icon, then ": action text";
  - `Est: $300 | 6 hr`, or "check link" when there's no price;
  - a "Needs booking" badge;
  - **"Why this?"**, which expands the reason and the source ("Geoapify", "SerpApi Google
    Hotels · as of Nov 1, 6:04 PM", "AI suggestion").
- Entries changed in the latest version get a highlight bar and an "Updated in v2" badge.
- Prices labeled as estimates come from the AI. Hotel prices come from the hotel tool with
  "as of".

### F4. Letter tags
- Every stop with a location gets a letter (home, airports, hotel, food, sights…), assigned by
  code in order of first appearance. Visiting the same place twice keeps one letter.
- Tags are stable across versions, and removed letters are never reused (rules in
  [contracts.md §3](contracts.md)).
- The same `TagBadge` (a filled circle in the day colour, a pill for "AA") is used in the Plan,
  chat chips, map pins and the stops list. Hovering shows "Refer to this as [C] in chat".

### F5. Map tab (unlocks once the plan has coordinates)
- Leaflet + OpenStreetMap tiles. Pins are `TagBadge`s coloured by day.
- Day chips (All days, Day 1…). Dashed polylines connect each day's stops in order.
- A **Stops** list overlay. Clicking a list row or a pin highlights it and shows its name,
  day and time. Stops without coordinates are listed as "Off map: A, B".
- Clicking a tag anywhere focuses its pin.

### F6. Book tab (unlocks once the plan has bookings)
- A "1 of 4 booked" progress bar, plus "Nothing is booked without your approval".
- Cards: tags (B → C for flights), title, `Est: $…` or "check link", details (dates, nights,
  "as of" time).
- **Book** opens an approval dialog. Confirming opens the provider link in a new tab
  (`rel="noopener noreferrer"`). The user then marks the card **Booked**, which is saved.
- Flights are link-only (Google Flights) in the MVP.

### F7. History rail
- Sessions newest first, a **New trip** button, and a click to load the chat + latest plan.
- Inline rename (Enter saves, Esc cancels, 1–80 chars). Delete with a confirm; deleting the
  active trip switches to the next one, or creates a new one.
- Auto-title once the city/dates are known ("San Jose · Mar 5–7").

## 6. Non-functional (MVP)
- Simple and correct over fast. Generation may take up to about a minute, with status lines
  showing progress.
- Free services only (see [architecture.md §5](architecture.md)). The LLM is the only external
  dependency that can't be mocked away in a live demo.
- A failed generation never replaces the previous plan. A tool failure → the plan still
  generates, and the gap is stated.
- Data lives in a local SQLite file and survives restarts.
- Basic accessibility: keyboard navigable, visible focus, aria labels on icon buttons.

## 7. Out of scope (MVP)
Accounts, multi-user, real bookings / payments, live price refresh, real flight fares,
drag-and-drop editing, editable profile chips, mobile layout, export/sharing, kids/accessibility
planning, trips > 7 days or > 2 cities, performance tuning. Some of these are stretch steps in
[plan.md](plan.md).

## 8. Demo success criteria
- Empty chat → a 2–4 day itinerary in under about 3 minutes of conversation.
- Plan, Map and Book show the same itinerary, with matching letters.
- "Replace [F] with something vegan" → v2: only F changes, the other letters stay, and the
  entry is highlighted.
- Weather comes from Open-Meteo (°F, forecast or climate average, labeled).
- The hotel price comes from the hotel tool with an "as of" time.
- History create / reopen / rename / delete persist across restarts.
