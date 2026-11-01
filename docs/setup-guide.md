# Developer Setup Guide

How to get the app running locally, and how to create the accounts and keys for the
external services. You can start with **no keys at all** — see "Run modes".

> Free-tier limits and console menus change. Values below were checked in Nov 2026; if a
> screen looks different, follow the provider's current docs (links included).

---

## 1. Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11+ (3.12 recommended) | `python --version` |
| Node.js | 22 LTS or newer (includes npm) | `node --version` |
| Git | any recent | `git --version` |
| Editor | VS Code + extensions: Python, ESLint, Tailwind CSS IntelliSense | |
| Optional | Claude Code (CLI or VS Code extension) — reads `CLAUDE.md` automatically | |

## 2. Clone and install

```bash
git clone <repo-url> md-travel-planner
cd md-travel-planner
```

**Backend (venv + pip):**
```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r backend/requirements.txt
copy backend\.env.example backend\.env
```
```bash
# macOS / Linux / Git Bash
python -m venv .venv
source .venv/bin/activate            # Git Bash on Windows: source .venv/Scripts/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.example .env.local           # PowerShell: copy .env.example .env.local
```

## 3. Run

```bash
# terminal 1 — backend (repo root, venv active)
uvicorn app.main:app --reload --app-dir backend     # http://localhost:8000/docs
python -m app.db.seed                               # optional: load demo sessions (run from backend/)

# terminal 2 — frontend
cd frontend && npm run dev                          # http://localhost:5173
```

## 4. Run modes (pick based on which keys you have)

| Mode | Settings | Needs |
|---|---|---|
| **UI only** (Phase 1) | `frontend/.env.local`: `VITE_USE_MOCKS=true` | nothing — backend not even running |
| **Full stack, offline** | `VITE_USE_MOCKS=false`; `backend/.env`: `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock` | nothing |
| **Real LLM, mock tools** | `LLM_PROVIDER=anthropic`, `LLM_API_KEY=…`, `TOOL_PROVIDER_MODE=mock` | LLM key |
| **Everything live** | above + `TOOL_PROVIDER_MODE=live` + Google + SerpApi keys | all keys |

The map needs `VITE_GOOGLE_MAPS_API_KEY` in any mode; without it the Map tab shows a placeholder.

## 5. Environment variables

### `backend/.env`
| Variable | Example | Required? |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` \| `fake` \| `openai_compat` | yes |
| `LLM_MODEL` | `claude-opus-5-5` | for real LLM |
| `LLM_FAST_MODEL` | `claude-haiku-5-5` | for real LLM (titles) |
| `LLM_API_KEY` | `sk-ant-...` | for real LLM |
| `LLM_BASE_URL` | empty, or a gateway URL | only for gateways / university endpoint |
| `TOOL_PROVIDER_MODE` | `mock` \| `live` | yes |
| `GOOGLE_MAPS_SERVER_KEY` | `AIza...` | live maps/places |
| `SERPAPI_KEY` | `...` | live hotel prices (optional; falls back to no prices) |
| `DATABASE_URL` | `sqlite:///./travel.db` | default is fine |

### `frontend/.env.local`
| Variable | Example |
|---|---|
| `VITE_USE_MOCKS` | `true` / `false` |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` |
| `VITE_GOOGLE_MAPS_API_KEY` | `AIza...` (browser key) |
| `VITE_GOOGLE_MAPS_MAP_ID` | `abc123...` (needed for Advanced Markers) |

**Never commit `.env` / `.env.local`.** Only `.env.example` files are committed. Share keys
over a private channel (team chat DM), never in the repo, issues, or screenshots.

---

## 6. Accounts & keys

### 6.1 LLM — Anthropic Claude API (current default)
Docs: https://platform.claude.com/docs

1. Go to the **Claude Console** (https://platform.claude.com, formerly console.anthropic.com) and sign up.
2. **Billing:** API usage is billed separately from Claude.ai Pro/Max subscriptions — a
   Claude.ai subscription does **not** include an API key. Add prepaid credits (a few dollars
   is enough for development) and set a **monthly spend limit**.
3. Recommended for the team: one Console organization, a workspace named `travel-planner`
   with a spend limit, invite teammates as members, and **each person creates their own API
   key**. This avoids sharing a personal login and lets you revoke one key without affecting others.
4. **API keys → Create key** → copy into `backend/.env` as `LLM_API_KEY`.
5. Cost control: set `LLM_MODEL=claude-sonnet-5-5` (cheaper) during development, or use
   `LLM_PROVIDER=fake` when you're working on unrelated parts.

> Don't share your personal Claude.ai / Claude Code login credentials with others. Teammates
> using Claude Code as a coding assistant should sign in with their own account; the app's
> runtime key (above) is separate from that.

### 6.2 LLM — University / other provider (later)
If the university provides an LLM API, ask IT / the course staff for:
- Base URL, model names, how to get a key, rate limits, data-retention policy.
- Is it **OpenAI-compatible** (Chat Completions)? Does it support **tool/function calling**
  and **JSON-schema structured output**? Both are required by our agent.

Then implement `backend/app/llm/openai_compat_provider.py` (see 05 §2.2) and set
`LLM_PROVIDER=openai_compat`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`. Sessions created
with one provider become read-only after switching; start a new trip.

