#!/usr/bin/env python3
"""
One-time backfill: seed the shared global feed (data/feed/_global/feed.csv) from
every existing per-user feed, so historical posts appear in the cross-user view.

Idempotent: skips rows whose post_id is already in the global feed. Safe to re-run.

Usage:
  python scripts/backfill_global_feed.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import feed


def main():
    global_path = feed._global_feed_csv()
    feed._ensure_csv(global_path, feed.FEED_HEADERS)

    existing: set[str] = set()
    with open(global_path, newline="") as f:
        for row in csv.DictReader(f):
            existing.add(row["post_id"])

    added = 0
    for user_dir in sorted(feed.FEED_DIR.iterdir()):
        if not user_dir.is_dir() or user_dir.name == feed.GLOBAL_USER:
            continue
        per_user = user_dir / "feed.csv"
        if not per_user.exists():
            continue
        with open(per_user, newline="") as f:
            for row in csv.DictReader(f):
                if row["post_id"] in existing:
                    continue
                feed._append_row(global_path, feed.FEED_HEADERS,
                                 [row["post_id"], row["persona_id"], row["cycle"],
                                  row["timestamp"], row["post_text"]])
                existing.add(row["post_id"])
                added += 1

    print(f"Backfill complete: {added} post(s) added to {global_path}")


if __name__ == "__main__":
    main()
