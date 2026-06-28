"""
Async delay mechanic: map delay buckets to real wall-clock durations and pick a
bucket per reply.

Buckets are the persona's "I'll reply later" feel. Durations are configurable so
testers can experience async delivery in seconds (fast mode) while production can
use realistic hours (real mode).
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

from app.models import DELAY_BUCKETS, DelayBucket

# Realistic durations (seconds).
BUCKET_SECONDS_REAL: dict[str, int] = {
    "immediate": 0,
    "<10 min": 600,
    "2 hours": 7200,
    "10 hours": 36000,
    "24 hours": 86400,
}

# Compressed durations for testing — same shape, minutes not hours.
BUCKET_SECONDS_FAST: dict[str, int] = {
    "immediate": 0,
    "<10 min": 20,
    "2 hours": 60,
    "10 hours": 120,
    "24 hours": 180,
}


def _mode() -> str:
    """'fast' (compressed, default) or 'real' (true durations)."""
    return os.getenv("HAI_DELAY_MODE", "fast").strip().lower()


def bucket_seconds(bucket: DelayBucket) -> int:
    table = BUCKET_SECONDS_FAST if _mode() == "fast" else BUCKET_SECONDS_REAL
    return table.get(bucket, 0)


def due_ts(bucket: DelayBucket, *, now: datetime | None = None) -> str:
    """ISO timestamp when a reply in this bucket should be delivered.
    Adds small (+0–15%) jitter so deliveries don't feel mechanical."""
    base = bucket_seconds(bucket)
    secs = base + (random.uniform(0, 0.15) * base if base else 0)
    t = (now or datetime.now(timezone.utc)) + timedelta(seconds=secs)
    return t.isoformat()


def pick_delay_bucket() -> DelayBucket:
    """Choose how long the persona takes to reply. `HAI_FORCE_BUCKET` pins it for
    deterministic testing (e.g. HAI_FORCE_BUCKET='<10 min')."""
    forced = os.getenv("HAI_FORCE_BUCKET", "").strip()
    if forced in DELAY_BUCKETS:
        return forced  # type: ignore[return-value]
    return random.choice(DELAY_BUCKETS)
