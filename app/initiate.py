"""
Character-initiated messaging: the restraint engine (PRD §1, §5).

Decides WHEN a persona may reach out to a user unprompted. Cheap, deterministic
gates (idle / cooldown / quiet hours / daily cap / no-stacking / backoff) run first
and short-circuit; only when they all pass do we make the single LLM judge+write
call (app.llm.initiate), which decides whether it's actually worth interrupting and,
if so, writes the opener. Approved reach-outs are enqueued as a ScheduledReply
(kind="initiation") that the existing scheduler delivers.

Timing mirrors app.delays' fast/real mode so testers can experience it in seconds.
Imports state/memory/llm/usage; imports app.schedule lazily inside functions to
avoid an import cycle (schedule drives this module).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from app import llm as llm_module
from app import memory as memory_module
from app import state as state_module
from app import usage as usage_module
from app.models import DigitalProfile, ScheduledReply
from app.state import STATE_DIR

# ─── Timing config (GENTLE defaults; fast mode compresses for testing) ─────────

# seconds
THRESHOLDS_REAL = {"idle": 6 * 3600, "cooldown": 6 * 3600, "backoff": 2 * 3600}
THRESHOLDS_FAST = {"idle": 30, "cooldown": 30, "backoff": 20}

QUIET_START_HOUR = 22   # 22:00
QUIET_END_HOUR = 9      # 09:00 (local, via HAI_TZ_OFFSET)


def _enabled() -> bool:
    return os.getenv("HAI_INITIATION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")


def _mode() -> str:
    """'fast' (default) or 'real'. Follows HAI_INITIATION_MODE, else HAI_DELAY_MODE."""
    m = os.getenv("HAI_INITIATION_MODE", "").strip().lower()
    if m in ("fast", "real"):
        return m
    return os.getenv("HAI_DELAY_MODE", "fast").strip().lower()


def _thr() -> dict[str, int]:
    return THRESHOLDS_FAST if _mode() == "fast" else THRESHOLDS_REAL


def _max_per_day() -> int:
    try:
        return max(0, int(os.getenv("HAI_INITIATION_MAX_PER_DAY", "1")))
    except ValueError:
        return 1


def _tz_offset() -> float:
    try:
        return float(os.getenv("HAI_TZ_OFFSET", "0"))
    except ValueError:
        return 0.0


def _quiet_enabled() -> bool:
    """Quiet hours apply in real mode (disabled in fast so tests aren't blocked)."""
    override = os.getenv("HAI_INITIATION_QUIET", "").strip().lower()
    if override in ("0", "false", "no"):
        return False
    if override in ("1", "true", "yes"):
        return True
    return _mode() == "real"


# ─── Time helpers ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local(dt: datetime) -> datetime:
    return dt + timedelta(hours=_tz_offset())


def _today_str(now: datetime) -> str:
    return _local(now).date().isoformat()


def _in_quiet_hours(now: datetime) -> bool:
    if not _quiet_enabled():
        return False
    h = _local(now).hour
    # Window wraps midnight (22:00 → 09:00).
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR


def _humanize(seconds: float) -> str:
    if seconds < 90 * 60:
        return "a little while"
    hours = seconds / 3600
    if hours < 24:
        return f"about {int(round(hours))} hours"
    days = hours / 24
    return "about a day" if days < 1.5 else f"about {int(round(days))} days"


# ─── Per-relationship bookkeeping ──────────────────────────────────────────────

def _book_path(persona_id: str, user_id: str):
    d = STATE_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"initiation-{persona_id}.json"


def load_book(persona_id: str, user_id: str) -> dict:
    path = _book_path(persona_id, user_id)
    if not path.exists():
        return {"last_initiated_ts": "", "last_considered_ts": "", "count_today": 0, "day": ""}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"last_initiated_ts": "", "last_considered_ts": "", "count_today": 0, "day": ""}


def save_book(persona_id: str, user_id: str, book: dict) -> None:
    path = _book_path(persona_id, user_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(book, indent=2))
    os.replace(tmp, path)


# ─── Conversation introspection ────────────────────────────────────────────────

def _messages(persona_id: str, user_id: str):
    """Full transcript if present, else the short buffer (back-compat)."""
    msgs = state_module.load_transcript(persona_id, user_id)
    if msgs:
        return msgs
    return state_module.load_state(persona_id, user_id).short_buffer


