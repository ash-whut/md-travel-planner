# md-travel-planner

A chat-driven AI travel planner for short trips (CSCE 634 IUI course project). You describe
your trip in a chat and get a day-by-day plan in which every stop has a letter. The plan also
shows on a map and as a list of things to book. You edit it by chatting ("replace [F] with
something vegan").

**Status:** the v0 UI (on canned data) is done. We are now building it step by step from
[docs/plan.md](docs/plan.md).

Stack: FastAPI · SQLite (SQLModel) · TAMU AI (OpenAI-compatible) · React + TypeScript + Vite ·
Tailwind · Zustand · Leaflet + OpenStreetMap · Open-Meteo · Geoapify · SerpApi. Every service
is free, and none needs a credit card.

## Docs
| File | What's in it |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules + workflow for coding agents (and for us) |
| [docs/plan.md](docs/plan.md) | **The numbered build steps**, with status. Start here to pick work |
| [docs/spec.md](docs/spec.md) | What we're building: features, UI behaviour, scope |
| [docs/architecture.md](docs/architecture.md) | How the code is organised, how a chat turn becomes a plan, external services |
| [docs/contracts.md](docs/contracts.md) | Source of truth: API, SSE events, DB tables, schemas, tag rules |
| [docs/decisions.md](docs/decisions.md) | Settled decisions (read before changing something big) |
| [docs/preview/](docs/preview/) | Screenshots of the target UI |

---

## How to develop
The code is mostly written by Claude Code agents, one small numbered step at a time. Each step
comes with unit tests, so later work can't silently break earlier work.

1. **Pick work.** Open [docs/plan.md](docs/plan.md) and choose the next open steps (☐). Write
   ◐ + your initials in their headings and push that, or tell the team, so nobody doubles up.
   Steps marked *BE* and *FE* can be split between people.
2. **Branch.** `git checkout main && git pull && git checkout -b <name>/<topic>`, for example
   `hari/chat-sse`.
3. **Build.** Start a **fresh** Claude Code session in the repo root (it reads `CLAUDE.md` →
   `AGENTS.md` automatically). Then run:
   ```
   /build-steps 11 12 14      # or a range: /build-steps 2-4
   ```
   List every step you want in your next commit. For each step, the skill runs:
   - **coder**, which implements it;
   - **tester**, which writes its unit tests and runs the full check (pytest, Vitest, lint,
     build);
   - **reviewer**, once at the end, which reviews the whole diff. Up to 2 automatic fix rounds
     follow.
   It marks the steps ☑ in `docs/plan.md` and ends with a short report and a suggested commit
   message. It stops early at a `[HUMAN]` step or a problem it can't fix.
4. **Check it yourself.** Read the report, skim `git diff`, and try the feature in the browser
   (see "Run" below).
5. **Commit and open a PR.** Agents never commit. You make one commit for the batch, push, and
   open a PR into `main`. A teammate glances at it, then squash-merge.

Tips:
- Use a fresh session (or `/clear`) per batch. It keeps the agents focused and the token use low.
- Keep batches small: 1–5 related steps. A batch that fails halfway is easier to fix.
- `/code-review` (built into Claude Code) gives an optional second opinion before you open the PR.
- `[HUMAN]` steps (keys, the TAMU AI check) are done by a person. Follow "API keys" below.
- If a doc is wrong, fix the doc in the same PR. If you change an API or schema, update
  `docs/contracts.md` in the same PR and tell the team. Frontend and backend both depend on it.
- Not using Claude Code? Follow the same loop by hand from [AGENTS.md](AGENTS.md) §5.

## Team rules
- `main` always runs. Don't push to it directly; work on a branch and open a PR.
- Before a PR: `pytest backend/tests`, then `cd frontend && npm test && npm run lint && npm run build`.
- Shared files need a heads-up before you change them: `docs/contracts.md`,
  `backend/app/schemas/`, `frontend/src/types/`, `frontend/src/api/`, `frontend/src/fixtures/`.
- Never commit `.env`, `.env.local`, keys, or `*.db` (the `.gitignore` handles it; don't
  force-add).

---

## Setup

### Prerequisites
Python 3.11+, Node.js 22+, Git. VS Code with the Python, ESLint and Tailwind CSS IntelliSense
extensions is recommended. Claude Code is optional but is how we build.

### Install
```powershell
# Windows PowerShell (repo root)
python -m venv .venv
.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r backend/requirements.txt
copy backend\.env.example backend\.env
cd frontend; npm install; copy .env.example .env.local
```
```bash
# macOS / Linux / Git Bash
python -m venv .venv
source .venv/bin/activate        # Git Bash on Windows: source .venv/Scripts/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
cd frontend && npm install && cp .env.example .env.local
```
(The backend and the `.env.example` files arrive with plan steps 1–2. Until then, only
`cd frontend && npm install && npm run dev` works, on canned data.)

### Run
```bash
# terminal 1: backend (repo root, venv active)
uvicorn app.main:app --reload --app-dir backend      # API docs: http://localhost:8000/docs
# terminal 2: frontend
cd frontend && npm run dev                           # http://localhost:5173
```
`http://localhost:5173/?demo=1` loads the sample San Jose trip (screenshot mode). The v0 URL
params also work: `?tab=map&day=2`, `?tab=book`, `?why=F`, `?picker=1`, `?history=1`.

### Run modes (set in `backend/.env`)
| Mode | Settings | Needs |
|---|---|---|
| Offline (default) | `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock` | nothing |
| Real LLM, mock tools | `LLM_PROVIDER=openai_compat` + `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | TAMU AI key |
| Everything live | above + `TOOL_PROVIDER_MODE=live` + `GEOAPIFY_KEY` (+ `SERPAPI_KEY` for hotel prices) | free keys |

Tests always run offline, whatever your `.env` says.

### API keys (all free, no card)
Never commit keys or paste them into issues or screenshots. Share them only in private DMs.
Better still, each person makes their own.

| Service | Used for | How to get it | Variable |
|---|---|---|---|
| **TAMU AI** | the LLM | Sign in to TAMU AI with your NetID and create an API key. Base URL `https://chat-api.tamu.ai` (confirm in plan step 10) | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| **Geoapify** | places, addresses, coordinates | Sign up at geoapify.com (free plan) → create a project → API key | `GEOAPIFY_KEY` |
| **SerpApi** | hotel prices (Google Hotels) | Sign up at serpapi.com (free plan, small monthly quota) → dashboard → API key | `SERPAPI_KEY` |
| Open-Meteo | weather + city coordinates | no key | — |
| OpenStreetMap / Nominatim | map tiles, geocoding fallback | no key (light use, keep the attribution) | — |

Use mock mode while you're not working on a tool, to save the free quotas (SerpApi especially).

### Troubleshooting
| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| CORS error in the browser | Is the backend running on :8000? Is `VITE_API_BASE_URL` right in `frontend/.env.local`? |
| LLM `401` / `429` | Wrong key or rate limit. Check `.env` for stray quotes, or switch to `LLM_PROVIDER=fake` |
| Hotel prices missing | `SERPAPI_KEY` unset or the monthly quota is used up. The app falls back to hotels without prices |
| Stale data | Stop the backend, delete `backend/travel.db`, restart |
