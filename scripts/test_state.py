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
    append_events,
    merge_user_memory,
    append_mood,
    recent_events_window,
    EVENT_LOG_CAP,
    USER_MEMORY_CAP,
    STATE_DIR,
)
from app.models import RuntimeState, EventEntry, MemoryItem

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

    print("\n── Test 6: Event log accumulates and caps ──")
    s = RuntimeState(persona_id=first_id)
    for cyc in range(1, 16):  # 15 cycles x 4 events = 60 > cap
        evs = [EventEntry(cycle=cyc, text=f"event {cyc}.{i}", salience=3) for i in range(4)]
        s = append_events(s, cyc, evs)
    assert len(s.event_log) == EVENT_LOG_CAP, f"event_log not capped: {len(s.event_log)}"
    win = recent_events_window(s, cycles=2)
    assert all(e.cycle >= 14 for e in win), "window should be last 2 cycles"
    print(f"  [ok] event_log capped at {EVENT_LOG_CAP}; window={len(win)} events from last 2 cycles")

    print("\n── Test 7: User memory dedup + salience cap ──")
    s = RuntimeState(persona_id=first_id)
    s = merge_user_memory(s, [MemoryItem(text="Sat is job hunting", cycle_added=1, salience=4)])
    # Duplicate with higher salience should replace, not double
    s = merge_user_memory(s, [MemoryItem(text="sat is job hunting", cycle_added=2, salience=5)])
    assert len(s.user_memory) == 1, f"dedup failed: {len(s.user_memory)}"
    assert s.user_memory[0].salience == 5, "should keep higher salience"
    # Overflow cap
    s = merge_user_memory(s, [MemoryItem(text=f"fact {i}", cycle_added=3, salience=2) for i in range(40)])
    assert len(s.user_memory) == USER_MEMORY_CAP, f"user_memory not capped: {len(s.user_memory)}"
    assert s.user_memory[0].salience == 5, "highest salience should rank first"
    assert "job hunting" in s.user_memory[0].text.lower(), "the salience-5 fact should rank first"
    print(f"  [ok] dedup + salience cap at {USER_MEMORY_CAP}")

    print("\n── Test 8: Backward-compat load of old state shape ──")
    old_path = STATE_DIR / f"runtime-{first_id}.json"
    old_path.write_text('{"persona_id": "%s", "cycle_count": 2, "mood": "old", '
                        '"journal": "j", "recent_events": [{"cycle": 1, "text": "x"}], '
                        '"short_buffer": []}' % first_id)
    reloaded = load_state(first_id)
    assert reloaded.cycle_count == 2 and reloaded.event_log == [], "old state should load with empty new fields"
    print("  [ok] legacy state file loads; new fields default empty")

    # Reset state for clean slate
    save_state(RuntimeState(persona_id=first_id))
    print("\nAll tests passed. State reset to clean slate.")

if __name__ == "__main__":
    main()
