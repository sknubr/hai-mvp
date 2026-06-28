#!/usr/bin/env python3
"""
Validate the reply LLM operation interactively.
Sends messages to a persona and prints replies with delay buckets.

Usage:
  python scripts/test_reply.py
  python scripts/test_reply.py --persona digital-profile-sol+002
  python scripts/test_reply.py --persona digital-profile-nadia+001 --no-save
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.state import load_all_profiles, load_state, append_to_buffer
from app.llm import reply


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", default=None)
    parser.add_argument("--no-save", action="store_true", help="don't persist messages to buffer")
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

    state = load_state(profile.profile_id)

    print(f"Chatting with {profile.name} (cycle {state.cycle_count})")
    print(f"Mood: {state.mood or 'Not established yet'}")
    print("Type a message and press Enter. Ctrl+C to quit.\n")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input:
                continue

            if not args.no_save:
                state = append_to_buffer(state, "user", user_input)

            print(f"\n{profile.name}: ", end="", flush=True)
            from app.delays import pick_delay_bucket
            reply_text = reply(profile, state, user_input)
            delay_bucket = pick_delay_bucket()
            print(reply_text)
            print(f"  [delay: {delay_bucket}]\n")

            if not args.no_save:
                state = append_to_buffer(state, "persona", reply_text, delay_bucket)

    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
