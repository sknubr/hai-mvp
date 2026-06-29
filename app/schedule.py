"""
Background scheduler for async (delayed) persona replies.

When a persona "decides" to reply later, the reply is NOT generated up front — a
ScheduledReply job is persisted, and a single asyncio loop (started in main's
lifespan) generates + delivers it when it comes due. This keeps replies reflecting
the persona's state at delivery time and makes the async delay mechanic real.

Imports only state/memory/llm/usage (never main) to avoid an import cycle — main
imports this module.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

from app import llm as llm_module
from app import memory as memory_module
from app import state as state_module
from app import usage as usage_module
from app.models import DigitalProfile, ScheduledReply
from app.state import STATE_DIR, DEFAULT_USER

TICK_SECONDS = 5
MAX_ATTEMPTS = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


# ─── Queue persistence (per user, per persona) ────────────────────────────────

def _queue_path(persona_id: str, user_id: str):
    d = STATE_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"queue-{persona_id}.json"


def load_queue(persona_id: str, user_id: str = DEFAULT_USER) -> list[ScheduledReply]:
    path = _queue_path(persona_id, user_id)
    if not path.exists():
        return []
    import json
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return [ScheduledReply.model_validate(j) for j in raw]


def save_queue(persona_id: str, user_id: str, jobs: list[ScheduledReply]) -> None:
    path = _queue_path(persona_id, user_id)
    tmp = path.with_suffix(".tmp")
    import json
    tmp.write_text(json.dumps([j.model_dump() for j in jobs], indent=2))
    os.replace(tmp, path)


def enqueue(job: ScheduledReply) -> None:
    jobs = load_queue(job.persona_id, job.user_id)
    jobs.append(job)
    save_queue(job.persona_id, job.user_id, jobs)


def all_pending_jobs() -> list[ScheduledReply]:
    """Scan every user's queue files for pending jobs (across all personas)."""
    out: list[ScheduledReply] = []
    if not STATE_DIR.exists():
        return out
    for user_dir in STATE_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        for qf in user_dir.glob("queue-*.json"):
            persona_id = qf.stem[len("queue-"):]
            for job in load_queue(persona_id, user_dir.name):
                if job.status == "pending":
                    out.append(job)
    return out


def _update_job(job: ScheduledReply, **changes) -> None:
    """Patch a single job in its queue file (drop it when delivered)."""
    jobs = load_queue(job.persona_id, job.user_id)
    new_status = changes.get("status")
    kept: list[ScheduledReply] = []
    for j in jobs:
        if j.id == job.id:
            if new_status == "delivered":
                continue  # remove delivered jobs
            kept.append(j.model_copy(update=changes))
        else:
            kept.append(j)
    save_queue(job.persona_id, job.user_id, kept)


# ─── Shared reply generation (used by immediate send AND the scheduler) ────────

def generate_and_store_reply(
    profile: DigitalProfile,
    persona_id: str,
    user_id: str,
    user_message: str,
    delay_bucket: str,
) -> str:
    """Load state, recall+reinforce memory, generate the reply, persist it to the
    short buffer. Returns the reply text. Runs OUTSIDE a request context."""
    s = state_module.load_state(persona_id, user_id)
    store = memory_module.load_store(persona_id, user_id)
    recalled = memory_module.select_relevant(store, user_message, s.cycle_count)
    if recalled:
        store = memory_module.reinforce(store, recalled)
        memory_module.save_store(store, user_id)

    reply_text = llm_module.reply(
        profile, s, user_message, recalled=recalled, short_term_summary=store.short_term_summary
    )
    usage_module.record_call(user_id)
    state_module.append_to_buffer(s, "persona", reply_text, delay_bucket, user_id=user_id)
    return reply_text


def generate_and_store_initiation(
    profile: DigitalProfile,
    persona_id: str,
    user_id: str,
    message: str,
) -> str:
    """Deliver a character-initiated reach-out. The message was already decided by
    the judge+write call in app.initiate (no LLM here) — just persist it as a persona
    message marked initiated_by='character' and notify via the messaging adapter."""
    from app import messaging as messaging_module

    s = state_module.load_state(persona_id, user_id)
    state_module.append_to_buffer(
        s, "persona", message, "immediate", user_id=user_id, initiated_by="character"
    )
    adapter = messaging_module.get_adapter(
        messaging_module.route(persona_id, user_id, "character")
    )
    adapter.deliver(user_id, profile, message, initiated_by="character")
    return message


