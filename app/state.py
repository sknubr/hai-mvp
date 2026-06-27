"""
Load/save runtime state and digital profiles.
All file I/O is here; the rest of the app imports from this module.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    DELAY_BUCKETS,
    BufferMessage,
    DelayBucket,
    DigitalProfile,
    EventEntry,
    MemoryItem,
    MoodEntry,
    PersonaSummary,
    RuntimeState,
    ThreadItem,
)

PROFILES_DIR = Path(__file__).parent.parent / "profiles"            # built-in, committed, read-only
GENERATED_DIR = Path(__file__).parent.parent / "data" / "personas"  # user-generated (writable/persistent)
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
SHORT_BUFFER_SIZE = 15
EVENT_LOG_CAP = 40          # older episodic life rolls up into the journal
USER_MEMORY_CAP = 30        # long-term memory of the user, salience-ranked
MOOD_HISTORY_CAP = 60


# ─── Profiles (read-only) ─────────────────────────────────────────────────────

def load_profile(persona_id: str) -> DigitalProfile:
    path = PROFILES_DIR / f"{persona_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    return DigitalProfile.model_validate_json(path.read_text())


def load_all_profiles() -> dict[str, DigitalProfile]:
    profiles: dict[str, DigitalProfile] = {}
    for d in (PROFILES_DIR, GENERATED_DIR):
        if not d.exists():
            continue
        for p in sorted(d.glob("digital-profile-*.json")):
            profile = DigitalProfile.model_validate_json(p.read_text())
            profiles[profile.profile_id] = profile
    return profiles


def next_profile_id(name: str, existing: dict[str, DigitalProfile]) -> str:
    """digital-profile-{slug}+{NNN} with an incrementing, zero-padded id."""
    max_id = 0
    for pid in existing:
        if "+" in pid:
            try:
                max_id = max(max_id, int(pid.rsplit("+", 1)[1]))
            except ValueError:
                pass
    slug = "".join(c for c in name.lower() if c.isalnum()) or "persona"
    return f"digital-profile-{slug}+{max_id + 1:03d}"


def save_generated_profile(profile: DigitalProfile) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{profile.profile_id}.json"
    path.write_text(profile.model_dump_json(indent=2))


# ─── Runtime State (mutable, per-user) ───────────────────────────────────────
#
# State is namespaced by user_id so each tester has a private relationship with
# the (shared, read-only) personas. user_id defaults to "local" for the local
# single-user dev flow and the test scripts.

DEFAULT_USER = "local"


def _user_dir(user_id: str) -> Path:
    d = STATE_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(persona_id: str, user_id: str = DEFAULT_USER) -> Path:
    return _user_dir(user_id) / f"runtime-{persona_id}.json"


def load_state(persona_id: str, user_id: str = DEFAULT_USER) -> RuntimeState:
    path = _state_path(persona_id, user_id)
    if not path.exists():
        return RuntimeState(persona_id=persona_id)
    return RuntimeState.model_validate_json(path.read_text())


def save_state(state: RuntimeState, user_id: str = DEFAULT_USER) -> None:
    path = _state_path(state.persona_id, user_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    os.replace(tmp, path)


# ─── Per-user display name registry (for feedback export) ─────────────────────

def set_display_name(user_id: str, display_name: str) -> None:
    path = _user_dir(user_id) / "profile.json"
    path.write_text(json.dumps({"user_id": user_id, "display_name": display_name}))


def get_display_name(user_id: str) -> str:
    path = STATE_DIR / user_id / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("display_name", user_id)
        except (json.JSONDecodeError, OSError):
            pass
    return user_id


def list_user_ids() -> list[str]:
    if not STATE_DIR.exists():
        return []
    return [p.name for p in STATE_DIR.iterdir() if p.is_dir()]


# ─── Buffer helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_to_buffer(
    state: RuntimeState,
    role: str,
    text: str,
    delay_bucket: DelayBucket = "immediate",
    user_id: str = DEFAULT_USER,
) -> RuntimeState:
    msg = BufferMessage(role=role, text=text, ts=_now_iso(), delay_bucket=delay_bucket)
    buffer = list(state.short_buffer) + [msg]
    # Trim to last N messages
    buffer = buffer[-SHORT_BUFFER_SIZE:]
    updated = state.model_copy(update={"short_buffer": buffer})
    save_state(updated, user_id)
    return updated


# ─── Layered memory helpers (M1) ──────────────────────────────────────────────

def append_events(state: RuntimeState, cycle: int, events: list[EventEntry]) -> RuntimeState:
    """Append this cycle's events to the episodic log; cap to most recent EVENT_LOG_CAP."""
    log = list(state.event_log) + list(events)
    log = log[-EVENT_LOG_CAP:]
    return state.model_copy(update={"event_log": log})


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def merge_user_memory(state: RuntimeState, new_items: list[MemoryItem]) -> RuntimeState:
    """Merge new durable facts about the user; dedup near-identical text,
    keep the top USER_MEMORY_CAP by salience then recency."""
    merged: dict[str, MemoryItem] = {_norm(m.text): m for m in state.user_memory}
    for item in new_items:
        key = _norm(item.text)
        existing = merged.get(key)
        # Keep the higher-salience / more recent version on collision.
        if existing is None or item.salience > existing.salience or item.cycle_added > existing.cycle_added:
            merged[key] = item
    ranked = sorted(merged.values(), key=lambda m: (m.salience, m.cycle_added), reverse=True)
    return state.model_copy(update={"user_memory": ranked[:USER_MEMORY_CAP]})


def set_preoccupations(state: RuntimeState, preoccupations: list[str]) -> RuntimeState:
    return state.model_copy(update={"preoccupations": preoccupations})


def set_open_threads(state: RuntimeState, threads: list[ThreadItem]) -> RuntimeState:
    return state.model_copy(update={"open_threads": threads})


def append_mood(state: RuntimeState, cycle: int, mood: str) -> RuntimeState:
    history = list(state.mood_history) + [MoodEntry(cycle=cycle, mood=mood)]
    history = history[-MOOD_HISTORY_CAP:]
    return state.model_copy(update={"mood_history": history})


def recent_events_window(state: RuntimeState, cycles: int = 2) -> list[EventEntry]:
    """Events from the last `cycles` notional days (for prompt context)."""
    if not state.event_log:
        return []
    latest = max(e.cycle for e in state.event_log)
    cutoff = latest - (cycles - 1)
    return [e for e in state.event_log if e.cycle >= cutoff]


# ─── Persona summary (for listing) ───────────────────────────────────────────

def get_persona_summary(profile: DigitalProfile, state: RuntimeState) -> PersonaSummary:
    return PersonaSummary(
        profile_id=profile.profile_id,
        name=profile.name,
        mood=state.mood or "Just getting started…",
        cycle_count=state.cycle_count,
        energy_vibe=profile.onboarding.energy_vibe.value,
        relationship_type=profile.onboarding.relationship_type.value,
    )
