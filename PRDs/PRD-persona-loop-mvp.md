# PRD: Persona Loop MVP (Hai)

> **Scope of this PRD.** This document owns the **runtime loop** of a Hai companion: messaging, simulated evolution, social-feed posting, human reactions, and memory. It does **not** own profile creation. Profile spawning is defined in `PRD-spawn-profile.md`, which produces a `digital-profile-{name}+id` artifact. This PRD **consumes** that artifact as the persona's starting identity. See [§3 Seam with spawn-profile PRD](#3-seam-with-spawn-profile-prd).

---

## 1. Overview & value proposition

Hai lets a user create an AI companion ("persona") whose identity is seeded from onboarding choices plus generatively-hydrated attributes. Unlike a static chatbot, the persona **feels alive over time**: it messages asynchronously, accumulates experiences, forms current preoccupations, and posts to a social feed that humans can react to.

The defensible value is **a persona that evolves and stays coherent** — not the chat surface. The MVP exists to validate that core loop cheaply, before any mobile/messaging investment.

### What this MVP is deliberately NOT
- Not a polished mobile or messaging product.
- Not real-time async (delays are simulated metadata, not actual waits — see [§6](#6-asynchronous-delay-mechanic)).
- Not ingesting real-world events (the persona **invents** plausible events — see [§5.3](#53-runcycle)).
- Not mutating canonical identity (base-schema fields stay fixed; only runtime state drifts).
- Not closing the reaction→evolution loop yet (reactions are logged only — see [§9](#9-data-model)).

---

## 2. Goals & success signals

The MVP is judged on three qualitative signals. Each has a lightweight check so we can tell if it's working.

| Signal | What it means | Lightweight check |
|---|---|---|
| **Alive** | Persona acts unprompted: invents experiences, posts, references its "days." | Over 5 cycles, does the persona surface new, plausible self-generated events that show up in chat/posts? |
| **Consistent** | Personality, voice, and identity hold across time and across surfaces (chat vs. feed). | Spot-check: does tone/values match the `digital-profile` and stay stable across cycles? No contradictions of fixed facts. |
| **Not stale** | Conversations and posts don't loop or feel canned. | Across a session, do replies/posts avoid repetition and reflect recent journal state? |

These are review heuristics for the builder/operator, not automated metrics in MVP.

---

## 3. Seam with spawn-profile PRD

`PRD-spawn-profile.md` is the source of truth for profile creation. It outputs a `digital-profile-{name}+id` (per its non-online `.md` flow or online DB flow), combining:
- **onboarding attributes** (finite enums + 5 trait sliders) — see `onboarding-questions.md`
- **hydrated base-schema attributes** (8 categories, generatively filled) — see `base-profile-schema.md`
- a **name** and incrementing **id**

**Contract for this PRD:** the loop receives a fully-hydrated `digital-profile-{name}+id` as **read-only canonical identity** (the "birth certificate"). The loop never edits it. All change lives in a separate **runtime state** object (the "diary") — see [§9](#9-data-model). This keeps personas consistent (a success signal) while letting them evolve.

If a persona is needed and none exists, the loop defers to the spawn-profile flow; it does not generate identities itself.

---

## 4. Core loop

```
        ┌─────────────────────────────────────────────────────┐
        │  digital-profile-{name}+id   (read-only identity)    │
        └───────────────────────────┬─────────────────────────┘
                                     │ seeds
                                     ▼
   ┌──────────┐    ┌──────────────────────────────┐    ┌─────────────┐
   │  reply   │◄──►│   runtime state (the diary)   │◄──►│  runCycle   │
   │ (chat)   │    │ journal · mood · buffer · evts│    │ "advance a  │
   └────┬─────┘    └──────────────┬───────────────┘    │    day"     │
        │                         │                     └──────┬──────┘
        │ delay-stamped           │ may emit                   │ invents 3–5
        ▼                         ▼                            ▼ events,
   user reads reply        feed.csv (posts) ◄── humans react (reactions.csv, logged only)
```

The operator drives two actions: **message the persona** (any time) and **advance a cycle** (when they want the world to move; default 1 cycle = 1 notional day). A cycle invents events, updates the journal/mood, and may post.

---

## 5. The three LLM operations

All three are single LLM calls. `generatePersona` is owned by the spawn PRD and listed here only for completeness of the seam.

### 5.1 generatePersona — (owned by spawn-profile PRD)
- **In:** onboarding answers (+ optional simulation flag).
- **Out:** `digital-profile-{name}+id`.
- **Note:** Not implemented in this PRD. Listed so the loop's input contract is explicit.

### 5.2 reply
Produces the persona's response to a user message.
- **In:** `digital-profile` (identity), runtime state (journal summary + recent **short-buffer** messages + current mood + recent simulated events), the new user message.
- **Out:** reply text; appended to the short buffer.
- **Prompt intent:** Stay in character per the `digital-profile` (voice from `communication_style`, `energy_vibe`, the 5 trait sliders, relationship_type). Naturally reference recent journal/events when relevant. Honor `boundaries`/`triggers` from base-schema. Do **not** invent new fixed biography that contradicts the profile.
- **Then:** roll the async delay bucket ([§6](#6-asynchronous-delay-mechanic)) and stamp the reply.

### 5.3 runCycle
Advances the persona one notional day. **This is the heart of the MVP.**
- **In:** `digital-profile`, current runtime state.
- **Out (single structured response):**
  1. **3–5 simulated events** — plausible things that "happened to" or were "seen by" the persona this cycle, consistent with its interests/location/life. (Replaces real-world event ingestion.)
  2. **updated journal** — rewritten long-term self-summary integrating the new events and any salient recent conversation. Bounded length (see [§7](#7-memory-model)).
  3. **updated mood / current preoccupations** — a short delta of what's top-of-mind now.
  4. **post decision** — the persona **freely decides** whether to post this cycle; if yes, the post text. (Not forced, not probability-gated.)
- **Prompt intent:** Evolution is legible and incremental — small drift in mood/interests/preoccupations, never contradicting fixed identity. Events should be specific and ownable so they can resurface in chat and posts.
- **Then:** if a post was produced, append it to `feed.csv`.

---

## 6. Asynchronous delay mechanic

To test whether replies "feel like real messages," each reply is assigned a delay bucket — **metadata, not a real wait** in MVP.

- On each `reply`, draw uniformly from `[immediate, <10 min, 2 hours, 10 hours, 24 hours]`, **p = 0.20 each**.
- Store the bucket + a synthetic `reply_timestamp` on the message.
- The chat UI renders the reply with its delay label / staggered timestamp so the operator can feel the async texture.
- **Production path:** the bucket maps to an actual scheduled send; MVP only records it.

---

## 7. Memory model

Two layers only — no vector DB.

- **Short-term (working buffer):** the last **N messages** (recommend N = 10–20), stored raw, passed verbatim into `reply`. Cheap recency.
- **Long-term (journal):** an LLM-maintained prose self-summary, **rewritten each `runCycle`** to fold in new events and salient conversation. Bounded (recommend ~300–500 words) so it stays in-context and forces summarization rather than unbounded growth. This *is* the persona's evolving "memory."

The `digital-profile` identity is **not** memory — it's fixed context always supplied alongside these two layers.

---

## 8. Surfaces

| Surface | MVP form | Purpose |
|---|---|---|
| **Chat** | Minimal single-page web UI (message list, delay-stamped bubbles, input box) | Feel whether replies read like real async messages |
| **Cycle trigger** | A button / CLI command ("Advance a day") | Operator advances persona time on demand |
| **Feed** | `feed.csv` (or a sheet) — append-only rows of persona posts | Where persona posts land |
| **Reactions** | `reactions.csv` (or a dropdown column on the feed sheet) | Humans react; **logged only** in MVP |

Chat is the only built UI; feed/reactions are files/sheets to minimize dev.

---

## 9. Data model

### 9.1 Canonical identity (read-only) — from spawn PRD
`digital-profile-{name}+id.md` / JSON per `proto-profile-schema.md`: the `onboarding` block (enums + 5 trait sliders) plus hydrated `base_schema` (8 categories). **Never mutated by the loop.**

### 9.2 Runtime state (mutable) — owned by this PRD
**Storage decision:** one **JSON file per persona** for MVP — simplest, diff-able, no schema migrations. *Path to production: promote to the SQLite/DB record implied by the spawn PRD's online flow; the JSON shape below maps 1:1 to a row + child tables.*

```json
{
  "persona_id": "digital-profile-{name}+id",
  "cycle_count": 0,
  "mood": "",                      // short current-preoccupations string
  "journal": "",                   // bounded long-term self-summary (§7)
  "recent_events": [               // last cycle's 3–5 simulated events
    { "cycle": 0, "text": "" }
  ],
  "short_buffer": [                // last N messages (§7)
    { "role": "user|persona", "text": "", "ts": "", "delay_bucket": "" }
  ]
}
```

### 9.3 Feed — `feed.csv`
`post_id, persona_id, cycle, timestamp, post_text`

### 9.4 Reactions — `reactions.csv` (logged only)
`reaction_id, post_id, persona_id, reaction_type, reaction_value, timestamp`
> `reaction_type`/`value` left flexible (emoji, 👍 count, dropdown enum). **Hook for future:** schema already links reactions → post → persona, so reaction-driven evolution can be added without rework ([§10](#10-out-of-scope--future)).

---

## 10. Out of scope / future

- **Reaction-driven evolution** — feed `reactions.csv` aggregates into the next `runCycle` journal update. (Schema hook already present.)
- **Live real-world events** — replace simulated events with a curated/live news ingestion pipeline.
- **Real async scheduling** — delay buckets trigger actual delayed sends.
- **Mobile app + native messaging.**
- **Multi-user / multi-persona social graph** (personas reacting to each other).
- **Mutable identity** — allowing slow drift of base-schema fields with versioning.

---

## 11. Open questions & risks

1. **`runCycle` is the product.** If invented events feel generic, "alive" fails. May need few-shot examples grounded in the persona's specific interests/location. **Mitigation:** review after first 5 cycles; iterate the prompt before building anything else.
2. **Journal drift vs. consistency.** Over many cycles the bounded journal could erode identity. **Mitigation:** always re-supply `digital-profile` as fixed context; instruct summarizer to preserve core identity.
3. **N (buffer size) and journal length** are tuning knobs — defaults proposed in [§7](#7-memory-model), confirm during build.
4. **Post frequency** — "persona freely decides" could yield too few or too many posts. **Mitigation:** observe across cycles; add soft guidance to the prompt if degenerate.
5. **Voice consistency across surfaces** — chat vs. feed-post voice may diverge since they're different calls. **Mitigation:** share the same identity/voice block in both prompts.

---

## 12. Build sequencing (for Claude Code)

1. Define **runtime state** JSON + load/save against an existing `digital-profile`.
2. Implement **`runCycle`** (events + journal + mood + post decision) — validate "alive" first.
3. Implement **`reply`** + short buffer + **delay bucket** + minimal chat UI.
4. Wire **feed.csv** append on post; add **reactions.csv** (logging only).
5. Operator loop: message ↔ advance-cycle; review against the three success signals ([§2](#2-goals--success-signals)).

**Referenced docs:** `PRD-spawn-profile.md`, `proto-profile-schema.md`, `base-profile-schema.md`, `onboarding-questions.md`.
