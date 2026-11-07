# AGENTS.md — rules for coding agents

This file is for any coding agent (Claude Code, Copilot, Cursor, Codex…) and for humans
working like one. Claude Code loads it through `CLAUDE.md`.

## 1. The project in brief
A chat-driven planner for short trips (2–4 days, 1–2 cities, budget travelers aged 15–35). The
user chats on the right. The plan shows on the left as **Plan** (day cards), **Map** (pins) and
**Book** (what to book). Every stop has a letter tag (A, B, C…), and the user edits by letter in
chat ("replace [F]"). It is a 4-person course project (CSCE 634), so **simple, readable code
beats clever or fast code.**

| Read | When |
|---|---|
| [docs/plan.md](docs/plan.md) | Always: the numbered steps; build only the ones you were given |
| [docs/contracts.md](docs/contracts.md) | **Source of truth** for API, SSE, DB, schemas, tag rules |
| [docs/architecture.md](docs/architecture.md) | Where code goes, how a turn and generation work, external services |
| [docs/spec.md](docs/spec.md) | What a feature should do and look like (UI behaviour) |
| [docs/decisions.md](docs/decisions.md) | Before changing anything that looks "decided" |
| `docs/preview/*.png`, `frontend/` v0 | The visual reference |

## 2. Commands
```bash
# backend (repo root, venv active; otherwise use .venv/Scripts/python on Windows or .venv/bin/python)
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend       # http://localhost:8000/docs
pytest backend/tests                                  # offline; live tests are skipped by default

# frontend
cd frontend && npm install
npm run dev                                           # http://localhost:5173
npm test && npm run lint && npm run build
```
**Full check** = `pytest backend/tests` + `npm test` + `npm run lint` + `npm run build` (skip
the ones that don't exist yet). It must be green before a step counts as done.

## 3. Code style
- Plain functions and small modules. One obvious place for each thing (see the architecture
  layout).
- No premature optimisation: no concurrency, caching or batching unless the step asks for it.
- No new frameworks or dependencies unless the step lists them. If you really need one, stop
  and ask.
- Clear names, short functions, a comment only where the "why" isn't obvious. Type hints in
  Python and strict TypeScript.
- Match the existing style of the file you're in. Don't reformat unrelated code.

## 4. Hard rules
1. **Build only the steps you were given.** Don't start later steps or "improve" unrelated code.
2. **Contracts first.** If you change an API, SSE event or schema, update
   `docs/contracts.md`, `backend/app/schemas/` and `frontend/src/types/` in the same change.
3. **Every step adds tests**, and existing tests stay green. Don't delete or weaken a test to
   make it pass. If a test is wrong, say so in your report.
4. **Tests never use the network:** `LLM_PROVIDER=fake`, `TOOL_PROVIDER_MODE=mock`, recorded
   JSON, a temp DB. Live tests are marked `@pytest.mark.live`.
5. **LLM SDKs only in `backend/app/llm/`.** Tags, coordinates, weather, prices and links come
   from code or tools, never from LLM text.
6. **Frontend components never call `fetch`;** they go through `src/api/`.
7. **Secrets only in git-ignored `.env` files;** keep the `.env.example` files current. No key
   reaches the browser.
8. **Never commit, push or rewrite git history.** Humans commit.
9. New non-trivial decision → add a row to `docs/decisions.md`.

## 5. Workflow for a batch of steps
The human asks for one or more steps (e.g. "build steps 11, 12, 14"). They become **one
commit**.

For **each step, in order**:
1. **Coder:** read the step in `docs/plan.md` and the docs it points to. Implement exactly that
   step. Run the existing tests so nothing old breaks.
2. **Tester:** write the tests the step lists, based on the step's *Tests* and *Done when* (not
   on the implementation). Only touch test files and fixtures. Run the full check. If a failure
   is a code bug, send it back to the coder instead of patching code.
3. If the check is red, the coder fixes it, at most 2 rounds. Still red → stop and report.
4. Mark the step ☑ in `docs/plan.md` and write one short line in its **Notes**.

After **all** the steps:

5. **Reviewer** (fresh eyes, read-only): review the whole uncommitted diff against the steps,
   `docs/contracts.md` and these rules. Return **APPROVE** or **CHANGES** with numbered
   findings marked *blocker* or *minor*, plus notes that belong to later steps.
6. Blockers and cheap minors go back to the coder, then the full check runs again and a fresh
   review follows, at most 2 rounds. Notes for later steps go into those steps' **Notes**.
7. **Final report** to the human. Keep it short:
   - per step: what was built and the tests added;
   - the review verdict and open issues;
   - a suggested commit message.

**Stop early and report** when:
- a check is still red after 2 fix rounds;
- the next step is `[HUMAN]`;
- a step needs a contract change it doesn't describe;
- a new dependency is needed;
- the docs contradict each other or the request is ambiguous.

If the docs are wrong, say so. Don't silently work around them.
