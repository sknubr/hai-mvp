from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import feed as feed_module
from app import llm as llm_module
from app import state as state_module
from app.models import (
    DigitalProfile,
    FeedPost,
    PersonaSummary,
    ReactionRequest,
    RunCycleResponse,
    RuntimeState,
    SendMessageRequest,
    SendMessageResponse,
)

STATIC_DIR = Path(__file__).parent / "static"

# Module-level profile cache — loaded at startup, never mutated at runtime
PROFILES: dict[str, DigitalProfile] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global PROFILES
    PROFILES = state_module.load_all_profiles()
    if not PROFILES:
        print("WARNING: No profiles found in profiles/. Run scripts/generate_profiles.py first.")
    else:
        names = ", ".join(p.name for p in PROFILES.values())
        print(f"Loaded {len(PROFILES)} profiles: {names}")
    feed_module.init_csvs()
    yield


app = FastAPI(title="Hai MVP", lifespan=lifespan)


# ─── Static files ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ─── Personas ─────────────────────────────────────────────────────────────────

@app.get("/personas", response_model=list[PersonaSummary])
def list_personas():
    summaries = []
    for profile_id, profile in PROFILES.items():
        s = state_module.load_state(profile_id)
        summaries.append(state_module.get_persona_summary(profile, s))
    return summaries


@app.get("/personas/{persona_id}")
def get_persona(persona_id: str) -> dict[str, Any]:
    profile = _get_profile(persona_id)
    s = state_module.load_state(persona_id)
    return {
        "profile": profile.model_dump(),
        "state": s.model_dump(),
    }


@app.get("/personas/{persona_id}/chat")
def get_chat(persona_id: str) -> list[dict]:
    _get_profile(persona_id)
    s = state_module.load_state(persona_id)
    return [m.model_dump() for m in s.short_buffer]


@app.post("/personas/{persona_id}/message", response_model=SendMessageResponse)
def send_message(persona_id: str, body: SendMessageRequest):
    profile = _get_profile(persona_id)
    s = state_module.load_state(persona_id)

    # Append user message to buffer first
    s = state_module.append_to_buffer(s, "user", body.text)

    # Get persona reply
    reply_text, delay_bucket = llm_module.reply(profile, s, body.text)

    # Append persona reply
    s = state_module.append_to_buffer(s, "persona", reply_text, delay_bucket)

    from datetime import datetime, timezone
    reply_ts = datetime.now(timezone.utc).isoformat()

    return SendMessageResponse(
        reply=reply_text,
        delay_bucket=delay_bucket,
        reply_ts=reply_ts,
    )


@app.post("/personas/{persona_id}/cycle")
def advance_cycle(persona_id: str) -> dict[str, Any]:
    profile = _get_profile(persona_id)
    s = state_module.load_state(persona_id)

    result: RunCycleResponse = llm_module.run_cycle(profile, s)

    # Update runtime state
    from app.models import RecentEvent
    new_events = [RecentEvent(cycle=s.cycle_count + 1, text=e) for e in result.events]
    updated = s.model_copy(update={
        "cycle_count": s.cycle_count + 1,
        "mood": result.mood,
        "journal": result.journal,
        "recent_events": new_events,
    })
    state_module.save_state(updated)

    post_id = None
    if result.post:
        post_id = feed_module.append_post(persona_id, updated.cycle_count, result.post)

    return {
        "cycle_count": updated.cycle_count,
        "events": result.events,
        "mood": result.mood,
        "post": result.post,
        "post_id": post_id,
    }


# ─── Feed ─────────────────────────────────────────────────────────────────────

@app.get("/feed", response_model=list[FeedPost])
def get_all_feed():
    return feed_module.get_feed()


@app.get("/feed/{persona_id}", response_model=list[FeedPost])
def get_persona_feed(persona_id: str):
    _get_profile(persona_id)
    return feed_module.get_feed(persona_id)


# ─── Reactions ────────────────────────────────────────────────────────────────

@app.post("/reactions")
def add_reaction(body: ReactionRequest) -> dict[str, str]:
    reaction_id = feed_module.append_reaction(
        body.post_id, body.persona_id, body.reaction_type, body.reaction_value
    )
    return {"reaction_id": reaction_id}


@app.get("/reactions/{post_id}")
def get_post_reactions(post_id: str) -> list[dict]:
    return feed_module.get_reactions(post_id)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_profile(persona_id: str) -> DigitalProfile:
    if persona_id not in PROFILES:
        raise HTTPException(status_code=404, detail=f"Persona not found: {persona_id}")
    return PROFILES[persona_id]
