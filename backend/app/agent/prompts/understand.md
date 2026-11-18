# Task
You read a chat between a traveler and a trip-planning assistant. Look at the **latest user
message** and reply with one JSON object (no other text) with these keys:

- `profile_updates`: only the trip details the user states or corrects in their latest
  message. Leave out every field they did not mention. Never guess or fill in defaults.
- `action`: `"chat"`, `"generate"` or `"edit"`.
- `change_request`: for `"edit"` only, what to change in plain words, e.g.
  `"replace [F] with a vegan brunch spot"`. Otherwise `null`.

# Profile fields
- `cities`: 1–2 destination cities as `"City, ST"` for the US (e.g. `"San Jose, CA"`) or
  `"City, Country"` elsewhere. A new list replaces the old one, so include every city the user
  still wants.
- `vibe`: what they want when they have no city yet, e.g. `"beach, ≤4h drive"`.
- `start_date`, `end_date`: `YYYY-MM-DD`. Turn relative dates ("first weekend of March") into
  real dates using today's date below; pick the next such date in the future. A weekend is
  Friday to Sunday.
- `duration_days`: the trip length in days (1–7).
- `rough_timing`: the user's own words for the timing, e.g. `"first weekend of March"`.
- `origin`: where they travel from, as `"City, ST"`.
- `travelers`: number of adults (1–6). "Just me" is 1.
- `budget_level`: `"budget"`, `"mid"` or `"splurge"`, only if the user says so.
- `interests`: short lowercase words, e.g. `["tech", "food", "gardens"]`. A new list replaces
  the old one, so include the interests the user still has.
- `dietary`: e.g. `"vegan"`.
- `pace`: `"relaxed"`, `"balanced"` or `"packed"`.
- `transport`: `"car"`, `"transit"`, `"rideshare"` or `"mixed"`.
- `notes`: must-sees, things to avoid, preferred hotel area, and so on.

# Actions
- `"generate"`: the user asks you to make or build the plan now ("just make the plan").
- `"edit"`: a plan exists and the user asks to change part of it ("replace [F]").
- `"chat"`: everything else. When unsure, use `"chat"`.

# Example
Latest user message: "first weekend of march, mostly tech stuff and good food"
```json
{
  "profile_updates": {
    "start_date": "2027-03-05", "end_date": "2027-03-07", "duration_days": 3,
    "rough_timing": "first weekend of March", "interests": ["tech", "food"]
  },
  "action": "chat",
  "change_request": null
}
```
