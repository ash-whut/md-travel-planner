# Contracts: API, database, schemas

**Source of truth.** The backend Pydantic models (`backend/app/schemas/`) and the frontend
types (`frontend/src/types/`) mirror this file. Change this file **in the same change** as the
code. A step in [plan.md](plan.md) builds only the parts of this file it names. Fields used by
later steps can stay out until then.

**Conventions**
- JSON is `snake_case`. IDs are UUID4 strings.
- Timestamps are ISO-8601 UTC (`2026-11-01T18:04:05Z`).
- Dates are `YYYY-MM-DD`. Times are local `HH:MM` in 24h; the UI shows 12h ("1:30 PM").
- Money is `{ "amount": 120, "currency": "USD" }`.
- Units are imperial: °F and miles.
- Unknown values are `null`, never made-up placeholders.

---

## 1. Database tables (SQLModel on SQLite, file `backend/travel.db`)

### `session`
| column | type | notes |
|---|---|---|
| id | str (uuid) PK | |
| title | str | default `"New trip"` |
| title_is_custom | bool | true once the user renames it; stops auto-titling |
| status | str | `intake` \| `planned` |
| trip_profile | JSON | `TripProfile` (§2.1) |
| created_at / updated_at | datetime | `updated_at` changes on every message, which sets the history order |

### `message`
| column | type | notes |
|---|---|---|
| id | str PK | |
| session_id | FK → session.id, cascade delete | |
| role | str | `user` \| `assistant` |
| content | text | markdown. `[C]`-style tokens render as tag chips (§2.5) |
| itinerary_version | int \| null | set on the assistant message that came with a new plan version |
| created_at | datetime | |

The LLM context for each turn is rebuilt from these messages + the profile + the latest
itinerary. We do **not** store provider-specific transcripts.

### `itinerary`
| column | type | notes |
|---|---|---|
| id | str PK | |
| session_id | FK, cascade delete | |
| version | int | 1, 2, 3… per session |
| data | JSON | full `Itinerary` (§2.2) |
| created_at | datetime | |

### `api_cache` (added in step 28)
| column | type | notes |
|---|---|---|
| key | str PK | `"{tool}:{sha256 of the args JSON}"` |
| value | JSON | normalized tool result |
| created_at | datetime | |
| ttl_seconds | int | weather 3 h, geocode 30 d, places 7 d, hotels 6 h |

The cache exists to protect free-tier quotas (SerpApi especially), not for speed.

---

## 2. Schemas

