from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import delays as delays_module
from app import feed as feed_module
from app import llm as llm_module
from app import memory as memory_module
from app import schedule as schedule_module
from app import state as state_module
from app import usage as usage_module
from app.models import (
    BaseSchema,
    DigitalProfile,
    FeedPost,
    OnboardingBlock,
    PersonaSummary,
    ReactionRequest,
    RunCycleResponse,
    RuntimeState,
    ScheduledReply,
    SendMessageRequest,
    SendMessageResponse,
)

STATIC_DIR = Path(__file__).parent / "static"
# empty = no gate (local dev). Normalize: tolerate stray quotes/whitespace/CRLF that
# editors or systemd EnvironmentFile parsing can leave on the value.
ACCESS_CODE = os.getenv("HAI_ACCESS_CODE", "").strip().strip('"').strip("'").strip()

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
    # Background scheduler delivers delayed ("async") persona replies when due.
    # Single asyncio task — run uvicorn with ONE worker so it isn't duplicated.
    import asyncio
    scheduler_task = asyncio.create_task(schedule_module.scheduler_loop(PROFILES))
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Hai MVP", lifespan=lifespan)


# ─── Per-user identity dependency ─────────────────────────────────────────────

def current_user(x_hai_user: str | None = Header(default=None)) -> str:
    """Resolve the per-user namespace from the X-Hai-User header (client uuid)."""
    if not x_hai_user or len(x_hai_user) < 8:
        raise HTTPException(status_code=400, detail="Missing or invalid user identity.")
    # Keep it filesystem-safe.
    return "".join(c for c in x_hai_user if c.isalnum() or c in "-_")[:64]


class GateRequest(BaseModel):
    code: str
    display_name: str = ""


@app.post("/gate")
def gate(body: GateRequest, user_id: str = Depends(current_user)) -> dict[str, bool]:
    """Validate the shared access passphrase and register the tester's display name."""
    if ACCESS_CODE and body.code.strip() != ACCESS_CODE:
        raise HTTPException(status_code=403, detail="Wrong access code.")
    feed_module.init_csvs(user_id)
    if body.display_name.strip():
        state_module.set_display_name(user_id, body.display_name.strip()[:60])
    return {"ok": True}


@app.get("/gate/required")
def gate_required() -> dict[str, bool]:
    return {"required": bool(ACCESS_CODE)}


# ─── Static files ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ─── Personas ─────────────────────────────────────────────────────────────────

@app.get("/personas", response_model=list[PersonaSummary])
def list_personas(user_id: str = Depends(current_user)):
    summaries = []
    for profile_id, profile in PROFILES.items():
        s = state_module.load_state(profile_id, user_id)
        summaries.append(state_module.get_persona_summary(profile, s))
    return summaries


