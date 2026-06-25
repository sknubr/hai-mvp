#!/usr/bin/env python3
"""Validate state I/O round-trip without any LLM calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.state import (
    load_all_profiles,
    load_state,
    save_state,
    append_to_buffer,
    get_persona_summary,
)
from app.models import RuntimeState

def main():
    print("── Test 1: Load all profiles ──")
    profiles = load_all_profiles()
    if not profiles:
        print("  [FAIL] No profiles found. Run scripts/generate_profiles.py first.")
        sys.exit(1)
    for pid, p in profiles.items():
        print(f"  [ok] {p.name} ({pid})")

    print("\n── Test 2: Load/create default runtime state ──")
    first_id = next(iter(profiles))
    state = load_state(first_id)
    print(f"  [ok] cycle_count={state.cycle_count}, mood={state.mood!r}")

    print("\n── Test 3: Save and reload state ──")
    from app.models import RecentEvent
    test_state = RuntimeState(
        persona_id=first_id,
        cycle_count=1,
        mood="Testing",
        journal="This is a test journal entry.",
        recent_events=[RecentEvent(cycle=1, text="Test event happened")],
        short_buffer=[],
    )
    save_state(test_state)
    reloaded = load_state(first_id)
    assert reloaded.cycle_count == 1, "cycle_count mismatch"
    assert reloaded.mood == "Testing", "mood mismatch"
    assert len(reloaded.recent_events) == 1, "events mismatch"
    print("  [ok] Save and reload match")

    print("\n── Test 4: Buffer append and trim ──")
    s = RuntimeState(persona_id=first_id)
    for i in range(20):
        s = append_to_buffer(s, "user" if i % 2 == 0 else "persona", f"Message {i}")
    reloaded = load_state(first_id)
    assert len(reloaded.short_buffer) == 15, f"Buffer not trimmed: {len(reloaded.short_buffer)}"
    print(f"  [ok] Buffer trimmed to 15 messages (from 20)")

    print("\n── Test 5: Persona summary ──")
    profile = profiles[first_id]
    state = load_state(first_id)
    summary = get_persona_summary(profile, state)
    print(f"  [ok] {summary.name} — mood: {summary.mood!r}, cycle: {summary.cycle_count}")

    # Reset state for clean slate
    save_state(RuntimeState(persona_id=first_id))
    print("\nAll tests passed. State reset to clean slate.")

if __name__ == "__main__":
    main()
