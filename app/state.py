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
    PersonaSummary,
    RuntimeState,
)

PROFILES_DIR = Path(__file__).parent.parent / "profiles"
STATE_DIR = Path(__file__).parent.parent / "data" / "state"
SHORT_BUFFER_SIZE = 15


# ─── Profiles (read-only) ─────────────────────────────────────────────────────

def load_profile(persona_id: str) -> DigitalProfile:
    path = PROFILES_DIR / f"{persona_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    return DigitalProfile.model_validate_json(path.read_text())


def load_all_profiles() -> dict[str, DigitalProfile]:
    profiles: dict[str, DigitalProfile] = {}
    for p in sorted(PROFILES_DIR.glob("digital-profile-*.json")):
        profile = DigitalProfile.model_validate_json(p.read_text())
        profiles[profile.profile_id] = profile
    return profiles


# ─── Runtime State (mutable) ─────────────────────────────────────────────────

def _state_path(persona_id: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"runtime-{persona_id}.json"


def load_state(persona_id: str) -> RuntimeState:
    path = _state_path(persona_id)
    if not path.exists():
        return RuntimeState(persona_id=persona_id)
    return RuntimeState.model_validate_json(path.read_text())


def save_state(state: RuntimeState) -> None:
    path = _state_path(state.persona_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    os.replace(tmp, path)


# ─── Buffer helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_to_buffer(
    state: RuntimeState,
    role: str,
    text: str,
    delay_bucket: DelayBucket = "immediate",
) -> RuntimeState:
    msg = BufferMessage(role=role, text=text, ts=_now_iso(), delay_bucket=delay_bucket)
    buffer = list(state.short_buffer) + [msg]
    # Trim to last N messages
    buffer = buffer[-SHORT_BUFFER_SIZE:]
    updated = state.model_copy(update={"short_buffer": buffer})
    save_state(updated)
    return updated


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
