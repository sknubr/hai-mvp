#!/usr/bin/env python3
"""
Deterministic tests for character-initiated messaging (no live LLM calls).
Covers: fast/real timing, quiet hours, each deterministic gate, and consider()'s
yes/no paths (monkeypatched LLM) including enqueue + backoff bookkeeping.

Usage:
  python scripts/test_initiate.py
"""
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import initiate, llm, schedule, state, usage
from app.models import BufferMessage, InitiationResponse
from app.state import STATE_DIR, load_all_profiles

TEST_UID = "initiate_test_user"
PID = "digital-profile-test+777"


def _reset():
    shutil.rmtree(STATE_DIR / TEST_UID, ignore_errors=True)


def _seed(now: datetime, msgs):
    """msgs: list of (role, seconds_ago). Writes a transcript relative to `now`."""
    _reset()
    for role, ago in msgs:
        ts = (now - timedelta(seconds=ago)).isoformat()
        state.append_transcript(PID, TEST_UID, BufferMessage(role=role, text="hi", ts=ts))


def test_timing():
    os.environ["HAI_INITIATION_MODE"] = "fast"
    assert initiate._thr()["idle"] == initiate.THRESHOLDS_FAST["idle"]
    os.environ["HAI_INITIATION_MODE"] = "real"
    assert initiate._thr()["idle"] == 6 * 3600
    os.environ["HAI_INITIATION_MODE"] = "fast"

    # Quiet hours: real mode on, fast mode off by default.
    os.environ.pop("HAI_INITIATION_QUIET", None)
    assert initiate._in_quiet_hours(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)) is False  # fast
    os.environ["HAI_INITIATION_QUIET"] = "1"
    assert initiate._in_quiet_hours(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)) is True
    assert initiate._in_quiet_hours(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)) is True
    assert initiate._in_quiet_hours(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)) is False
    os.environ.pop("HAI_INITIATION_QUIET", None)
    print("  [ok] fast/real thresholds + quiet-hours window")


def test_gates():
    os.environ["HAI_INITIATION_MODE"] = "fast"
    os.environ["HAI_INITIATION_ENABLED"] = "1"
    initiate.THRESHOLDS_FAST = {"idle": 100, "cooldown": 10, "backoff": 50}
    now = datetime.now(timezone.utc)

    # Disabled
    os.environ["HAI_INITIATION_ENABLED"] = "0"
    _seed(now, [("user", 200), ("persona", 200)])
    assert initiate.gate(PID, TEST_UID, now=now) == (False, "disabled")
    os.environ["HAI_INITIATION_ENABLED"] = "1"

    # No relationship
    _reset()
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "no relationship yet"

    # User never messaged (persona-only history)
    _seed(now, [("persona", 200)])
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "user has never messaged"

    # Within cooldown (last message just now)
    _seed(now, [("user", 200), ("persona", 5)])
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "within cooldown of last message"

    # User not idle long enough (>cooldown, <idle)
    _seed(now, [("user", 50), ("persona", 50)])
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "user not idle long enough"

    # Quiet hours (enable + pick a quiet now; seed relative to it)
    os.environ["HAI_INITIATION_QUIET"] = "1"
    qnow = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    _seed(qnow, [("user", 200), ("persona", 200)])
    assert initiate.gate(PID, TEST_UID, now=qnow)[1] == "quiet hours"
    os.environ.pop("HAI_INITIATION_QUIET", None)

    # Passes when idle + cooldown clear, under cap, no backoff/pending
    _seed(now, [("user", 200), ("persona", 200)])
    assert initiate.gate(PID, TEST_UID, now=now) == (True, "ok")

    # Daily cap reached
    initiate.save_book(PID, TEST_UID,
                       {"last_initiated_ts": "", "last_considered_ts": "",
                        "count_today": 1, "day": initiate._today_str(now)})
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "daily cap reached"

    # Backoff after a recent "no"
    initiate.save_book(PID, TEST_UID,
                       {"last_initiated_ts": "", "last_considered_ts": (now - timedelta(seconds=5)).isoformat(),
                        "count_today": 0, "day": initiate._today_str(now)})
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "backoff after recent decision"

    # Pending initiation already queued (clear backoff first)
    initiate.save_book(PID, TEST_UID,
                       {"last_initiated_ts": "", "last_considered_ts": "",
                        "count_today": 0, "day": ""})
    from app.models import ScheduledReply
    schedule.enqueue(ScheduledReply(id="p1", persona_id=PID, user_id=TEST_UID,
                                    message="x", delay_bucket="immediate",
                                    created_ts=now.isoformat(), due_ts=now.isoformat(),
                                    kind="initiation", initiated_by="character"))
    assert initiate.gate(PID, TEST_UID, now=now)[1] == "initiation already pending"
    print("  [ok] gates: disabled, no-history, no-user, cooldown, idle, quiet, cap, backoff, pending")


