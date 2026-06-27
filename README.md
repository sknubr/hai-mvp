# hai-mvp

An AI-companion MVP: pre-generated personas that feel alive over time — they message,
accumulate a simulated daily life, evolve their preoccupations and memory, remember the
people they talk to, and post to a feed. Built to validate the **agent loop** (does a
persona feel alive, consistent, and continuous?) before any polished app investment.

## Architecture (quick map)

- `profiles/` — 4 committed, **read-only** digital profiles (Nadia, Sol, Remy, Theo).
- `app/models.py` — Pydantic models incl. layered memory (`event_log`, `user_memory`,
  `open_threads`, `preoccupations`, `mood_history`).
- `app/llm.py` — pluggable provider (Google / Anthropic) with retry + **multi-model
  fallback chain**.
- `app/prompts.py` — pure prompt builders for `reply` and the consolidating `runCycle`.
- `app/state.py` / `app/feed.py` / `app/usage.py` — **per-user** state, feed/feedback,
  and a soft daily call cap. All namespaced by `user_id`.
- `app/main.py` — FastAPI server; `app/static/index.html` — single-page UI (chat,
  feed, inner-world drawer, feedback, access gate).

All persona evolution lives in per-user `RuntimeState`; profiles are never mutated.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add GOOGLE_API_KEY (or use Anthropic)
# Profiles are committed; regenerate only if needed:
#   python scripts/generate_profiles.py
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
```

Locally there's no access gate (leave `HAI_ACCESS_CODE` unset) and a single `local` user.

### Validate the loop without the server
```bash
python scripts/test_state.py                                   # memory model / state I/O
python scripts/test_cycle.py --persona digital-profile-nadia+001 --cycles 5   # evolution
python scripts/test_reply.py --persona digital-profile-nadia+001              # chat
```

## Configuration (env)

| Var | Purpose |
|---|---|
| `LLM_PROVIDER` | `google` (default) or `anthropic` |
| `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` | provider key |
| `GOOGLE_MODEL` | primary model (default `gemini-3.1-flash-lite`) |
| `GOOGLE_MODEL_FALLBACKS` | comma-list rolled to on transient 429s |
| `HAI_ACCESS_CODE` | shared passphrase gating the hosted preview (unset = no gate) |
| `HAI_DAILY_CALL_CAP` | per-user/day LLM-call cap (default 80; 0 = unlimited) |

## Hosted preview (for ~5 testers)

The app is multi-user: each browser gets a private `user_id` (localStorage, sent as
`X-Hai-User`), so testers never share persona memories. A shared `HAI_ACCESS_CODE`
gates entry; the per-user daily cap protects the shared key.

**Deploy on Render (simplest):**
1. Push this repo to GitHub.
2. Render → New → **Blueprint** → select the repo (uses `render.yaml`).
3. Set secrets in the dashboard: `GOOGLE_API_KEY`, `HAI_ACCESS_CODE`.
4. Deploy.

**Persistence switch (in `render.yaml`):**
- **Default = free tier, no disk.** Per-user state is ephemeral — it resets on every
  redeploy/restart, and the instance sleeps after ~15 min idle. Good for solo testing.
- **For the real tester round**, turn on persistence: set `plan: starter`, uncomment the
  `disk:` block, push (or re-sync the Blueprint). State at `/app/data` then survives
  redeploys. (Disks require a paid instance.)

**Any Docker host (Fly.io, etc.):** build the `Dockerfile`, mount a volume at
`/app/data`, and set the same env vars. Run command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

**Give testers:** the URL + the access code. Tell them their chats are stored privately
on the host (only the LLM provider sees message content).

**Collect feedback:** `GET /admin/feedback?code=<HAI_ACCESS_CODE>` returns every
tester's per-reply 👍/👎 and per-persona signal tags (alive / consistent / stale) + notes.

## Status

- Agent loop (memory, consolidating cycles, continuity, inner-world view): **done**.
- Multi-user + feedback + guardrails + hosting: **done** (this round).
- Deferred: full app experience (onboarding/persona creation, polish), reaction-driven
  evolution, after feedback is in.
