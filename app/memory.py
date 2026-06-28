"""
Unified memory store (per PRDs/memory-model-design.md).

Owns all memory item I/O + logic. No LLM calls live here — these are pure
functions + file I/O, like state.py. The intelligence is in WHAT we filter and
retain (LLM-assigned salience + recall reinforcement + consolidation), not in
the machinery.

Two invariants from the PRD:
  • Salience is a hint, not a clock — assigned only at write/consolidation and
    bumped only by recall (reinforce). Never recomputed on a schedule/per-tick.
  • Relevance selection is "dumb": salience + recency + keyword overlap. No
    embeddings/vectors unless the dumb version visibly fails.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import Memory, MemoryDraft, MemoryStore
from app.state import STATE_DIR, DEFAULT_USER

# Caps (PRD §5/§8). WORKING_CAP doubles as the §5 threshold N.
WORKING_CAP = 30
SHORT_TERM_CAP = 25
LONG_TERM_PINNED_CAP = 12

# Recall reinforcement (PRD §6).
RECALL_BUMP = 10
RECALL_MAX = 100

# Promotion thresholds (PRD §4 — repeated reinforcement / high salience move up).
PROMOTE_SALIENCE = 80
PROMOTE_REINFORCE = 3

# Pruning (PRD §4 — low-salience, un-recalled items fade).
DROP_SALIENCE = 20
# Oddities: minor items kept anyway because they were recalled (feel human, PRD §4).
ODDITY_SALIENCE = 40

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "at",
    "for", "with", "is", "are", "was", "were", "be", "been", "am", "i", "you",
    "he", "she", "it", "we", "they", "me", "my", "your", "this", "that", "these",
    "those", "do", "did", "does", "have", "has", "had", "so", "as", "about",
    "what", "how", "when", "where", "who", "why", "not", "no", "yes", "im", "ive",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


# ─── Persistence ──────────────────────────────────────────────────────────────

def _path(persona_id: str, user_id: str = DEFAULT_USER) -> Path:
    d = STATE_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"memories-{persona_id}.json"


def load_store(persona_id: str, user_id: str = DEFAULT_USER) -> MemoryStore:
    path = _path(persona_id, user_id)
    if not path.exists():
        return MemoryStore(persona_id=persona_id)
    return MemoryStore.model_validate_json(path.read_text())


def save_store(store: MemoryStore, user_id: str = DEFAULT_USER) -> None:
    path = _path(store.persona_id, user_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(store.model_dump_json(indent=2))
    os.replace(tmp, path)


# ─── Write path (PRD §2) ──────────────────────────────────────────────────────

def _draft_to_memory(draft: MemoryDraft, cycle: int) -> Memory:
    return Memory(
        id=new_id(),
        tier="working",
        content=draft.content,
        salience=draft.salience,
        tag=draft.tag,
        source=draft.source,
        cycle_written=cycle,
        created_at=_now_iso(),
    )


def write_items(store: MemoryStore, drafts: list[MemoryDraft], cycle: int) -> MemoryStore:
    """Append new working-tier memories from drafts; enforce the working cap."""
    items = list(store.items) + [_draft_to_memory(d, cycle) for d in drafts]
    return _enforce_caps(store.model_copy(update={"items": items}))


# ─── Recall + reinforcement (PRD §6 + §9) ─────────────────────────────────────

def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOPWORDS and len(t) > 2}


def select_relevant(store: MemoryStore, user_message: str, current_cycle: int, k: int = 6) -> list[Memory]:
    """Dumb relevance: salience + recency + keyword overlap. No embeddings (PRD §9).
    Pulls from working + short_term; long_term enters chat via the prose summary."""
    pool = [m for m in store.items if m.tier in ("working", "short_term")]
    if not pool:
        return []
    q = _tokens(user_message)
    span = max(current_cycle, 1)

    def score(m: Memory) -> float:
        sal = m.salience / 100.0
        recency = 1.0 - min(max(current_cycle - m.cycle_written, 0), span) / span
        overlap = len(_tokens(m.content) & q) / len(q) if q else 0.0
        return 0.45 * sal + 0.25 * recency + 0.30 * overlap

    ranked = sorted(pool, key=score, reverse=True)
    return ranked[:k]


def reinforce(store: MemoryStore, recalled: list[Memory]) -> MemoryStore:
    """Bump salience + stamp last_recalled_at for items actually surfaced in a reply.
    The ONLY place salience changes outside write/consolidation."""
    ids = {m.id for m in recalled}
    if not ids:
        return store
    now = _now_iso()
    items = []
    for m in store.items:
        if m.id in ids:
            m = m.model_copy(update={
                "salience": min(RECALL_MAX, m.salience + RECALL_BUMP),
                "last_recalled_at": now,
                "reinforce_count": m.reinforce_count + 1,
            })
        items.append(m)
    return store.model_copy(update={"items": items})


# ─── Consolidation / "sleep" (PRD §4 + §5) ────────────────────────────────────

def consolidate(
    store: MemoryStore,
    new_memories: list[MemoryDraft],
    consolidated_memory: list[MemoryDraft],
    short_term_summary: str,
    cycle: int,
) -> MemoryStore:
    """Apply the LLM's sleep output deterministically:
      • keep existing long_term (pinned) items
      • replace short_term with the LLM's consolidated set
      • add this cycle's new memories as working items
      • promote high-salience / well-reinforced items up a tier
      • retain 1–2 low-salience-but-recalled oddities (PRD §4)
      • enforce caps (drop lowest-salience first)
    The LLM returns the new STATE of short-term memory as content (no fragile id
    round-tripping); recall reinforcement flows in via the salience we fed it.
    """
    long_term = [m for m in store.items if m.tier == "long_term"]

    # Oddities: low-salience items that were nonetheless recalled — keep a couple
    # so the persona feels human, not purely optimized.
    oddities = [
        m for m in store.items
        if m.tier in ("working", "short_term") and m.salience < ODDITY_SALIENCE and m.reinforce_count > 0
    ]
    oddities = sorted(oddities, key=lambda m: m.last_recalled_at or "", reverse=True)[:2]

    short_term = [
        Memory(id=new_id(), tier="short_term", content=d.content, salience=d.salience,
               tag=d.tag, source=d.source, cycle_written=cycle, created_at=_now_iso())
        for d in consolidated_memory
    ]
    working = [_draft_to_memory(d, cycle) for d in new_memories]

    items = long_term + short_term + working + oddities

    # Promote (PRD §4): repeated reinforcement / high salience move up a tier.
    promoted = []
    for m in items:
        if m.tier == "short_term" and (m.salience >= PROMOTE_SALIENCE or m.reinforce_count >= PROMOTE_REINFORCE):
            m = m.model_copy(update={"tier": "long_term"})
        elif m.tier == "working" and (m.salience >= PROMOTE_SALIENCE or m.reinforce_count >= PROMOTE_REINFORCE):
            m = m.model_copy(update={"tier": "short_term"})
        promoted.append(m)

    updated = store.model_copy(update={"items": promoted, "short_term_summary": short_term_summary})
    return _enforce_caps(updated)


def _enforce_caps(store: MemoryStore) -> MemoryStore:
    """Bound each tier; drop lowest-salience (then oldest) first. = forgetting."""
    def cap_tier(tier: str, limit: int) -> list[Memory]:
        tier_items = [m for m in store.items if m.tier == tier]
        if len(tier_items) <= limit:
            return tier_items
        ranked = sorted(tier_items, key=lambda m: (m.salience, m.cycle_written), reverse=True)
        return ranked[:limit]

    kept = (
        cap_tier("working", WORKING_CAP)
        + cap_tier("short_term", SHORT_TERM_CAP)
        + cap_tier("long_term", LONG_TERM_PINNED_CAP)
    )
    return store.model_copy(update={"items": kept})


# ─── Display helper (for /inner) ──────────────────────────────────────────────

def tier_counts(store: MemoryStore) -> dict[str, int]:
    counts = {"working": 0, "short_term": 0, "long_term": 0}
    for m in store.items:
        counts[m.tier] = counts.get(m.tier, 0) + 1
    return counts
