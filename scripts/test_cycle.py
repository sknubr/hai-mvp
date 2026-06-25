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

from app.state import load_all_profiles, load_state, save_state
from app.llm import run_cycle
from app.models import RecentEvent, RuntimeState


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
        print(f"\n─── CYCLE {state.cycle_count + 1} ───")
        try:
            result = run_cycle(profile, state)
        except Exception as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        # Update state
        new_events = [RecentEvent(cycle=state.cycle_count + 1, text=e) for e in result.events]
        state = state.model_copy(update={
            "cycle_count": state.cycle_count + 1,
            "mood": result.mood,
            "journal": result.journal,
            "recent_events": new_events,
        })
        save_state(state)

        print(f"\nEvents:")
        for ev in result.events:
            print(f"  • {ev}")

        print(f"\nMood: {result.mood}")

        print(f"\nJournal ({len(result.journal.split())} words):")
        # Print first 150 words of journal
        words = result.journal.split()
        preview = " ".join(words[:150])
        if len(words) > 150:
            preview += " …"
        print(f"  {preview}")

        if result.post:
            print(f"\nPost:")
            print(f"  {result.post}")
        else:
            print(f"\nPost: [no post this cycle]")

    print("\n" + "=" * 60)
    print(f"Done. {profile.name} is now on cycle {state.cycle_count}.")
    print("\nEvaluate 'alive' signal:")
    print("  ✓ Are events specific and grounded in this persona's world?")
    print("  ✓ Does the journal feel like this character's voice?")
    print("  ✓ Does the mood change incrementally across cycles?")
    print("  ✓ Are posts (when present) authentic to this persona?")


if __name__ == "__main__":
    main()
