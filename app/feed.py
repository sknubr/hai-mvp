"""
Per-user append-only CSV I/O for feed, reactions, and feedback.

Everything is namespaced by user_id so testers don't share state:
  data/feed/{user_id}/feed.csv
  data/feed/{user_id}/reactions.csv
  data/feedback/{user_id}.csv
user_id defaults to "local" for the single-user dev flow and test scripts.
"""
from __future__ import annotations

import csv
import fcntl
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import FeedPost

DATA_DIR = Path(__file__).parent.parent / "data"
FEED_DIR = DATA_DIR / "feed"
FEEDBACK_DIR = DATA_DIR / "feedback"
DEFAULT_USER = "local"

FEED_HEADERS = ["post_id", "persona_id", "cycle", "timestamp", "post_text"]
REACTIONS_HEADERS = ["reaction_id", "post_id", "persona_id", "reaction_type", "reaction_value", "timestamp"]
FEEDBACK_HEADERS = ["feedback_id", "user_id", "persona_id", "kind", "target_ref",
                    "rating", "signal_tag", "comment", "timestamp"]


def _feed_csv(user_id: str) -> Path:
    return FEED_DIR / user_id / "feed.csv"


def _reactions_csv(user_id: str) -> Path:
    return FEED_DIR / user_id / "reactions.csv"


def _feedback_csv(user_id: str) -> Path:
    return FEEDBACK_DIR / f"{user_id}.csv"


def _ensure_csv(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)


def init_csvs(user_id: str = DEFAULT_USER) -> None:
    _ensure_csv(_feed_csv(user_id), FEED_HEADERS)
    _ensure_csv(_reactions_csv(user_id), REACTIONS_HEADERS)
    _ensure_csv(_feedback_csv(user_id), FEEDBACK_HEADERS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_row(path: Path, headers: list[str], row: list) -> None:
    _ensure_csv(path, headers)
    with open(path, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            csv.writer(f).writerow(row)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ─── Feed ─────────────────────────────────────────────────────────────────────

def append_post(persona_id: str, cycle: int, post_text: str, user_id: str = DEFAULT_USER) -> str:
    post_id = str(uuid.uuid4())
    _append_row(_feed_csv(user_id), FEED_HEADERS,
                [post_id, persona_id, cycle, _now_iso(), post_text])
    return post_id


def get_feed(persona_id: str | None = None, user_id: str = DEFAULT_USER) -> list[FeedPost]:
    path = _feed_csv(user_id)
    _ensure_csv(path, FEED_HEADERS)
    posts: list[FeedPost] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
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


# ─── Reactions ────────────────────────────────────────────────────────────────

def append_reaction(post_id: str, persona_id: str, reaction_type: str,
                    reaction_value: str, user_id: str = DEFAULT_USER) -> str:
    reaction_id = str(uuid.uuid4())
    _append_row(_reactions_csv(user_id), REACTIONS_HEADERS,
                [reaction_id, post_id, persona_id, reaction_type, reaction_value, _now_iso()])
    return reaction_id


def get_reactions(post_id: str, user_id: str = DEFAULT_USER) -> list[dict]:
    path = _reactions_csv(user_id)
    _ensure_csv(path, REACTIONS_HEADERS)
    with open(path, newline="") as f:
        return [dict(row) for row in csv.DictReader(f) if row["post_id"] == post_id]


# ─── Feedback (Milestone B) ───────────────────────────────────────────────────

def append_feedback(user_id: str, persona_id: str, kind: str, target_ref: str,
                    rating: str, signal_tag: str, comment: str) -> str:
    feedback_id = str(uuid.uuid4())
    _append_row(_feedback_csv(user_id), FEEDBACK_HEADERS,
                [feedback_id, user_id, persona_id, kind, target_ref,
                 rating, signal_tag, comment, _now_iso()])
    return feedback_id


def all_feedback() -> list[dict]:
    """Every user's feedback rows, for the admin export."""
    rows: list[dict] = []
    if not FEEDBACK_DIR.exists():
        return rows
    for path in sorted(FEEDBACK_DIR.glob("*.csv")):
        with open(path, newline="") as f:
            rows.extend(dict(r) for r in csv.DictReader(f))
    return rows
