# Developer Setup Guide

How to get the app running locally, and how to create the accounts and keys for the
external services. You can start with **no keys at all** (`LLM_PROVIDER=fake`) — see "Run
modes" and "Which keys each stage needs".

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
python -m app.db.seed                               # Stage 4+, optional: load demo sessions (run from backend/)

# terminal 2 — frontend
cd frontend && npm run dev                          # http://localhost:5173
```

## 4. Run modes (pick based on which keys you have)

Always run both the backend and the frontend; there is no frontend-only mock mode.

| Mode | `backend/.env` | Needs |
|---|---|---|
| **Offline (no keys)** | `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock` | nothing — canned replies and a sample plan |
| **TAMU AI** (Stage 1 default for real use) | `LLM_PROVIDER=openai_compat`, `LLM_BASE_URL=…`, `LLM_MODEL=…`, `LLM_API_KEY=…` | TAMU AI key (§6.2) |
| **Claude** (backup) | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-5-5`, `LLM_API_KEY=…` | Claude Console key (§6.1) |
| **Live tools** (Stage 2+) | any LLM mode + `TOOL_PROVIDER_MODE=live` + Google (+ SerpApi from Stage 3) keys | §6.3, §6.4 |

Quick live check of the LLM settings (after S1.6): `python -m app.llm.smoke` from `backend/`.

### Which keys each stage needs
| Stage | Keys |
|---|---|
| 1 — Talking skeleton | none (fake) or one LLM key (TAMU AI preferred) |
| 2 — Places on the map | + Google: browser key, Map ID, server key (§6.3) |
| 3 — Live tools | + SerpApi (§6.4); Open-Meteo needs no key |
| 4–5 | nothing new |

From Stage 2 the map needs `VITE_GOOGLE_MAPS_API_KEY`; without it the Map tab shows a placeholder.

## 5. Environment variables

### `backend/.env`
| Variable | Example | Required? |
|---|---|---|
| `LLM_PROVIDER` | `fake` (default) \| `openai_compat` \| `anthropic` | yes |
| `LLM_MODEL` | `protected.Claude-Opus-5` (TAMU AI), or `claude-sonnet-5-5` (direct Anthropic) | for real LLM |
| `LLM_FAST_MODEL` | a small/cheap model ID (e.g. `claude-haiku-5-5`) | Stage 4 (titles) |
| `LLM_API_KEY` | `...` | for real LLM |
| `LLM_BASE_URL` | `https://chat-api.tamu.ai/openai` (§6.2) | required for `openai_compat` |
| `TOOL_PROVIDER_MODE` | `mock` \| `live` | from Stage 2 |
| `GOOGLE_MAPS_SERVER_KEY` | `AIza...` | Stage 2+ live place lookups |
| `SERPAPI_KEY` | `...` | Stage 3+ live hotel prices (optional; falls back to no prices) |
| `DATABASE_URL` | `sqlite:///./travel.db` | default is fine |

### `frontend/.env.local`
| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api` |
| `VITE_GOOGLE_MAPS_API_KEY` | `AIza...` (browser key; Stage 2+) |
| `VITE_GOOGLE_MAPS_MAP_ID` | `abc123...` (needed for Advanced Markers; Stage 2+) |

**Never commit `.env` / `.env.local`.** Only `.env.example` files are committed. Share keys
over a private channel (team chat DM), never in the repo, issues, or screenshots.

---

## 6. Accounts & keys

### 6.1 LLM — Anthropic Claude API (backup)
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

### 6.2 LLM — TAMU AI (first choice)
TAMUS AI Chat (https://chat.tamu.ai) is the university's AI platform: NetID login, GPT /
Claude Sonnet / Gemini models, a daily usage allowance. Its API docs are still a work in
progress, so a teammate fills in the blanks below (plan item **H1.2**). Background:
[research/README.md](research/README.md) RQ-2. One TAMU key covers every model TAMU AI
offers, including Claude Sonnet — pick it by model ID. (A direct Anthropic key is a separate,
paid thing — §6.1.)

1. Sign in at https://chat.tamu.ai with your NetID.
2. **Profile icon → Settings → Account → API Keys** → create/copy a key (confirmed location).
3. API host: **`https://chat-api.tamu.ai`** — it answers `401 "Bearer token required"` without
   a key (checked 2026-11-02). Don't use `https://chat.tamu.ai/api`: it redirects to the NetID
   login page, which a backend can't pass. **Base URL: `https://chat-api.tamu.ai/openai`**
   (confirmed with a key, 2026-11-02).