### 2.1 `TripProfile`
All fields are optional. The server computes `missing_required`.
```jsonc
{
  "cities": ["San Jose, CA"],          // 0–2 entries
  "vibe": null,                        // "beach, ≤4h drive" when the user wants suggestions
  "start_date": "2027-03-05", "end_date": "2027-03-07",
  "duration_days": 3,                  // 1–7
  "rough_timing": null,                // "first weekend of March" before exact dates
  "origin": "College Station, TX",
  "travelers": 1,                      // adults, 1–6
  "budget_level": "budget",            // budget | mid | splurge; null until stated, plans then assume budget (D17)
  "interests": ["tech", "food", "gardens"],
  "dietary": "vegan",
  "pace": "balanced",                  // relaxed | balanced | packed
  "transport": null,                   // car | transit | rideshare | mixed
  "notes": null,                       // must-sees, things to avoid, hotel area…
  "missing_required": []               // subset of: destination, dates, origin, travelers, interests
}
```
### 2.2 `Itinerary`
**Every stop with a location gets a letter tag**, including home, airports and the hotel. A
stop is stored once in `stops`, and items point to it with `stop_tag`.
```jsonc
{
  "id": "uuid", "version": 2,
  "title": "San Jose — Tech, Tacos & Gardens",
  "summary": "One short paragraph.",
  "start_date": "2027-03-05", "end_date": "2027-03-07",
  "travelers": 1,
  "cities": [ { "name": "San Jose", "region": "CA", "country": "USA", "lat": 37.33, "lng": -121.89 } ], // lat/lng null until geocoded
  "cost_estimate": { "low": 780, "high": 910, "currency": "USD", "source": "ai_estimate" },  // per person; flights included only if priced
  "weather_summary": "Mild and sunny, 48–68 °F",     // null until the weather step; always from the tool
  "assumptions": ["Budget level assumed (none given)"],

  "stops": [
    {
      "tag": "C",                        // A..Z, AA, AB… — assigned by code (§3)
      "name": "San Jose Airport",
      "kind": "airport",                 // home|airport|lodging|food|sight|museum|nature|nightlife|shopping|activity|other
      "address": "1701 Airport Blvd, San Jose, CA",
      "lat": 37.3639, "lng": -121.9289,  // null = shown as "off map"
      "place_id": "geoapify:51a3…",      // provider id, or null; used for tag matching
      "rating": null,
      "map_url": "https://www.google.com/maps/search/?api=1&query=…"
    }
  ],

  "lodging": [                           // one per city; details for a lodging stop
    {
      "stop_tag": "D",
      "check_in": "2027-03-05", "check_out": "2027-03-07", "nights": 2,
      "price_per_night": { "amount": 120, "currency": "USD" },   // null if unknown
      "total_price":     { "amount": 240, "currency": "USD" },
      "price_source": "serpapi_google_hotels",                   // ai_estimate | serpapi_google_hotels | none
      "price_as_of": "2026-11-01T18:04:05Z",                     // null unless from a tool
      "links": [ { "label": "Google Hotels", "url": "https://…" } ]
    }
  ],

  "days": [
    {
      "day_number": 1, "date": "2027-03-05", "title": "Travel day", "city": "San Jose",
      "weather": { "high_f": 66, "low_f": 48, "condition": "sunny", "icon": "☀️", "source": "forecast" }, // forecast|climate; whole object null until the weather step
      "items": [
        {
          "id": "d1-i2",
          "kind": "flight",                  // transit|flight|lodging|meal|activity|free_time
          "stop_tag": "B",                   // null for untagged items (e.g. free time)
          "description": "Board your flight to San Jose.",
          "start_time": "09:15",
          "duration_min": 360,               // null if unknown
          "nights": null,                    // lodging items only
          "est_cost": { "amount": 300, "currency": "USD" },  // per person; null = "check link"
          "cost_source": "ai_estimate",      // ai_estimate | tool | null
          "booking_required": true,
          "booking_id": "bk-flight",         // set when booking_required (step 42+)
          "why": "Lowest fare with one stop that lands before 2 PM.",
          "source": "AI suggestion",         // shown under "Why this?" e.g. "Geoapify", "SerpApi Google Hotels · as of Nov 1, 6:04 PM"
          "transit_from_previous": { "mode": "rideshare", "duration_min": 12, "distance_mi": 4.1, "estimated": true }, // null for the first item; mode: walk|transit|drive|rideshare|flight
          "updated_in_version": null         // set by code to the version that last changed this item
        }
      ]
    }
  ],

  "bookings": [                              // the Book tab (step 42+); [] before that
    {
      "id": "bk-flight",
      "kind": "flight",                      // flight | lodging | activity
      "tags": ["B", "C"],                    // shown as B → C
      "title": "Flight Booking",
      "details": "IAH → SJC round trip · Mar 5 – Mar 7",
      "estimate": null,                      // Money or null ("check link")
      "price_as_of": null,
      "links": [ { "label": "Google Flights", "url": "https://…" } ],
      "status": "todo"                       // todo | booked
    }
  ],
  "created_at": "2026-11-01T18:04:05Z"
}
```

**Validation (Pydantic, run after postprocessing):**
- 1–7 days; number of days = `end_date − start_date + 1`; `day_number` runs 1..N without gaps;
  dates match.
- ≤ 2 cities; ≤ 2 lodging entries.
- Items within a day are sorted by `start_time`.
- Stop tags are unique.
- Every `stop_tag`, `lodging.stop_tag` and `booking_id` resolves.
- Lat/lng are valid ranges or null.

### 2.3 `ItineraryDraft` (what the LLM returns)
Same shape as `Itinerary` **minus** everything code owns:
- `id`, `version`, `created_at`
- tags, `updated_in_version`
- weather, `transit_from_previous`, coordinates
- tool prices, `price_as_of`, links
- item `source` and `cost_source` (code sets "AI suggestion" now; tool steps set it from the tool)
- bookings

Stops get a temporary `key` (`"s1"`, `"s2"`…) and items refer to it with `stop_key`. A stop
may carry a `place_ref` that points at a tool result id (step 34+): the short ref code gave a
found place (`"p3"`). Code copies the coordinates, address, `place_id` and rating from that
tool result and sets the item `source` ("Geoapify"); an unknown ref is ignored.

### 2.4 `TurnAnalysis` (internal, one JSON call per user turn)
```jsonc
{
  "profile_updates": { /* partial TripProfile, only fields the user just stated */ },
  "action": "chat",            // chat | generate | edit
  "change_request": null       // for edit: what to change, in plain words, e.g. "replace [F] with a vegan brunch spot"
}
```

### 2.5 Tag tokens in chat text
Both roles write tags as `[C]`. The frontend renders `[A]`…`[ZZ]` tokens as clickable tag
chips. The "+" stop picker inserts `[C]` into the input. Users may also type a plain "C"; the
LLM resolves it from the itinerary listing in context.

### 2.6 Session DTOs
```jsonc
// SessionSummary
{ "id": "uuid", "title": "San Jose · Mar 5–7", "status": "planned", "updated_at": "…" }

// SessionDetail
{
  "id": "uuid", "title": "…", "status": "intake",
  "trip_profile": { /* TripProfile */ },
  "messages": [ { "id": "uuid", "role": "assistant", "content": "…", "itinerary_version": null, "created_at": "…" } ],
  "itinerary": null,           // or the latest Itinerary
  "created_at": "…", "updated_at": "…"
}
```