@app.post("/personas/create")
def create_persona(onboarding: OnboardingBlock, user_id: str = Depends(current_user)) -> dict[str, Any]:
    """Generate a new persona from a user's onboarding answers and register it."""
    import json as _json
    from datetime import datetime, timezone

    _check_quota(user_id)
    onboarding_json = _json.dumps(onboarding.model_dump(mode="json"), indent=2)
    data = llm_module.generate_onboarding(onboarding_json)
    usage_module.record_call(user_id)

    name = str(data.get("name") or "").strip() or "Unnamed"
    profile_id = state_module.next_profile_id(name, PROFILES)
    profile = DigitalProfile(
        profile_id=profile_id,
        name=name,
        onboarding=onboarding,
        base_schema=BaseSchema.model_validate(data["base_schema"]),
        created_by=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    state_module.save_generated_profile(profile)
    PROFILES[profile_id] = profile  # make it immediately available

    return {"profile_id": profile_id, "name": name}


@app.get("/personas/{persona_id}")
def get_persona(persona_id: str, user_id: str = Depends(current_user)) -> dict[str, Any]:
    profile = _get_profile(persona_id)
    s = state_module.load_state(persona_id, user_id)
    return {
        "profile": profile.model_dump(),
        "state": s.model_dump(),
    }


@app.get("/personas/{persona_id}/chat")
def get_chat(persona_id: str, user_id: str = Depends(current_user)) -> list[dict]:
    """Full conversation history (last ~200). Falls back to the working buffer for
    users created before transcripts existed."""
    _get_profile(persona_id)
    transcript = state_module.load_transcript(persona_id, user_id)
    if not transcript:
        s = state_module.load_state(persona_id, user_id)
        transcript = s.short_buffer
    return [m.model_dump() for m in transcript[-200:]]


@app.get("/inbox")
def get_inbox(user_id: str = Depends(current_user)) -> list[dict[str, Any]]:
    """Per-persona delivery status for client polling: the timestamp of the latest
    persona message + whether a delayed reply is pending and when it's due. Lets the
    UI surface freshly-delivered async replies and notify across personas."""
    out: list[dict[str, Any]] = []
    for persona_id in PROFILES:
        s = state_module.load_state(persona_id, user_id)
        last_persona_ts = ""
        last_persona_text = ""
        last_initiated_by = "user"
        for m in reversed(s.short_buffer):
            if m.role == "persona":
                last_persona_ts = m.ts
                last_persona_text = m.text[:140]
                last_initiated_by = m.initiated_by
                break
        pending = [j for j in schedule_module.load_queue(persona_id, user_id) if j.status == "pending"]
        next_due = min((j.due_ts for j in pending), default="")
        out.append({
            "persona_id": persona_id,
            "name": PROFILES[persona_id].name,
            "last_persona_ts": last_persona_ts,
            "last_persona_text": last_persona_text,
            "last_initiated_by": last_initiated_by,
            "pending": bool(pending),
            "next_due_ts": next_due,
        })
    return out


@app.get("/personas/{persona_id}/inner")
def get_inner_world(persona_id: str, user_id: str = Depends(current_user)) -> dict[str, Any]:
    """Trimmed, display-ready view of the persona's evolving inner state."""
    _get_profile(persona_id)
    s = state_module.load_state(persona_id, user_id)
    store = memory_module.load_store(persona_id, user_id)
    # Top memory items per tier, salience-ranked (for the inner-world drawer).
    by_tier: dict[str, list[dict]] = {"working": [], "short_term": [], "long_term": []}
    for m in sorted(store.items, key=lambda m: m.salience, reverse=True):
        by_tier.setdefault(m.tier, []).append({
            "content": m.content, "salience": m.salience, "tag": m.tag,
            "source": m.source, "reinforce_count": m.reinforce_count,
        })
    return {
        "cycle_count": s.cycle_count,
        "mood": s.mood,
        "mood_history": [m.model_dump() for m in s.mood_history[-7:]],
        "preoccupations": s.preoccupations,
        "open_threads": [t.model_dump() for t in s.open_threads if t.status == "open"],
        "journal": s.journal,
        "short_term_summary": store.short_term_summary,
        "memory_counts": memory_module.tier_counts(store),
        "memory_by_tier": by_tier,
    }


@app.post("/personas/{persona_id}/message", response_model=SendMessageResponse)
def send_message(persona_id: str, body: SendMessageRequest, user_id: str = Depends(current_user)):
    profile = _get_profile(persona_id)
    _check_quota(user_id)
    s = state_module.load_state(persona_id, user_id)

    # Append user message to buffer first (shows immediately in the chat).
    s = state_module.append_to_buffer(s, "user", body.text, user_id=user_id)

    # How long does the persona take to reply this time?
    bucket = delays_module.pick_delay_bucket()

    from datetime import datetime, timezone

    if bucket == "immediate":
        # Synchronous path — generate and return the reply now.
        reply_text = schedule_module.generate_and_store_reply(
            profile, persona_id, user_id, body.text, bucket
        )
        return SendMessageResponse(
            status="delivered",
            reply=reply_text,
            delay_bucket=bucket,
            reply_ts=datetime.now(timezone.utc).isoformat(),
        )

    # Delayed path — enqueue; the scheduler generates + delivers it when due.
    due = delays_module.due_ts(bucket)
    schedule_module.enqueue(ScheduledReply(
        id=schedule_module.new_id(),
        persona_id=persona_id,
        user_id=user_id,
        user_message=body.text,
        delay_bucket=bucket,
        created_ts=datetime.now(timezone.utc).isoformat(),
        due_ts=due,
    ))
    return SendMessageResponse(
        status="scheduled",
        delay_bucket=bucket,
        due_ts=due,
    )


@app.post("/personas/{persona_id}/cycle")
def advance_cycle(persona_id: str, user_id: str = Depends(current_user)) -> dict[str, Any]:
    profile = _get_profile(persona_id)
    _check_quota(user_id)
    s = state_module.load_state(persona_id, user_id)
    store = memory_module.load_store(persona_id, user_id)

    result: RunCycleResponse = llm_module.run_cycle(profile, s, store)
    usage_module.record_call(user_id)
    new_cycle = s.cycle_count + 1

    # Stamp every event/thread with this cycle (the model may omit/guess it).
    for e in result.events:
        e.cycle = new_cycle
    for t in result.open_threads:
        if not t.cycle_added:
            t.cycle_added = new_cycle

    # Update runtime state (mood/journal/preoccupations/threads). event_log and
    # user_memory are deprecated — memory now lives in the unified store.
    updated = s.model_copy(update={
        "cycle_count": new_cycle,
        "mood": result.mood,
        "journal": result.journal,
    })
    updated = state_module.append_mood(updated, new_cycle, result.mood)
    updated = state_module.set_preoccupations(updated, result.preoccupations)
    updated = state_module.set_open_threads(updated, result.open_threads)
    state_module.save_state(updated, user_id)

    # Consolidate memory ("sleep"). Bridge from events/facts if the model used the
    # older output shape so the store still populates.
    from app.models import MemoryDraft
    new_drafts = list(result.new_memories)
    if not new_drafts:
        new_drafts = [
            MemoryDraft(content=e.text, salience=min(100, e.salience * 20),
                        tag="observed", source="external_event")
            for e in result.events if e.salience >= 4
        ] + [
            MemoryDraft(content=f.text, salience=min(100, f.salience * 20),
                        tag="verified", source="conversation")
            for f in result.salient_user_facts
        ]
    store = memory_module.consolidate(
        store, new_drafts, list(result.consolidated_memory),
        result.short_term_summary, new_cycle,
    )
    memory_module.save_store(store, user_id)

    post_id = None
    if result.post:
        post_id = feed_module.append_post(persona_id, updated.cycle_count, result.post, user_id)

    return {
        "cycle_count": updated.cycle_count,
        "events": [e.text for e in result.events],
        "mood": result.mood,
        "preoccupations": result.preoccupations,
        "new_memories": [d.content for d in new_drafts],
        "memory_counts": memory_module.tier_counts(store),
        "post": result.post,
        "post_id": post_id,
    }


# ─── Feed ─────────────────────────────────────────────────────────────────────

@app.get("/feed", response_model=list[FeedPost])
def get_all_feed(user_id: str = Depends(current_user)):
    return feed_module.get_feed(user_id=user_id)


@app.get("/feed/{persona_id}", response_model=list[FeedPost])
def get_persona_feed(persona_id: str, user_id: str = Depends(current_user)):
    _get_profile(persona_id)
    return feed_module.get_feed(persona_id, user_id=user_id)


# ─── Reactions ────────────────────────────────────────────────────────────────

@app.post("/reactions")
def add_reaction(body: ReactionRequest, user_id: str = Depends(current_user)) -> dict[str, str]:
    reaction_id = feed_module.append_reaction(
        body.post_id, body.persona_id, body.reaction_type, body.reaction_value, user_id
    )
    return {"reaction_id": reaction_id}


@app.get("/reactions/{post_id}")
def get_post_reactions(post_id: str, user_id: str = Depends(current_user)) -> list[dict]:
    return feed_module.get_reactions(post_id, user_id)


# ─── Feedback (Milestone B) ───────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    persona_id: str
    kind: str                 # "reply" | "session"
    target_ref: str = ""      # e.g. the reply text snippet being rated
    rating: str = ""          # "up" | "down" | ""
    signal_tag: str = ""      # "alive" | "consistent" | "stale" | ""
    comment: str = ""


@app.post("/feedback")
def add_feedback(body: FeedbackRequest, user_id: str = Depends(current_user)) -> dict[str, str]:
    fid = feed_module.append_feedback(
        user_id, body.persona_id, body.kind, body.target_ref,
        body.rating, body.signal_tag, body.comment,
    )
    return {"feedback_id": fid}


@app.get("/admin/feedback")
def export_feedback(code: str = "") -> Any:
    """All testers' feedback, gated by the access code (for collecting results)."""
    if not ACCESS_CODE or code != ACCESS_CODE:
        raise HTTPException(status_code=403, detail="Forbidden.")
    rows = feed_module.all_feedback()
    # Attach display names.
    names = {uid: state_module.get_display_name(uid) for uid in {r["user_id"] for r in rows}}
    for r in rows:
        r["display_name"] = names.get(r["user_id"], r["user_id"])
    return rows


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_profile(persona_id: str) -> DigitalProfile:
    if persona_id not in PROFILES:
        raise HTTPException(status_code=404, detail=f"Persona not found: {persona_id}")
    return PROFILES[persona_id]


def _check_quota(user_id: str) -> None:
    if not usage_module.under_cap(user_id):
        raise HTTPException(
            status_code=429,
            detail="You've reached today's usage limit for this shared preview. "
                   "Please try again tomorrow.",
        )