4. Test from PowerShell 7 (the key is typed at a hidden prompt, never saved):
   ```powershell
   $key = Read-Host "TAMU AI key" -MaskInput
   $h = @{ Authorization = "Bearer $key" }
   $base = "https://chat-api.tamu.ai/openai"; $model = "protected.Claude-Opus-5"
   # a) list models
   (Invoke-RestMethod "$base/models" -Headers $h).data | Select-Object id
   # b) one chat message
   $body = @{ model = $model; messages = @(@{ role = "user"; content = "Say hi in five words" }) } | ConvertTo-Json -Depth 5
   (Invoke-RestMethod "$base/chat/completions" -Method Post -Headers $h -ContentType "application/json" -Body $body).choices[0].message.content
   # c) JSON-schema output (needed by "Generate plan")
   $body = @{ model = $model; messages = @(@{ role = "user"; content = "Name one city in Texas." });
     response_format = @{ type = "json_schema"; json_schema = @{ name = "place"; strict = $true; schema = @{
       type = "object"; properties = @{ city = @{ type = "string" }; state = @{ type = "string" } };
       required = @("city", "state"); additionalProperties = $false } } } } | ConvertTo-Json -Depth 10
   try { (Invoke-RestMethod "$base/chat/completions" -Method Post -Headers $h -ContentType "application/json" -Body $body).choices[0].message.content }
   catch { "json_schema -> $($_.Exception.Response.StatusCode): $($_.ErrorDetails.Message)" }
   # d) streaming (should print many "data: {...}" lines, then "data: [DONE]")
   $body = @{ model = $model; stream = $true; messages = @(@{ role = "user"; content = "Count to ten." }) } | ConvertTo-Json -Depth 5
   $body | Set-Content "$env:TEMP\tamu-body.json"
   curl.exe -sN -H "Authorization: Bearer $key" -H "Content-Type: application/json" -d "@$env:TEMP\tamu-body.json" "$base/chat/completions"
   Remove-Item "$env:TEMP\tamu-body.json"
   ```
5. In `backend/.env`: `LLM_PROVIDER=openai_compat`,
   `LLM_BASE_URL=https://chat-api.tamu.ai/openai`, `LLM_MODEL=protected.Claude-Opus-5`,
   `LLM_API_KEY=<key>`.
6. Record here what you found (never the key):

| Item | Value |
|---|---|
| Base URL | `https://chat-api.tamu.ai/openai` (verified 2026-11-02) |
| Model IDs (from `/models`, 2026-11-02) | `protected.Claude-Opus-5` (**default**), `protected.gpt-5.5` (alternative), `protected.Claude Opus 4.1` (ID contains a space — avoid) |
| Streaming works? | **Yes** (test d, 2026-11-02). Quirks: many empty filler chunks, extra `reasoning_content` / `thinking_blocks` fields, and `data: [DONE]` can appear twice — the adapter yields only non-empty `delta.content` and stops at the first `[DONE]`. |
| Non-streaming chat works? | **No usable response** (tests b/c returned no `choices`) — the adapter always uses `stream=True` |
| JSON-schema `response_format` supported? | Unknown (could not test without non-streaming) — S1.6 uses prompt-based JSON + Pydantic validation |
| Prompt-based JSON works? | **Yes** — `python -m app.llm.smoke` with `protected.Claude-Opus-5` streamed a reply and returned a valid `{city, state}` object via the schema-in-system-prompt path (2026-11-02, S1.6) |
| Tool/function calling supported? (needed in Stage 3) | _to fill later_ |
| Daily allowance / rate limits | _to fill_ |