---

## 3. Tag rules (code only: `backend/app/agent/tags.py`)
1. **Version 1:** walk the days in order and the items by `start_time`. Each new stop gets the
   next letter: A … Z, AA, AB …
2. **Same stop = same tag.** Two stops match when their `place_id` is equal, or else when their
   normalized names are equal (lowercase, no punctuation or extra spaces). Example: flying out
   of the arrival airport again reuses `C`.
3. **Version N > 1:** a stop that matches a stop in **any earlier version** of the session keeps
   that tag. New stops get the next letter after the highest letter ever used in the session.
4. Letters of removed stops are **never reused** in the session, so older chat messages that
   mention `[F]` stay unambiguous.

`updated_in_version`: in a new version, an item gets `updated_in_version = N` if no item in
version N−1 has the same `stop_tag` + `kind` + `start_time` + `description`. Otherwise it keeps
the previous item's value.

---

## 4. REST endpoints (prefix `/api`)

| Method | Path | Body | Response | Step |
|---|---|---|---|---|
| GET | `/health` | — | `{ "ok": true, "llm_provider": "fake", "tool_mode": "mock" }` | 2 |
| POST | `/sessions` | — | `SessionDetail` (new, includes the greeting message) | 4 |
| GET | `/sessions/{id}` | — | `SessionDetail` · 404 | 4 |
| POST | `/sessions/{id}/messages` | `{ "content": "1–4000 chars" }` | **SSE** (§5) | 11 |
| POST | `/sessions/{id}/generate` | `{}` | **SSE** (§5) | 23 |
| PATCH | `/sessions/{id}/bookings/{booking_id}` | `{ "status": "todo" \| "booked" }` | updated booking | 42 |
| GET | `/sessions` | — | `SessionSummary[]`, newest `updated_at` first | 44 |
| PATCH | `/sessions/{id}` | `{ "title": "1–80 chars" }` | `SessionSummary` (sets `title_is_custom`) | 44 |
| DELETE | `/sessions/{id}` | — | `204`, cascades | 44 |

Errors are `{ "detail": "message" }` with status 400/404/500, or 422 (invalid body).

---

## 5. SSE events (`text/event-stream`, each with an `event:` name and JSON `data:`)

| event | data | when |
|---|---|---|
| `message_start` | `{ "message_id": "uuid" }` | the assistant message begins |
| `token` | `{ "text": "partial" }` | streamed assistant text |
| `status` | `{ "label": "Checking weather for San Jose · Mar 5–7", "state": "start" \| "end" \| "error" }` | pipeline / tool activity |
| `profile` | `TripProfile` | the profile changed |
| `title` | `{ "title": "San Jose · Mar 5–7" }` | the session got an auto-title |
| `itinerary` | `Itinerary` | a new version was **saved** |
| `error` | `{ "message": "user-friendly text", "retryable": true }` | failure; the stream ends |
| `done` | `{ "message_id": "uuid" }` | complete; the assistant message is saved |

Order: `message_start` comes first and `done` or `error` comes last. If the client aborts
(Stop), the server stops and saves the partial text with " *(stopped)*" appended.
- Chat turn: `message_start → [profile] → token… → done`.
- Making the plan (`/generate`, or a chat turn whose action is `generate`):
  `message_start → [profile] → status… → itinerary → token… → done`. The tokens are a short
  summary; its saved message gets `itinerary_version`. `/generate` saves no user message.
- A failed generation → `status` with `state: "error"`, then `error`; no version is saved.
  A tool status (e.g. weather) may also end in `error` while generation carries on to `done`;
  only the `error` event means the plan failed.
- Tool calls in one planner round run in parallel (D25), so status lines may interleave:
  several `start`s, then their `end`/`error`s in any order. Labels are unique within a turn
  (e.g. "Finding food spots in San Jose"), and a later event for the same label updates that
  line.
- If only the summary fails (the version is already saved), a fixed "plan is ready" line is
  streamed and saved with `itinerary_version`, then `done`.

---

## 6. Deep links (`backend/app/tools/links.py`, built by code, never by the LLM)
URL-encode every parameter.
- Google Flights: `https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{YYYY-MM-DD}%20returning%20{YYYY-MM-DD}`
- Google Hotels: the `link` from SerpApi when present; otherwise `https://www.google.com/travel/hotels?q={hotel name} {city}`
- Booking.com: `https://www.booking.com/searchresults.html?ss={hotel name, city}&checkin={YYYY-MM-DD}&checkout={YYYY-MM-DD}&group_adults={n}`
- Activity tickets: `https://www.google.com/search?q={stop name} {city} tickets`
- Map link for a stop: `https://www.google.com/maps/search/?api=1&query={name}, {address or city}` (a plain link; no Google API key needed)
