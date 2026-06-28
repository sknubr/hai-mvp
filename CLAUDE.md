# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Subagent Execution Rules
- if sub-agents are needed preferred subagents per task: 1
- Always ask for explicit user confirmation before spawning any parallel subagents.
- subagents for generic codebase lookups or research tasks; execute them sequentially unless large benefits to doing so in parallel - in which case please ask. 


## Project status

This repo is in the **PRD / pre-code phase**. All design lives in `PRDs/`. No application code exists yet. When building, follow the sequencing in `PRDs/PRD-persona-loop-mvp.md §12`.

## What Hai is

Hai is an AI companion app. Users create a digital persona through an onboarding flow; the persona then **feels alive over time** — messaging asynchronously, accumulating experiences, forming preoccupations, and posting to a social feed. The MVP validates this core loop cheaply before any mobile investment.

## Two-PRD architecture

The system is split across two PRDs with a strict seam:

| PRD | Responsibility | Output artifact |
|---|---|---|
| `PRD-spawn-profile.md` | Profile creation (one-time) | `digital-profile-{name}+id.md` (read-only) |
| `PRD-persona-loop-mvp.md` | Runtime loop (ongoing) | Mutable `runtime-state-{id}.json` |

**The loop never mutates the digital profile.** All change lives in the runtime state. This separation is the key architectural invariant — violating it breaks the "consistent" success signal.

## Three LLM operations

All LLM work is single calls (no chaining):

1. **`generatePersona`** (spawn PRD) — onboarding answers → hydrated `digital-profile-{name}+id`
2. **`reply`** — `[digital-profile + runtime state + short buffer + new user message]` → reply text; roll async delay bucket; append to short buffer
3. **`runCycle`** — `[digital-profile + runtime state]` → structured response: 3–5 invented events + rewritten journal + updated mood + optional post. If post produced, append to `feed.csv`.

## Data model

### Canonical identity — `digital-profile-{name}+id.md` (read-only)
Schema defined in `PRDs/proto-profile-schema.md` = onboarding block + hydrated base-schema (8 categories from `PRDs/base-profile-schema.md`).

### Runtime state — one JSON file per persona (mutable)
```json
{
  "persona_id": "digital-profile-{name}+id",
  "cycle_count": 0,
  "mood": "",
  "journal": "",
  "recent_events": [{ "cycle": 0, "text": "" }],
  "short_buffer": [{ "role": "user|persona", "text": "", "ts": "", "delay_bucket": "" }]
}
```

### Feed and reactions (append-only CSVs)
- `feed.csv`: `post_id, persona_id, cycle, timestamp, post_text`
- `reactions.csv`: `reaction_id, post_id, persona_id, reaction_type, reaction_value, timestamp` (logged only in MVP — no feedback loop yet)

## Memory model (no vector DB)

- **Short-term buffer:** last N messages (recommend 10–20), passed verbatim into `reply`
- **Long-term journal:** LLM-maintained prose summary (~300–500 words), rewritten each `runCycle` — this is the persona's evolving memory
- `digital-profile` is fixed context, not memory

## Async delay mechanic

On each `reply`, draw uniformly from `[immediate, <10 min, 2 hours, 10 hours, 24 hours]` (p=0.20 each). Store bucket + synthetic `reply_timestamp` on the message. In MVP this is metadata only — no real scheduling.

## Onboarding attributes (from `PRDs/onboarding-questions.md`)

Six questions produce the onboarding block of the proto-profile:
- **gender**: Male / Female / You choose for me / Other
- **relationship_type**: Romantic Interest / Close Friend / Mentor/Coach / Daring Partner / Supportive Ally
- **conversation_dynamic**: I want to lead / You lead / Let's share the spotlight
- **energy_vibe**: Warm & affectionate / Cool & enigmatic / Playful & teasing / Deep & philosophical / Bold & provocative
- **communication_style**: object with `language`, `approach`, `focus`, `expression` enums
- **personality_traits**: 5 sliders (0–100): serious_humorous, logical_intuitive, deferential_assertive, predictable_spontaneous, grounded_imaginative

## Recommended build sequence

1. Runtime state JSON schema + load/save utilities against an existing `digital-profile`
2. `runCycle` — validate the "alive" signal first (review after 5 cycles before building further)
3. `reply` + short buffer + delay bucket + minimal single-page chat UI
4. `feed.csv` append on post; `reactions.csv` logging
5. Operator loop: message ↔ advance-cycle; evaluate against the three success signals (alive / consistent / not stale)

## Success signals (qualitative, reviewed by operator)

| Signal | Lightweight check |
|---|---|
| **Alive** | Over 5 cycles, does the persona surface new plausible self-generated events in chat/posts? |
| **Consistent** | Does tone/values match the `digital-profile` and stay stable? No contradictions of fixed facts. |
| **Not stale** | Do replies/posts avoid repetition and reflect recent journal state? |

## Key risks to watch

- `runCycle` invented events going generic — if "alive" fails, iterate the prompt before building anything else
- Journal drift eroding identity over many cycles — always re-supply `digital-profile` as fixed context
- Chat vs. feed voice diverging — share the same identity/voice block in both prompts
