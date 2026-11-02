# 03 — Contracts (API, Data Model, Schemas)

**This file is the source of truth.** Backend Pydantic models (`backend/app/schemas/`) and
frontend TypeScript types (`frontend/src/types/`) mirror it. Change this file first, in the
same PR as the code change.

**Stages:** the MVP is built in stages ([05-implementation-plan.md](05-implementation-plan.md)).
The REST and SSE tables below have a **Stage** column saying when each piece first exists.
Fields that are filled only from a later stage are nullable and are `null` before then.

> **CONTRACT CHANGE (2026-11-02, staged MVP):** `places[].lat/lng/address/place_id/rating` and
> `lodging[].lat/lng/address/place_id/rating` are now **nullable** — Stage 1 has no place
> lookups (filled from Stage 2). `days[].weather` and `weather_summary` may be `null` (until
> Stage 3). Frontend impact: render "not on map" / hide weather and transit when null.

Conventions: JSON uses `snake_case`. IDs are UUID4 strings. Timestamps are ISO-8601 UTC
(`2026-11-01T18:04:05Z`). Dates are `YYYY-MM-DD`; times are local `HH:MM` (24h; the UI
formats as 12h). Money is `{ "amount": number, "currency": "USD" }`.
**Units are imperial:** temperatures °F, distances miles, precipitation inches.

---

## 1. Database tables (SQLModel / SQLite)

### `session`
| column | type | notes |
|---|---|---|
| id | str (uuid) PK | |
| title | str | default `"New trip"` |
| title_is_custom | bool | true once the user renames → stop auto-titling |
| status | str | `intake` \| `planned` |
| trip_profile | JSON | `TripProfile` |
| llm_provider | str | provider that owns `agent_transcript` (e.g. `anthropic`, `fake`) |
| agent_transcript | JSON | provider-native message list (incl. tool calls/results, thinking blocks). **Append-only.** Never sent to the UI. If the configured provider differs from `llm_provider`, the session is read-only for chat and the UI suggests a new trip. |
| created_at / updated_at | datetime | `updated_at` bumps on each message → history order |

### `message` (display messages)
| column | type | notes |
|---|---|---|
| id | str PK | |
| session_id | FK → session.id, cascade delete | |
| role | str | `user` \| `assistant` |
| content | text | markdown |
| itinerary_version | int \| null | set on the assistant message that produced a new version |
| created_at | datetime | |

### `itinerary`
| column | type | notes |
|---|---|---|
| id | str PK | |
| session_id | FK, cascade delete | |
| version | int | 1, 2, 3… per session |
| data | JSON | full `Itinerary` |
| created_at | datetime | |

### `api_cache`
| column | type | notes |
|---|---|---|
| key | str PK | `"{tool}:{sha256 of normalized args}"` |
| value | JSON | raw/normalized provider response |
| created_at | datetime | |
| ttl_seconds | int | weather 3h, places 7d, hotels 6h |

Persisting the cache matters because free tiers (especially hotel pricing) have small
monthly quotas.

Checklist checkbox state lives in the latest `itinerary.data.checklist[].status` (PATCHed
in place). On regeneration, carry over `status` for checklist items whose `id` still exists.

---

## 2. Schemas

### 2.1 `TripProfile`
All fields optional; `missing_required` computed server-side.
```jsonc
{
  "cities": ["Austin"],                       // 0–2 entries
  "vibe": null,                               // when user wants suggestions: "beach, ≤4h drive"
  "start_date": "2027-03-06", "end_date": "2027-03-08",
  "duration_days": 3,                          // 1–7
  "rough_timing": null,                        // "a weekend in March" before exact dates are known
  "origin": "College Station, TX",
  "travelers": 3,                              // adults, 1–6
  "budget_level": "budget",                    // budget | mid | splurge  (default budget)
  "interests": ["food", "live music"],
  "pace": "balanced",                          // relaxed | balanced | packed
  "transport": "car",                          // car | transit | walk | mixed
  "must_see": [], "avoid": [], "dietary": null, "hotel_area": null,
  "notes": null,
  "missing_required": []                       // subset of: destination, dates, origin, travelers, interests
}
```

