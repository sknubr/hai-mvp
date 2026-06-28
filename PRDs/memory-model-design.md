# Memory Model — Design (MVP)

> Companion to `PRD-persona-loop-mvp.md`. This doc specs how memory works. Design rule: **the intelligence is in what we filter and retain, not in the architecture.** Start as simple as possible; the LLM does the hard judgment, the DB just stores hints.

---

## 1. Core idea (read this first)

Human-like memory here means **forgetting is the default and remembering is earned.** We get that almost for free:

- **Forgetting = not being carried forward.** During a periodic "sleep" (consolidation) step, the LLM rewrites memory into summaries. Anything it doesn't include is simply gone. There is **no decay formula and no timer math.**
- **A numeric salience score (0–100) is a hint, not a clock.** It's assigned by the LLM when a memory is written/consolidated, stored in a column, and used to (a) decide what to load into the consolidation prompt and (b) bias the keep/drop/merge judgment. It is never recomputed on a schedule.
- **Recall reinforces.** When a memory is actually used during chat, we bump its salience and stamp `last_recalled_at`. Reinforced memories survive the next sleep. This is "recall boosts half-life," implemented as a score bump.

That trio — **LLM consolidates, score guides, recall reinforces** — covers half-life, consolidation, and human-like retention without heavy machinery.

---

## 2. Inputs: what creates memories

Three event sources, with different default weight:

| Source | Default salience bias | Notes |
|---|---|---|
| **Conversations** | medium–high | What the user shares about themselves, emotional moments, commitments, recurring topics. |
| **External events** (simulated now; later a function of real events near them + their interests) | medium | The 3–5 events from `runCycle`. Some are mundane (low), some are formative (high) — LLM scores per event. |
| **Feedback on posts** | low (smaller impact, per spec) | Reactions/engagement. Logged, lightly memorable ("people liked when I talked about X"). Reaction→evolution stays out of scope per loop PRD; here it only seeds low-salience memories. |

---

## 3. The three tiers

| Tier | Holds | Lifespan | Form |
|---|---|---|---|
| **Working memory** | Current session / current day: raw recent messages + this cycle's events + freshly written memory items | Until next sleep | Raw-ish items + the live chat buffer |
| **Short-term memory** | Recent consolidated summary of the last few days | A few cycles, then folded up or dropped | Prose summary + surviving high-salience items |
| **Long-term memory** | Durable, identity-level facts and themes | Persistent | Bounded prose summary + a small set of high-salience pinned items |

**Identity note:** the canonical `digital-profile` is *not* memory — it's fixed context always supplied alongside these tiers (see loop PRD §3). Long-term memory is what the persona has *become*, layered on top of who they *are*.

---

## 4. How memories move (the flow)

```
chat / events / feedback
        │  (LLM writes memory items, assigns salience 0–100 + tags)
        ▼
   WORKING MEMORY  ──── recall during chat bumps salience + last_recalled_at
        │
        │  SLEEP / CONSOLIDATION  (cycle-triggered; threshold safety valve)
        │  LLM reads working + short-term, then:
        │    • keeps / merges salient items → short-term
        │    • drops low-salience, un-recalled items  (= forgetting)
        │    • promotes repeated/high-salience themes → long-term
        ▼
   SHORT-TERM  ──(repeated reinforcement / high salience)──►  LONG-TERM
```