Run step 4 top to bottom in one PowerShell window; `$base` and `$model` must be set before tests b–d.

Sessions created with one provider become read-only after switching (Stage 4 banner); start a new trip.

### 6.3 Google Maps Platform (map, places, geocoding, travel times) — needed from Stage 2
Docs: https://developers.google.com/maps/get-started

One Google Cloud project for the team (plan item **H2.1**). Stage 2 needs Maps JavaScript API
and Places API (New); Geocoding and Routes can be enabled later (Stage 3).

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

### 6.4 SerpApi — hotel prices (Google Hotels) — needed from Stage 3
Docs: https://serpapi.com/google-hotels-api

1. Sign up at https://serpapi.com and choose the **Free** plan (a small number of searches per
   month — check https://serpapi.com/pricing for the current number).
2. Copy the key from https://serpapi.com/manage-api-key → `SERPAPI_KEY`.
3. Quota tips: each generation uses ~1 search per city; results are cached for 6 h in the
   `api_cache` table; use `TOOL_PROVIDER_MODE=mock` when not testing hotels; each teammate
   can use their own free account.
4. No key or quota exhausted → app falls back to Google Places hotels without prices.

### 6.5 Open-Meteo — weather (Stage 3)
Docs: https://open-meteo.com/en/docs

No account or key. Free for non-commercial use with fair rate limits. Data is CC BY 4.0 —
keep the "Weather data by Open-Meteo.com" credit in the UI footer.

### 6.6 MCP servers
None needed for the MVP. Tools are plain Python modules; wrapping them as MCP servers is post-MVP (04-backend-design §11).

---

> Service choices in §6.3–6.5 are pending backend research (RQ-3, RQ-4, RQ-5 in
> [research/README.md](research/README.md)); the researcher updates this guide if they change.

---

## 7. Using the Claude Code agents

Nothing to install beyond Claude Code itself: everything is committed in the repo.
- `CLAUDE.md` imports `AGENTS.md`, so the rules load automatically in every session.
- Subagents: `.claude/agents/` (`backend-researcher`, `frontend-dev`, `backend-dev`,
  `code-reviewer`). Check they're detected with `/agents`.
- Skills: `/implement-task <task-ids>` and `/research <RQ-id>` (`.claude/skills/`).
- Each teammate signs in to Claude Code with their **own** account. This is separate from the
  app's runtime `LLM_API_KEY`.
- Pick and claim an item in `docs/05-implementation-plan.md` (◐ + initials), then
  `/implement-task S1.4` (or `/research RQ-4`). **H** items are done by you, not agents.
- Start every agent task from a clean `git status` on your own branch. Agents don't commit; you do.
- Using Cursor, Codex or Copilot instead? They read `AGENTS.md`; follow the manual prompts in
  [06-agent-workflow.md](06-agent-workflow.md) §6.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Frontend: CORS error | Backend running on :8000? `VITE_API_BASE_URL` correct? CORS origin `http://localhost:5173` in `main.py`. |
| Map is gray / "For development purposes only" | Billing not linked, Maps JavaScript API not enabled, or referrer restriction doesn't match `http://localhost:5173/*`. |
| Markers don't render | `VITE_GOOGLE_MAPS_MAP_ID` missing (Advanced Markers need a Map ID). |
| Places `REQUEST_DENIED` / 403 | Places API (**New**) not enabled, or server key restricted to the wrong APIs. |
| LLM `401` | Wrong/revoked `LLM_API_KEY`; check no stray quotes/spaces in `.env`. |
| LLM `429` | Rate limit (or TAMU AI daily allowance used up); wait and retry, or switch to `LLM_PROVIDER=fake` for UI work. |
| `openai_compat` connection/403 errors | Check `LLM_BASE_URL` (the API host may differ from the chat.tamu.ai web address, which sits behind a NetID login page) and the model ID from `/models`. |
| Hotel prices missing | `SERPAPI_KEY` unset or monthly quota used up (check SerpApi dashboard). |
| Stale demo data | Stop backend, delete `backend/travel.db`, restart, re-run seed. |