### 2.2 `Itinerary`
Places are stored once in `places` and referenced by `place_tag` from items.
```jsonc
{
  "id": "uuid", "version": 2,
  "title": "Austin — Tacos, Music & Hills",
  "summary": "One-paragraph overview.",
  "start_date": "2027-03-06", "end_date": "2027-03-08",
  "travelers": 3,
  "cities": [ { "name": "Austin", "region": "TX", "country": "USA", "lat": 30.2672, "lng": -97.7431 } ],
  "cost_estimate": {                                   // per person
    "currency": "USD", "low": 280, "high": 390,
    "breakdown": [ { "category": "lodging", "low": 120, "high": 120 } ]   // lodging|food|activities|local_transport|other (flights excluded)
  },
  "weather_summary": "Sunny and mild, 52–74 °F.",      // null until Stage 3
  "assumptions": ["Budget level assumed since none was given."],

  "places": [
    {
      "tag": "A",                                      // A..Z, AA.. ; stable across versions
      "name": "Franklin Barbecue",
      "address": "900 E 11th St, Austin, TX",          // null if unknown
      "lat": 30.2701, "lng": -97.7312,                 // null until found (Stage 2+)
      "place_id": "ChIJ…",                             // provider id; null if none
      "category": "food",                              // food|sight|nature|nightlife|shopping|museum|activity|transport_hub|other
      "rating": 4.7,                                   // null if unknown
      "maps_url": "https://www.google.com/maps/search/?api=1&query=…"
    }
  ],

  "lodging": [
    {
      "tag": "H1",                                     // H1, H2
      "name": "Example Inn Downtown", "city": "Austin",
      "address": "…", "lat": 30.26, "lng": -97.74, "place_id": "…",   // each null until found (Stage 2+)
      "check_in": "2027-03-06", "check_out": "2027-03-08", "nights": 2,
      "rating": 4.1,
      "price_per_night": { "amount": 89, "currency": "USD" },   // null if no pricing source
      "total_price":     { "amount": 178, "currency": "USD" },  // whole stay, whole room
      "price_as_of": "2026-11-01T18:04:05Z",           // null when price_source is "none"
      "price_source": "serpapi_google_hotels",         // serpapi_google_hotels | none
      "alternatives": [ { "name": "…", "total_price": { "amount": 199, "currency": "USD" }, "rating": 4.3, "link": "https://…" } ],
      "links": [ { "label": "Google Hotels", "url": "https://…" }, { "label": "Booking.com", "url": "https://…" } ]
    }
  ],

  "days": [
    {
      "day_number": 1, "date": "2027-03-06", "title": "Arrival, East Side eats",
      "city": "Austin",
      "lodging_tag": "H1",
      "weather": { "high_f": 72, "low_f": 51, "condition": "sunny", "precip_chance": 10, "source": "forecast" },  // forecast|climate|unavailable; whole object null until Stage 3
      "items": [
        {
          "id": "d1-i1",
          "kind": "meal",                              // activity|meal|transit|lodging|free_time
          "title": "Lunch at Franklin Barbecue",
          "description": "Short, concrete description.",
          "start_time": "11:00", "end_time": "12:30",
          "place_tag": "A",                            // or "H1" for lodging items, or null (free_time / generic)
          "est_cost": { "amount": 25, "currency": "USD" },   // per person; null if unknown
          "booking_required": false,
          "checklist_item_id": null,
          "transit_from_previous": { "mode": "drive", "duration_min": 12, "distance_mi": 3.4 },  // null for first item; mode: walk|transit|drive|rideshare|flight|train
          "tips": "Line forms early; arrive by 10:30."
        }
      ]
    }
  ],

  "checklist": [
    {
      "id": "chk-lodging-H1",
      "category": "lodging",                           // flights|lodging|activities|local_transport|documents|packing
      "title": "Book Example Inn Downtown (H1)",
      "details": "2 nights, Mar 6–8. $178 total as of Nov 1, 6:04 PM.",
      "date": "2027-03-06",
      "recommended_option": "Example Inn Downtown — $89/night",
      "links": [ { "label": "Booking.com", "url": "https://…" } ],
      "bookable_by_us": true,                          // "Book for me" → coming soon (MVP)
      "status": "todo"                                 // todo|done
    }
  ],
  "created_at": "2026-11-01T18:04:05Z"
}
```

**Tag rules (assigned by backend code, never by the LLM):**
1. Version 1: walk days in order, items by `start_time`; each new place (matched by
   `place_id`, else normalized name + coords within ~50 m) gets the next letter A, B, …, Z, AA, AB …
2. Version N > 1: a place already tagged in **any earlier version of this session** keeps its
   tag. New places get the next letter after the highest letter ever used in the session.
   Retired letters are never reused.
