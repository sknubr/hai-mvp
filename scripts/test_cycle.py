#!/usr/bin/env python3
"""
Validate the runCycle LLM operation.
Run 3–5 cycles for a persona and print results to manually evaluate
the 'alive' signal before building the server.

Usage:
  python scripts/test_cycle.py
  python scripts/test_cycle.py --persona digital-profile-nadia+001 --cycles 5
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.state import (
    load_all_profiles,
    load_state,
    save_state,
    append_events,
    append_mood,
    merge_user_memory,
    set_preoccupations,
    set_open_threads,
)
from app.llm import run_cycle
from app.models import RuntimeState


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", default=None, help="persona profile_id (default: first found)")
    parser.add_argument("--cycles", type=int, default=3, help="number of cycles to run (default: 3)")
    parser.add_argument("--reset", action="store_true", help="reset state before running")
    args = parser.parse_args()

    profiles = load_all_profiles()
    if not profiles:
        print("[FAIL] No profiles found. Run scripts/generate_profiles.py first.")
        sys.exit(1)

    if args.persona:
        if args.persona not in profiles:
            print(f"[FAIL] Persona not found: {args.persona}")
            print("Available:", list(profiles.keys()))
            sys.exit(1)
        profile = profiles[args.persona]
    else:
        profile = next(iter(profiles.values()))

    print(f"Running {args.cycles} cycles for: {profile.name} ({profile.profile_id})")
    print("=" * 60)

    if args.reset:
        save_state(RuntimeState(persona_id=profile.profile_id))
        print("State reset.\n")

    state = load_state(profile.profile_id)

    for i in range(args.cycles):
        new_cycle = state.cycle_count + 1
        print(f"\n─── CYCLE {new_cycle} ───")

        prev_preocc = set(state.preoccupations)

        try:
            result = run_cycle(profile, state)
        except Exception as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        # Stamp + merge into layered memory (mirrors the /cycle endpoint).
        for e in result.events:
            e.cycle = new_cycle
        for f in result.salient_user_facts:
            if not f.cycle_added:
                f.cycle_added = new_cycle
        for t in result.open_threads:
            if not t.cycle_added:
                t.cycle_added = new_cycle

        state = state.model_copy(update={
            "cycle_count": new_cycle,
            "mood": result.mood,
            "journal": result.journal,
        })
        state = append_events(state, new_cycle, result.events)
        state = append_mood(state, new_cycle, result.mood)
        state = merge_user_memory(state, result.salient_user_facts)
        state = set_preoccupations(state, result.preoccupations)
        state = set_open_threads(state, result.open_threads)
        save_state(state)

        print("\nEvents:")
        for ev in result.events:
            print(f"  • [s{ev.salience}] {ev.text}")

        print(f"\nMood: {result.mood}")

        # Drift diff (M6): show how preoccupations evolved.
        now_preocc = set(result.preoccupations)
        added = now_preocc - prev_preocc
        dropped = prev_preocc - now_preocc
        carried = now_preocc & prev_preocc
        print("\nPreoccupations:")
        print(f"  carried: {sorted(carried) or '—'}")
        print(f"  + added: {sorted(added) or '—'}")
        print(f"  - dropped/resolved: {sorted(dropped) or '—'}")

        if result.salient_user_facts:
            print("\nNew salient facts about the user:")
            for f in result.salient_user_facts:
                print(f"  • [s{f.salience}] {f.text}")

        open_t = [t for t in result.open_threads if t.status == "open"]
        if open_t:
            print("\nOpen follow-up threads:")
            for t in open_t:
                print(f"  • {t.text}")

        words = result.journal.split()
        preview = " ".join(words[:120])
        if len(words) > 120:
            preview += " …"
        print(f"\nJournal ({len(words)} words): {preview}")

        print(f"\nPost: {result.post if result.post else '[no post this cycle]'}")

    print("\n" + "=" * 60)
    print(f"Done. {profile.name} is on cycle {state.cycle_count}.")
    print(f"  event_log: {len(state.event_log)} events | user_memory: {len(state.user_memory)} facts "
          f"| open threads: {len([t for t in state.open_threads if t.status=='open'])}")
    print("\nEvaluate signals:")
    print("  ✓ ALIVE: events specific, salience-varied, building on recent days?")
    print("  ✓ CONSISTENT: voice/values stable; preoccupations carry, not reset?")
    print("  ✓ CONTINUITY: substantive user facts captured; trivia ignored?")


if __name__ == "__main__":
    main()
