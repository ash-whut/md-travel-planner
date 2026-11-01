# 01 — Product Spec

## 1. Summary

A web app where one user plans a short trip by chatting with an AI travel agent. The agent
gathers details about the traveler and the trip, consults weather, maps, and hotel data,
then generates a structured itinerary. The itinerary is viewable as a day-by-day plan, as
lettered points on a map, and as a checklist of things to book. The user edits the plan by
chatting, referring to places by their letter tag ("swap C for something cheaper"). Every
planning session is saved and can be reopened, renamed, or deleted.

## 2. Target users & trip scope (MVP)

We deliberately optimize for one common case instead of every traveler type.

| Dimension | MVP target | Handling outside the target |
|---|---|---|
| Age / group | 15–35, solo or small group of adults (1–6), no kids | Agent still plans, but no kid/accessibility-specific logic |
| Trip length | **2–4 days** (supported range 1–7) | > 7 days: agent explains the MVP limit and offers to plan the first 7 |
| Cities | **1–2 cities** | > 2: agent asks the user to pick the 2 main ones |
| Budget | Budget-conscious by default: cheapest reasonable options | User can ask for "mid-range" / "nicer" |
| Lodging | **One hotel for the whole stay** (one per city for 2-city trips), chosen mainly by total price | User can ask to split stays |
| Units | **°F, miles**, US-style dates in UI (Sat, Apr 3) | — |

## 3. Core user flow

1. User opens the app → the most recent session (or a new one) is shown.
2. Agent greets and asks questions; user answers freely in chat.
3. A "What I know so far" strip fills in as the agent learns details.
4. When required details are known, the agent offers to generate. The user can also click
   **Generate plan** (or type "just make the plan") at any time — missing details are filled
   with defaults that are listed as **assumptions**.
5. The Plan tab renders the itinerary as day cards; every place gets a **letter tag**
   (A, B, C…). Map and Checklist tabs become enabled.
6. User edits through chat using tags ("remove B", "move E to day 2", "cheaper hotel") →
   a new itinerary version replaces the displayed one; unchanged places keep their letters.
7. User can open past sessions from the history sidebar.

## 4. Features (MVP)

### F1. Chat (right half of screen)
- Streaming assistant responses (token-by-token), markdown rendering.
- Status lines while the agent uses tools, e.g. "Checking weather for Austin…".
- Enter to send, Shift+Enter for newline; disabled while streaming; Stop cancels.
- After a plan exists, input placeholder hints: "Edit by letter — e.g. 'replace C with a museum'".

### F2. Information gathering (intake)
Conversational, at most 1–2 questions per turn, never a form dump. The agent should get
to a plan quickly — a typical intake is 3–5 turns.

**Required (ask unless already given):**
| Slot | Example | Default if user says "just generate" |
|---|---|---|
| Destination: 1–2 cities, or a vibe to get suggestions | "Austin" / "somewhere with beaches, 4h drive" | — (must have at least a region; agent suggests 3 options) |
| Dates, or duration + rough time | "Mar 6–8" / "a weekend in March" | next upcoming weekend |
| Origin (home city / airport) | "College Station" | ask once; else omit flight items |
| Number of travelers | "3 of us" | 1 |
| Interests | "food, nightlife, hiking" | popular highlights |

**Optional (ask only if natural):** budget level (default **budget**), pace (default
balanced), must-see places, things to avoid, dietary needs, transport (car / transit / walk),
hotel area preference.

### F3. Trip profile strip
A compact "What I know so far" strip showing known slots as chips and missing required
slots in muted style. Read-only in the MVP — corrections happen via chat.

### F4. Itinerary — Plan tab (day cards)
- Header: trip title, dates, travelers, total estimated cost range, weather summary, assumptions.
- One **card per day**: date, theme title, city, weather chip (°F), and a time-ordered list
  of items (activity / meal / transit / lodging / free time) with short description,
  estimated cost, and a "needs booking" badge where relevant.
- Each item at a place shows that place's **letter tag** badge.

