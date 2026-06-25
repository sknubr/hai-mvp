"""
Append-only CSV I/O for feed.csv and reactions.csv.
"""
from __future__ import annotations

import csv
import fcntl
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import FeedPost

DATA_DIR = Path(__file__).parent.parent / "data"
FEED_CSV = DATA_DIR / "feed.csv"
REACTIONS_CSV = DATA_DIR / "reactions.csv"

FEED_HEADERS = ["post_id", "persona_id", "cycle", "timestamp", "post_text"]
REACTIONS_HEADERS = ["reaction_id", "post_id", "persona_id", "reaction_type", "reaction_value", "timestamp"]


def _ensure_csv(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)


def init_csvs() -> None:
    _ensure_csv(FEED_CSV, FEED_HEADERS)
    _ensure_csv(REACTIONS_CSV, REACTIONS_HEADERS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_post(persona_id: str, cycle: int, post_text: str) -> str:
    post_id = str(uuid.uuid4())
    _ensure_csv(FEED_CSV, FEED_HEADERS)
    with open(FEED_CSV, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            writer = csv.writer(f)
            writer.writerow([post_id, persona_id, cycle, _now_iso(), post_text])
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return post_id


def get_feed(persona_id: str | None = None) -> list[FeedPost]:
    _ensure_csv(FEED_CSV, FEED_HEADERS)
    posts: list[FeedPost] = []
    with open(FEED_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if persona_id and row["persona_id"] != persona_id:
                continue
            posts.append(FeedPost(
                post_id=row["post_id"],
                persona_id=row["persona_id"],
                cycle=int(row["cycle"]),
                timestamp=row["timestamp"],
                post_text=row["post_text"],
            ))
    return list(reversed(posts))


def append_reaction(post_id: str, persona_id: str, reaction_type: str, reaction_value: str) -> str:
    reaction_id = str(uuid.uuid4())
    _ensure_csv(REACTIONS_CSV, REACTIONS_HEADERS)
    with open(REACTIONS_CSV, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            writer = csv.writer(f)
            writer.writerow([reaction_id, post_id, persona_id, reaction_type, reaction_value, _now_iso()])
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return reaction_id


def get_reactions(post_id: str) -> list[dict]:
    _ensure_csv(REACTIONS_CSV, REACTIONS_HEADERS)
    results = []
    with open(REACTIONS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["post_id"] == post_id:
                results.append(dict(row))
    return results