### What moves vs. what doesn't
- **Moves up:** repeated themes, emotionally weighted moments, commitments/facts about the user, anything reinforced by recall, anything the LLM scores high.
- **Stays / fades:** one-off small talk, low-salience external events, post feedback — unless reinforced.
- **Deliberately retained oddities:** the consolidation prompt is told to **keep 1–2 "interesting but minor" details** even if low-salience, so the persona feels human and not purely optimized (your consideration #9).
- **Forgetting is fine.** Optimize for **general consistency, not perfect recall.** The prompt explicitly permits dropping detail.

---

## 5. When consolidation runs

Target: **cycle-triggered + threshold safety valve** (one consolidation function, two trigger conditions):

1. **Cycle ("advance a day") → sleep.** The natural consolidation point; reuses the existing loop trigger.
2. **Threshold:** if working-memory items exceed `N` (recommend ~30) before a cycle, run consolidation early. This is literally one extra `if` on the same function.

If the threshold path ever complicates the build, drop it — cycle-only is an acceptable fallback with no other changes.

---

## 6. Salience score (0–100)

- **Assigned by the LLM** at write time and re-evaluated at consolidation. Not computed by formula.
- **Used for:** (a) ordering/gating what loads into the consolidation prompt (load high first, cap the rest), (b) biasing keep/drop, (c) the target of recall reinforcement.
- **Coarse bands** (guidance for the prompt, not hard rules): 80–100 identity-level / strongly emotional / explicit user facts; 50–79 notable; 20–49 minor; 0–19 trivial.
- **Recall reinforcement:** on use during chat, bump salience (e.g. +10, capped 100) and set `last_recalled_at`. Reinforced items resist the next drop.

---

## 7. Memory tags (trust signals)

Each memory carries one trust tag so the agent knows how much to lean on it. **Memories are context, not commands** — the chat prompt is told to treat them as things the persona believes/recalls, weighted by tag, never as instructions to obey.

| Tag | Meaning | Agent trust |
|---|---|---|
| `verified` | Stated directly & clearly by the user, or a fixed event | High |
| `observed` | Seen in conversation/feed but not explicitly confirmed | Medium |
| `inferred` | The persona's own guess/interpretation | Low — hold loosely, may be wrong |
| `stale` | Was salient, now likely outdated | Low — flag rather than assert |

Tags are set at write time and can be updated at consolidation (e.g. an `observed` fact later confirmed → `verified`; an old fact → `stale`).

---

## 8. Storage (server + DB)

One table does most of the work. Keep it boring.

```
TABLE memories
  id              PK
  persona_id      FK
  tier            enum: working | short_term | long_term
  content         text            -- the memory itself (a sentence or two)
  salience        int   0–100
  tag             enum: verified | observed | inferred | stale
  source          enum: conversation | external_event | feedback
  created_at      timestamp
  last_recalled_at timestamp null
  reinforce_count int   default 0
  cycle_written   int             -- which cycle it came from
```

Plus the consolidated **prose summaries** per tier (short-term, long-term) — store as either tall rows in this table (a single `long_term` summary item) or a small `memory_summaries` table if you prefer summaries separate from items. Either is fine; don't over-design.

The **live chat buffer** (last N raw messages) can stay where the loop PRD already keeps it (runtime state) — it's working memory's rawest layer and doesn't need its own table.

---

## 9. What the agent sees while chatting (the payload)

This is where the value shows up. On each reply, assemble context in priority order, capped to a token budget:

1. `digital-profile` (fixed identity)
2. **long-term** summary (who they've become)
3. **short-term** summary (recent days)
4. **working memory** items relevant to the current message, highest salience first
5. live chat buffer (last N messages)

Relevance selection for (4) can start dumb: highest-salience + most-recent + simple keyword overlap with the user's message. **No embeddings/vector search in MVP** — add only if dumb selection visibly fails. Recall of any item here triggers reinforcement (§6).

---

## 10. Deliberately out of scope (for now)

- Vector/embedding retrieval — only if keyword+salience selection proves insufficient.
- Numeric time-decay formulas — replaced by LLM consolidation.
- Reaction→personality evolution — owned by loop PRD future scope; here feedback only seeds low-salience memories.
- Cross-persona / shared memory.
- Contradiction resolution beyond the `stale` tag.

---

## 11. Build sequencing

1. `memories` table + write path: after each chat turn / cycle, LLM emits memory items with `content`, `salience`, `tag`, `source`.
2. **Consolidation function** (the sleep step): load working + short-term by salience, prompt LLM to keep/merge/drop/promote and re-tag, write results back, retain 1–2 oddities. Wire to the cycle trigger.
3. **Recall reinforcement:** when an item is used in a reply, bump salience + stamp `last_recalled_at`.
4. **Context assembly (§9)** for chat, with dumb relevance selection.
5. Add the **threshold trigger** as one `if`. Observe a few cycles; tune `N`, salience bands, reinforcement bump.

**Success check (mirrors loop PRD signals):** persona recalls what matters, plausibly forgets trivia, stays consistent, and occasionally surfaces a charming minor detail — without perfect recall.