def _last_ts(msgs, *, role: str | None = None) -> datetime | None:
    for m in reversed(msgs):
        if role is None or m.role == role:
            dt = _parse(m.ts)
            if dt is not None:
                return dt
    return None


def _pending_initiation(persona_id: str, user_id: str) -> bool:
    from app import schedule as schedule_module  # lazy: avoid import cycle
    return any(
        j.status == "pending" and j.kind == "initiation"
        for j in schedule_module.load_queue(persona_id, user_id)
    )


# ─── The gate (deterministic, no LLM) ──────────────────────────────────────────

def gate(persona_id: str, user_id: str, *, now: datetime | None = None) -> tuple[bool, str]:
    """Cheap pre-checks. Returns (ok, reason). Run before any LLM call."""
    now = now or _now()
    if not _enabled():
        return False, "disabled"

    msgs = _messages(persona_id, user_id)
    if not msgs:
        return False, "no relationship yet"

    last_user = _last_ts(msgs, role="user")
    if last_user is None:
        return False, "user has never messaged"  # never cold-open

    thr = _thr()
    last_any = _last_ts(msgs)
    if last_any is not None and (now - last_any).total_seconds() < thr["cooldown"]:
        return False, "within cooldown of last message"

    if (now - last_user).total_seconds() < thr["idle"]:
        return False, "user not idle long enough"

    if _in_quiet_hours(now):
        return False, "quiet hours"

    book = load_book(persona_id, user_id)
    count_today = book["count_today"] if book.get("day") == _today_str(now) else 0
    if count_today >= _max_per_day():
        return False, "daily cap reached"

    last_considered = _parse(book.get("last_considered_ts", ""))
    if last_considered is not None and (now - last_considered).total_seconds() < thr["backoff"]:
        return False, "backoff after recent decision"

    if _pending_initiation(persona_id, user_id):
        return False, "initiation already pending"

    return True, "ok"


# ─── Consider: gate → LLM judge+write → enqueue ────────────────────────────────

def _recall_query(state) -> str:
    """A query for memory recall when there's no user message to anchor on."""
    parts = list(state.preoccupations)
    parts += [t.text for t in state.open_threads if t.status == "open"]
    return " ".join(parts)[:400]


def consider(profile: DigitalProfile, persona_id: str, user_id: str,
             *, now: datetime | None = None) -> tuple[bool, str]:
    """Evaluate one relationship. If gates pass, make the single judge+write call;
    enqueue an initiation on a yes, set backoff on a no. Returns (reached_out, reason)."""
    now = now or _now()
    ok, reason = gate(persona_id, user_id, now=now)
    if not ok:
        return False, reason

    s = state_module.load_state(persona_id, user_id)
    store = memory_module.load_store(persona_id, user_id)
    query = _recall_query(s)
    recalled = memory_module.select_relevant(store, query, s.cycle_count) if query else []
    if recalled:
        store = memory_module.reinforce(store, recalled)
        memory_module.save_store(store, user_id)

    last_user = _last_ts(_messages(persona_id, user_id), role="user")
    idle_secs = (now - last_user).total_seconds() if last_user else 0
    idle_human = _humanize(idle_secs)

    decision = llm_module.initiate(
        profile, s, recalled=recalled,
        short_term_summary=store.short_term_summary, idle_human=idle_human,
    )
    usage_module.record_call(user_id)

    book = load_book(persona_id, user_id)
    if book.get("day") != _today_str(now):
        book["day"] = _today_str(now)
        book["count_today"] = 0

    if decision.reach_out and decision.message.strip():
        from app import schedule as schedule_module  # lazy: avoid import cycle
        schedule_module.enqueue(ScheduledReply(
            id=schedule_module.new_id(),
            persona_id=persona_id,
            user_id=user_id,
            user_message="",
            message=decision.message.strip(),
            delay_bucket="immediate",
            created_ts=now.isoformat(),
            due_ts=now.isoformat(),
            kind="initiation",
            initiated_by="character",
        ))
        book["last_initiated_ts"] = now.isoformat()
        book["last_considered_ts"] = now.isoformat()
        book["count_today"] = book.get("count_today", 0) + 1
        save_book(persona_id, user_id, book)
        return True, decision.reason or "reached out"

    book["last_considered_ts"] = now.isoformat()
    save_book(persona_id, user_id, book)
    return False, decision.reason or "decided not to reach out"