3. Lodging tags are `H1`, `H2` in order of check-in; same matching rule.

**Validation rules (Pydantic, after the model returns):**
- 1–7 days; `days` count = `end_date − start_date + 1`; `day_number` contiguous; dates match.
- ≤ 2 cities; ≤ 2 lodging entries.
- Items sorted by `start_time` within a day; every `place_tag`, `lodging_tag`, `checklist_item_id` resolves.
- Every `booking_required: true` item has a checklist item.
- Lat/lng valid. Unknown values are `null`, never invented placeholders.

### 2.3 Session DTOs
```jsonc
// SessionSummary
{ "id": "uuid", "title": "Austin · Mar 6–8", "status": "planned", "updated_at": "…" }

// SessionDetail
{
  "id": "uuid", "title": "…", "status": "intake", "trip_profile": { /* TripProfile */ },
  "messages": [ { "id": "uuid", "role": "user", "content": "…", "itinerary_version": null, "created_at": "…" } ],
  "itinerary": null,             // or latest Itinerary
  "chat_enabled": true,          // false if session belongs to a different LLM provider
  "created_at": "…", "updated_at": "…"
}
```

---

## 3. REST endpoints (prefix `/api`)

| Method | Path | Body | Response | Stage |
|---|---|---|---|---|
| GET | `/sessions` | — | `SessionSummary[]` by `updated_at` desc | 4 |
| POST | `/sessions` | — | `SessionDetail` (new; includes greeting message) | 1 |
| GET | `/sessions/{id}` | — | `SessionDetail` · 404 | 1 |
| PATCH | `/sessions/{id}` | `{ "title": "1–80 chars" }` | `SessionSummary` (sets `title_is_custom`) | 4 |
| DELETE | `/sessions/{id}` | — | `204` (cascade) | 4 |
| POST | `/sessions/{id}/messages` | `{ "content": "1–4000 chars" }` | **SSE** (§4) | 1 |
| POST | `/sessions/{id}/generate` | `{}` | **SSE** (§4) | 1 |
| PATCH | `/sessions/{id}/checklist/{item_id}` | `{ "status": "todo" \| "done" }` | updated item | 3 |
| GET | `/health` | — | `{ "ok": true, "llm_provider": "fake", "tool_mode": "mock" }` | 1 |

Errors: `{ "detail": "message" }` with 400/404/409/500. A second stream on a session that is
already streaming → `409` (Stage 3; before that there is no lock).

---

## 4. SSE event stream

`text/event-stream`; each event has an `event:` name and JSON `data:`.

| event | data | when | Stage |
|---|---|---|---|
| `message_start` | `{ "message_id": "uuid" }` | assistant message begins | 1 |
| `token` | `{ "text": "partial" }` | streamed assistant text | 1 |
| `status` | `{ "label": "Finding cheap hotels in Austin…", "tool": "search_hotels", "state": "start" \| "end" \| "error" }` | tool activity / phases (`tool` may be `null` for phases like "Drafting your itinerary…") | 1 |
| `profile` | `TripProfile` | trip profile changed | 3 |
| `title` | `{ "title": "Austin · Mar 6–8" }` | session auto-titled | 4 |
| `itinerary` | `Itinerary` | new version persisted | 1 |
| `error` | `{ "message": "user-friendly text", "retryable": true }` | failure; stream ends | 1 |
| `done` | `{ "message_id": "uuid" }` | complete; assistant message persisted | 1 |

Order: `message_start` first; `done` or `error` last; `itinerary` only after it's persisted.
Client abort (Stage 3) → server stops the LLM call and saves partial text with "*(stopped)*".
Before Stage 3 an aborted stream saves nothing partial.

---

## 5. Deep-link formats (`tools/links.py`, deterministic)

Built in code, never by the LLM. URL-encode params. Verify formats at implementation time.
- Google Flights: `https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{date}%20returning%20{date}`
- Skyscanner: `https://www.skyscanner.com/transport/flights/{origin_iata}/{dest_iata}/{yymmdd}/{yymmdd}/` (omit if IATA unknown)
- Google Hotels: use the `link` returned by SerpApi when present; else `https://www.google.com/travel/hotels?q={hotel name city}`
- Booking.com: `https://www.booking.com/searchresults.html?ss={hotel name, city}&checkin={YYYY-MM-DD}&checkout={YYYY-MM-DD}&group_adults={n}`
- Google Maps place: `https://www.google.com/maps/search/?api=1&query={name}&query_place_id={place_id}`
