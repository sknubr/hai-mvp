#!/usr/bin/env python3
"""
Deterministic tests for async delivery (no live LLM calls).
Covers: delay-bucket → seconds mapping, bucket selection override, queue
persistence, and the scheduler delivering a due job (monkeypatched LLM).

Usage:
  python scripts/test_schedule.py
"""
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import delays, llm, schedule, state, usage
from app.models import ScheduledReply
from app.state import STATE_DIR, load_all_profiles

TEST_UID = "schedule_test_user"


def test_delays():
    os.environ["HAI_DELAY_MODE"] = "fast"
    assert delays.bucket_seconds("immediate") == 0
    assert delays.bucket_seconds("<10 min") == 20
    os.environ["HAI_DELAY_MODE"] = "real"
    assert delays.bucket_seconds("2 hours") == 7200
    os.environ["HAI_DELAY_MODE"] = "fast"

    os.environ["HAI_FORCE_BUCKET"] = "10 hours"
    assert delays.pick_delay_bucket() == "10 hours"
    del os.environ["HAI_FORCE_BUCKET"]
    print("  [ok] delay mapping + forced bucket override")


def test_queue_roundtrip():
    pid = "digital-profile-test+999"
    job = ScheduledReply(id="j1", persona_id=pid, user_id=TEST_UID, user_message="hi",
                         delay_bucket="<10 min", created_ts="t", due_ts="t")
    schedule.enqueue(job)
    loaded = schedule.load_queue(pid, TEST_UID)
    assert len(loaded) == 1 and loaded[0].id == "j1"
    assert any(j.id == "j1" for j in schedule.all_pending_jobs())
    schedule._update_job(job, status="delivered")
    assert schedule.load_queue(pid, TEST_UID) == []
    print("  [ok] queue enqueue / scan / mark-delivered (drops job)")


def test_scheduler_delivers_due_job():
    # Monkeypatch the LLM + usage so no network/state pollution happens.
    orig_reply, orig_record = llm.reply, usage.record_call
    llm.reply = lambda *a, **k: "Sorry for the delay — was painting all afternoon."
    usage.record_call = lambda uid: None
    try:
        profs = load_all_profiles()
        pid = next(iter(profs))
        # A past-due job (simulates a restart catch-up).
        job = ScheduledReply(id="due1", persona_id=pid, user_id=TEST_UID,
                             user_message="how was your day?", delay_bucket="<10 min",
                             created_ts="2020-01-01T00:00:00+00:00",
                             due_ts="2020-01-01T00:00:00+00:00")
        schedule.enqueue(job)
        schedule._process_due(profs)

        assert not [j for j in schedule.all_pending_jobs() if j.user_id == TEST_UID], "queue not drained"
        s = state.load_state(pid, TEST_UID)
        assert s.short_buffer and s.short_buffer[-1].role == "persona", "reply not stored"
        assert "painting" in s.short_buffer[-1].text
        assert s.short_buffer[-1].delay_bucket == "<10 min"

        # A future-due job must NOT be delivered yet.
        future = ScheduledReply(id="fut1", persona_id=pid, user_id=TEST_UID,
                                user_message="later?", delay_bucket="24 hours",
                                created_ts=datetime.now(timezone.utc).isoformat(),
                                due_ts="2999-01-01T00:00:00+00:00")
        schedule.enqueue(future)
        schedule._process_due(profs)
        assert any(j.id == "fut1" for j in schedule.all_pending_jobs()), "future job wrongly delivered"
        print("  [ok] scheduler delivers due job, defers future job, survives 'restart'")
    finally:
        llm.reply, usage.record_call = orig_reply, orig_record


def main():
    print("Testing async delivery…")
    try:
        test_delays()
        test_queue_roundtrip()
        test_scheduler_delivers_due_job()
        print("All schedule tests passed ✅")
    finally:
        shutil.rmtree(STATE_DIR / TEST_UID, ignore_errors=True)


if __name__ == "__main__":
    main()