### 6.3 Google Maps Platform (map, places, geocoding, travel times)
Docs: https://developers.google.com/maps/get-started

Google requires a billing account (card) even for free usage. Each API has a monthly free
usage cap per SKU that a class project should stay well under; quotas in step 6 guarantee it.
One person can own the project and share keys, or each teammate creates their own.

1. https://console.cloud.google.com → create project `travel-planner`.
2. **Billing** → link a billing account. Then **Billing → Budgets & alerts** → budget of e.g. $1 with email alerts.
3. **APIs & Services → Library** → enable: **Maps JavaScript API**, **Places API (New)**, **Geocoding API**, **Routes API**.
4. **APIs & Services → Credentials → Create credentials → API key**, twice:
   - **Browser key** → Application restrictions: *Websites* → `http://localhost:5173/*` (add the deploy domain later). API restrictions: *Maps JavaScript API* only. → `VITE_GOOGLE_MAPS_API_KEY`.
   - **Server key** → Application restrictions: *None* for local dev (or IP addresses). API restrictions: *Places API (New), Geocoding API, Routes API*. → `GOOGLE_MAPS_SERVER_KEY`.
5. **Google Maps Platform → Map Management → Create Map ID** (type JavaScript) → `VITE_GOOGLE_MAPS_MAP_ID`. Required for the Advanced Markers we use for letter tags.
6. **Quotas:** for each enabled API → *Quotas & System Limits* → lower the requests-per-day limit (e.g. 300/day for Places, Geocoding, Routes; 1,000/day map loads).

### 6.4 SerpApi — hotel prices (Google Hotels)
Docs: https://serpapi.com/google-hotels-api

1. Sign up at https://serpapi.com and choose the **Free** plan (a small number of searches per
   month — check https://serpapi.com/pricing for the current number).
2. Copy the key from https://serpapi.com/manage-api-key → `SERPAPI_KEY`.
3. Quota tips: each generation uses ~1 search per city; results are cached for 6 h in the
   `api_cache` table; use `TOOL_PROVIDER_MODE=mock` when not testing hotels; each teammate
   can use their own free account.
4. No key or quota exhausted → app falls back to Google Places hotels without prices.

### 6.5 Open-Meteo — weather
Docs: https://open-meteo.com/en/docs

No account or key. Free for non-commercial use with fair rate limits. Data is CC BY 4.0 —
keep the "Weather data by Open-Meteo.com" credit in the UI footer.

### 6.6 MCP servers
None needed for the MVP. Tools are plain Python modules; wrapping them as MCP servers is post-MVP (05 §6).

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Frontend: CORS error | Backend running on :8000? `VITE_API_BASE_URL` correct? CORS origin `http://localhost:5173` in `main.py`. |
| Map is gray / "For development purposes only" | Billing not linked, Maps JavaScript API not enabled, or referrer restriction doesn't match `http://localhost:5173/*`. |
| Markers don't render | `VITE_GOOGLE_MAPS_MAP_ID` missing (Advanced Markers need a Map ID). |
| Places `REQUEST_DENIED` / 403 | Places API (**New**) not enabled, or server key restricted to the wrong APIs. |
| LLM `401` | Wrong/revoked `LLM_API_KEY`; check no stray quotes/spaces in `.env`. |
| LLM `429` | Rate limit; wait and retry, or switch to `LLM_PROVIDER=fake` for UI work. |
| Hotel prices missing | `SERPAPI_KEY` unset or monthly quota used up (check SerpApi dashboard). |
| Stale demo data | Stop backend, delete `backend/travel.db`, restart, re-run seed. |