# ─── The background loop ──────────────────────────────────────────────────────

def _process_due(profiles: dict[str, DigitalProfile]) -> None:
    """Synchronous worker: deliver all due pending jobs once. Called via to_thread."""
    now = _now_iso()
    for job in all_pending_jobs():
        if job.due_ts > now:
            continue
        profile = profiles.get(job.persona_id)
        if profile is None:
            _update_job(job, status="failed", attempts=job.attempts + 1)
            continue
        try:
            if job.kind == "initiation":
                generate_and_store_initiation(
                    profile, job.persona_id, job.user_id, job.message
                )
            else:
                generate_and_store_reply(
                    profile, job.persona_id, job.user_id, job.user_message, job.delay_bucket
                )
                # Reply delivery notifies via the adapter (initiations notify in
                # generate_and_store_initiation).
                try:
                    from app import messaging as messaging_module
                    messaging_module.get_adapter(
                        messaging_module.route(job.persona_id, job.user_id, "user")
                    ).deliver(job.user_id, profile,
                              f"{profile.name} replied", initiated_by="user")
                except Exception:
                    pass
            _update_job(job, status="delivered")
        except Exception as e:  # noqa: BLE001
            attempts = job.attempts + 1
            status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            _update_job(job, status=status, attempts=attempts)
            print(f"[scheduler] delivery error for {job.persona_id} (attempt {attempts}): "
                  f"{str(e)[:120]}")


def _relationships() -> list[tuple[str, str]]:
    """Every (user_id, persona_id) pair that has any history (transcript or queue)."""
    pairs: set[tuple[str, str]] = set()
    if not STATE_DIR.exists():
        return []
    for user_dir in STATE_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        for f in user_dir.glob("transcript-*.json"):
            pairs.add((user_dir.name, f.stem[len("transcript-"):]))
        for f in user_dir.glob("runtime-*.json"):
            pairs.add((user_dir.name, f.stem[len("runtime-"):]))
    return sorted(pairs)


def _consider_initiations(profiles: dict[str, DigitalProfile]) -> None:
    """Sync worker: let each relationship's persona decide whether to reach out.
    Deterministic gates short-circuit before any LLM call. Called via to_thread."""
    from app import initiate as initiate_module
    if not initiate_module._enabled():
        return
    for user_id, persona_id in _relationships():
        profile = profiles.get(persona_id)
        if profile is None:
            continue
        try:
            reached, reason = initiate_module.consider(profile, persona_id, user_id)
            if reached:
                print(f"[initiate] {profile.name} → {user_id}: reaching out ({reason})")
        except Exception as e:  # noqa: BLE001 — one bad relationship can't stop the rest
            print(f"[initiate] error for {persona_id}/{user_id}: {str(e)[:120]}")


# Consider initiations on a coarser cadence than delivery (LLM calls are heavier).
CONSIDER_EVERY_TICKS = 12  # 12 × 5s ≈ every 60s


async def scheduler_loop(profiles: dict[str, DigitalProfile]) -> None:
    """Tick forever, delivering due replies and (less often) considering unprompted
    reach-outs. Past-due jobs left by a restart are delivered on the next tick
    ('catch up'). Run as a single asyncio task."""
    print(f"[scheduler] started (tick={TICK_SECONDS}s)")
    tick = 0
    while True:
        try:
            await asyncio.to_thread(_process_due, profiles)
            if tick % CONSIDER_EVERY_TICKS == 0:
                await asyncio.to_thread(_consider_initiations, profiles)
        except asyncio.CancelledError:
            print("[scheduler] stopped")
            raise
        except Exception as e:  # noqa: BLE001 — never let the loop die
            print(f"[scheduler] tick error: {str(e)[:120]}")
        tick += 1
        await asyncio.sleep(TICK_SECONDS)