### F5. Location tags
- Every distinct place in the itinerary gets a tag: **A, B, C … Z, AA, AB …**, assigned in
  order of first appearance (day 1 morning first).
- Lodging gets **H1** (and **H2** for a second city) so hotels are distinguishable.
- A place visited twice keeps one tag.
- **Tags are stable across edits**: places that remain keep their letters; new places get the
  next unused letter; letters of removed places are not reused within the session (so older
  chat messages that mention "C" stay unambiguous).
- Tags appear on Plan items, map markers, and are understood by the agent in chat.

### F6. Editing via chat
- Any change request after a plan exists produces a new itinerary version (v2, v3 …).
- The agent replies with a 1–3 line summary of what changed ("Replaced C (Museum X) with
  M (Park Y); moved E to day 2.").
- Requests can reference tags, days, times, or names. If a reference is ambiguous the agent asks.
- MVP re-renders the whole plan; it does not highlight diffs.

### F7. Map tab (disabled until a plan exists)
- Google Map with markers labeled by **letter tag**, colored per day; hotels with a bed icon + H1/H2.
- Day filter chips ("All", "Day 1" …); polyline connecting the day's stops in order.
- Marker click → info window (tag, name, day, time). List item click → pan to marker.

### F8. Checklist tab (disabled until a plan exists)
- Grouped: Flights, Lodging, Activities/Tickets, Local transport, Documents, Packing.
- Each item: title, details, date, recommended option, external links (Google Flights,
  Skyscanner, Booking.com, Google Hotels…), persisted checkbox, and a **Book for me** button
  that shows "Coming soon".
- Hotel items show the **price found at generation time**, labeled "as of {date/time}".
  No live refresh; prices are understood to change.
- Flights are **link-only** items (pre-filled search links; no flight API or prices).

### F9. History (left, never disabled)
- Sessions newest first; New trip button; click to load chat + latest itinerary.
- Rename (inline) and Delete (confirm). No archive, no search.
- Titles auto-generated after the first user message ("Austin · Mar 6–8"), renamable.

## 5. Non-functional requirements

- **Latency:** first streamed token < 3 s; generation shows continuous status updates and
  should finish in < ~60 s for a 3-day trip.
- **Cost:** free tiers for all external APIs; the LLM is the only paid component and is
  swappable (see 05 §2).
- **Resilience:** tool/API failure → agent continues and states the gap. A failed generation
  never replaces the previous itinerary.
- **Persistence:** local SQLite file; survives restarts. No cloud services required.
- **Desktop-first** (≥ 1280 px), usable at 1024 px.
- **Accessibility basics:** keyboard navigable, visible focus, contrast, aria labels.

## 6. Out of scope (MVP) → post-MVP if time allows

- Direct manipulation editing (drag items, click-to-edit chips, inline edits).
- Partial / diff-based plan updates with visual highlighting of changed parts.
- Editable trip profile chips.
- Accounts/auth, multi-user, real bookings, flight API, live price refresh.
- Families with kids, accessibility planning, trips > 7 days or > 2 cities.
- Mobile layout, sharing/export, history search/archive, metric toggle.

## 7. Post-MVP roadmap (ordered)

1. Diff-aware edits: only changed items re-render, changes highlighted.
2. Direct editing in the Plan view (drag between days, delete, reorder) with agent re-validation.
3. Flights agent (real fares) → recommended option in checklist.
4. "Book for me" flow.
5. More agents: events, restaurants, local transport.
6. Export (PDF / .ics), share link; auth + deployment.

## 8. Success criteria for the MVP demo

- Empty chat → rendered 2–4 day itinerary in under ~3 minutes of conversation.
- Plan, Map, and Checklist show the same itinerary; letters match between Plan and Map.
- "Replace C with something else" produces v2 where only C changes and other letters persist.
- Weather per day comes from the weather tool (°F; forecast or climate average, labeled).
- Hotels and their prices come from the hotel tool, with an "as of" timestamp.
- History create / reopen / rename / delete work and persist across restarts.