def test_consider_yes_then_backoff():
    os.environ["HAI_INITIATION_MODE"] = "fast"
    os.environ["HAI_INITIATION_ENABLED"] = "1"
    initiate.THRESHOLDS_FAST = {"idle": 100, "cooldown": 10, "backoff": 50}
    now = datetime.now(timezone.utc)
    profs = load_all_profiles()
    pid = next(iter(profs))
    profile = profs[pid]

    orig_initiate, orig_record = llm.initiate, usage.record_call
    usage.record_call = lambda uid: None
    try:
        # YES path
        llm.initiate = lambda *a, **k: InitiationResponse(
            reach_out=True, message="hey — did you ever book that trip?", reason="open thread")
        _reset()
        for role, ago in [("user", 200), ("persona", 200)]:
            ts = (now - timedelta(seconds=ago)).isoformat()
            state.append_transcript(pid, TEST_UID, BufferMessage(role=role, text="hi", ts=ts))

        reached, _ = initiate.consider(profile, pid, TEST_UID, now=now)
        assert reached is True
        pending = [j for j in schedule.load_queue(pid, TEST_UID)
                   if j.kind == "initiation" and j.status == "pending"]
        assert len(pending) == 1 and pending[0].initiated_by == "character"
        assert "trip" in pending[0].message
        book = initiate.load_book(pid, TEST_UID)
        assert book["count_today"] == 1 and book["last_initiated_ts"]

        # Deliver it and confirm it lands as a character-initiated persona message.
        schedule._process_due(profs)
        s = state.load_state(pid, TEST_UID)
        assert s.short_buffer[-1].role == "persona"
        assert s.short_buffer[-1].initiated_by == "character"
        assert "trip" in s.short_buffer[-1].text

        # NO path → backoff, no enqueue
        llm.initiate = lambda *a, **k: InitiationResponse(reach_out=False, reason="nothing to say")
        now2 = now + timedelta(seconds=1)
        _reset()
        for role, ago in [("user", 200), ("persona", 200)]:
            ts = (now2 - timedelta(seconds=ago)).isoformat()
            state.append_transcript(pid, TEST_UID, BufferMessage(role=role, text="hi", ts=ts))
        reached, _ = initiate.consider(profile, pid, TEST_UID, now=now2)
        assert reached is False
        assert not [j for j in schedule.load_queue(pid, TEST_UID) if j.kind == "initiation"]
        # Second consider immediately after is blocked by backoff.
        assert initiate.gate(pid, TEST_UID, now=now2 + timedelta(seconds=1))[1] == "backoff after recent decision"
        print("  [ok] consider: yes → enqueue+deliver (initiated_by=character); no → backoff, no enqueue")
    finally:
        llm.initiate, usage.record_call = orig_initiate, orig_record
        shutil.rmtree(STATE_DIR / TEST_UID, ignore_errors=True)


def main():
    print("Testing character-initiated messaging…")
    orig_fast = dict(initiate.THRESHOLDS_FAST)
    try:
        test_timing()
        test_gates()
        test_consider_yes_then_backoff()
        print("All initiation tests passed ✅")
    finally:
        initiate.THRESHOLDS_FAST = orig_fast
        shutil.rmtree(STATE_DIR / TEST_UID, ignore_errors=True)


if __name__ == "__main__":
    main()
