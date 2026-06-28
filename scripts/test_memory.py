#!/usr/bin/env python3
"""
Deterministic tests for the unified memory store (no LLM calls).
Exercises the PRD invariants: write → recall reinforces → consolidation
keeps/drops/promotes → caps → oddity retention.

Usage:
  python scripts/test_memory.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import memory
from app.models import MemoryDraft, MemoryStore


def test_write_and_recall_reinforces():
    s = MemoryStore(persona_id="p")
    s = memory.write_items(s, [
        MemoryDraft(content="Sat is preparing for a PhD viva on Thursday", salience=70,
                    tag="verified", source="conversation"),
        MemoryDraft(content="Nadia repotted her basil on the windowsill", salience=30,
                    tag="observed", source="external_event"),
    ], cycle=1)
    assert len(s.items) == 2 and all(m.tier == "working" for m in s.items)

    sel = memory.select_relevant(s, "how did the viva go on thursday?", current_cycle=1)
    assert sel and "viva" in sel[0].content, "keyword overlap should surface the viva memory first"

    before = sel[0].salience
    s = memory.reinforce(s, sel)
    bumped = next(m for m in s.items if m.content == sel[0].content)
    assert bumped.salience == min(100, before + memory.RECALL_BUMP), "recall should bump salience"
    assert bumped.reinforce_count == 1 and bumped.last_recalled_at, "recall should stamp reinforcement"
    print("  [ok] write + dumb recall + reinforcement")


def test_consolidation_promotes_drops_and_keeps_oddity():
    s = MemoryStore(persona_id="p")
    # Seed working/short-term items: one high-salience, one trivial-but-recalled oddity.
    s = memory.write_items(s, [
        MemoryDraft(content="user's mother is seriously ill", salience=90, tag="verified", source="conversation"),
        MemoryDraft(content="user mentioned liking the colour teal", salience=10, tag="observed", source="conversation"),
    ], cycle=1)
    # Recall the trivial one so it becomes a protected oddity.
    teal = [m for m in s.items if "teal" in m.content]
    s = memory.reinforce(s, teal)

    # Sleep: LLM returns a consolidated short-term set + a new working memory.
    s = memory.consolidate(
        store=s,
        new_memories=[MemoryDraft(content="user started a new job today", salience=75,
                                  tag="verified", source="conversation")],
        consolidated_memory=[MemoryDraft(content="user's mother is seriously ill", salience=90,
                                         tag="verified", source="conversation")],
        short_term_summary="The user is going through a hard family stretch but just landed a job.",
        cycle=2,
    )
    contents = [m.content for m in s.items]
    # High-salience consolidated item promoted to long_term (>= PROMOTE_SALIENCE).
    ill = next(m for m in s.items if "mother" in m.content)
    assert ill.tier == "long_term", f"high-salience item should promote, got {ill.tier}"
    # Oddity retained despite being trivial, because it was recalled.
    assert any("teal" in c for c in contents), "recalled oddity should survive consolidation"
    assert s.short_term_summary.startswith("The user is going"), "short-term summary stored"
    print("  [ok] consolidation promotes high-salience, keeps recalled oddity, stores summary")


def test_caps_drop_lowest_salience():
    s = MemoryStore(persona_id="p")
    drafts = [MemoryDraft(content=f"trivial fact {i}", salience=i % 50, source="conversation")
              for i in range(memory.WORKING_CAP + 15)]
    s = memory.write_items(s, drafts, cycle=1)
    working = [m for m in s.items if m.tier == "working"]
    assert len(working) == memory.WORKING_CAP, f"working tier not capped: {len(working)}"
    # Lowest-salience items should have been dropped (min surviving >= dropped max).
    assert min(m.salience for m in working) > 0, "lowest-salience items should be dropped first"
    print(f"  [ok] working tier capped at {memory.WORKING_CAP}, lowest salience dropped")


def main():
    print("Testing unified memory store…")
    test_write_and_recall_reinforces()
    test_consolidation_promotes_drops_and_keeps_oddity()
    test_caps_drop_lowest_salience()
    print("All memory tests passed ✅")


if __name__ == "__main__":
    main()
