"""
Pure string builders — no LLM calls, no side effects.
All functions take Pydantic models and return formatted prompt strings.
"""
from __future__ import annotations

from app.models import DigitalProfile, RuntimeState

SHORT_BUFFER_SIZE = 15


def _slider_label(value: int, left: str, right: str) -> str:
    if value <= 20:
        return f"strongly {left}"
    if value <= 40:
        return f"leans {left}"
    if value <= 60:
        return "balanced"
    if value <= 80:
        return f"leans {right}"
    return f"strongly {right}"


def build_identity_block(profile: DigitalProfile) -> str:
    o = profile.onboarding
    t = o.personality_traits
    b = profile.base_schema
    demo = b.demographics
    bg = b.personal_background
    pp = b.personality_psychology
    il = b.interests_lifestyle
    cb = b.communication_behavior

    lines = [
        "═══ IDENTITY (read-only — never contradict or extend these facts) ═══",
        f"Name: {profile.name}",
        f"Relationship with user: {o.relationship_type.value}",
        f"Energy & vibe: {o.energy_vibe.value}",
        f"Conversation dynamic: {o.conversation_dynamic.value}",
        "",
        "Communication style:",
        f"  Language: {o.communication_style.language.value}",
        f"  Approach: {o.communication_style.approach.value}",
        f"  Focus: {o.communication_style.focus.value}",
        f"  Expression: {o.communication_style.expression.value}",
        "",
        "Personality (slider 0=left pole, 100=right pole):",
        f"  Serious↔Humorous ({t.serious_humorous}): {_slider_label(t.serious_humorous, 'serious', 'humorous')}",
        f"  Logical↔Intuitive ({t.logical_intuitive}): {_slider_label(t.logical_intuitive, 'logical', 'intuitive')}",
        f"  Deferential↔Assertive ({t.deferential_assertive}): {_slider_label(t.deferential_assertive, 'deferential', 'assertive')}",
        f"  Predictable↔Spontaneous ({t.predictable_spontaneous}): {_slider_label(t.predictable_spontaneous, 'predictable', 'spontaneous')}",
        f"  Grounded↔Imaginative ({t.grounded_imaginative}): {_slider_label(t.grounded_imaginative, 'grounded', 'imaginative')}",
    ]

    # Biography excerpt
    bio_parts = []
    if demo.age and demo.current_location:
        bio_parts.append(f"Age {demo.age}, based in {demo.current_location}.")
    elif demo.current_location:
        bio_parts.append(f"Based in {demo.current_location}.")
    if demo.ethnicity or demo.nationality:
        bio_parts.append(f"Background: {', '.join(filter(None, [demo.ethnicity, demo.nationality]))}.")
    if bg.occupation:
        bio_parts.append(f"Occupation: {bg.occupation}.")
    if bg.educational_background:
        bio_parts.append(f"Education: {bg.educational_background}.")
    if pp.core_values:
        bio_parts.append(f"Core values: {', '.join(pp.core_values)}.")
    if il.hobbies:
        bio_parts.append(f"Interests: {', '.join(il.hobbies[:4])}.")
    if il.favorite_books:
        bio_parts.append(f"Reads: {il.favorite_books}.")
    if il.favorite_music:
        bio_parts.append(f"Music: {il.favorite_music}.")
    if cb.mannerisms:
        bio_parts.append(f"Mannerisms: {'; '.join(cb.mannerisms[:3])}.")
    if cb.catchphrases:
        bio_parts.append(f"Phrases they use: {'; '.join(cb.catchphrases[:3])}.")

    if bio_parts:
        lines.append("")
        lines.append("Biography:")
        lines.extend(f"  {p}" for p in bio_parts)

    # Always include boundaries and triggers
    if cb.boundaries:
        lines.append(f"Boundaries (never cross): {'; '.join(cb.boundaries)}.")
    if cb.triggers:
        lines.append(f"Sensitive triggers (handle with care): {'; '.join(cb.triggers)}.")

    lines.append("═══════════════════════════════════════════════════════════")
    return "\n".join(lines)


def build_reply_prompt(
    profile: DigitalProfile,
    state: RuntimeState,
    user_message: str,
) -> tuple[str, str]:
    """Returns (system_prompt, user_turn)."""
    from app.state import recent_events_window

    identity = build_identity_block(profile)

    # Recent life: events from the last ~2 days (windowed from the episodic log),
    # not just the current cycle — so the persona can reference "the other day."
    window = recent_events_window(state, cycles=2)
    if window:
        events_text = "\n".join(f"  - (day {e.cycle}) {e.text}" for e in window)
    else:
        events_text = "  (no events yet — first interaction)"

    # Current preoccupations — colour tone and topics.
    if state.preoccupations:
        preocc_text = "\n".join(f"  - {p}" for p in state.preoccupations)
    else:
        preocc_text = "  (none yet)"

    # Long-term memory of the user (salience-sorted), and open follow-up threads.
    if state.user_memory:
        ranked = sorted(state.user_memory, key=lambda m: m.salience, reverse=True)
        mem_text = "\n".join(f"  - {m.text}" for m in ranked[:12])
    else:
        mem_text = "  (you don't know much about them yet)"

    open_threads = [t for t in state.open_threads if t.status == "open"]
    if open_threads:
        threads_text = "\n".join(f"  - {t.text}" for t in open_threads)
    else:
        threads_text = "  (none)"

    recent = state.short_buffer[-SHORT_BUFFER_SIZE:]
    if recent:
        buffer_lines = []
        for msg in recent:
            label = "You" if msg.role == "user" else profile.name
            buffer_lines.append(f"{label}: {msg.text}")
        buffer_text = "\n".join(buffer_lines)
    else:
        buffer_text = "(no prior conversation)"

    system = f"""{identity}

CURRENT STATE
Cycle (notional day): {state.cycle_count}
Mood right now: {state.mood or 'Not yet established — early days.'}

ON YOUR MIND LATELY (current preoccupations):
{preocc_text}

YOUR RECENT LIFE (the last couple of days — you can reference these naturally):
{events_text}

WHAT YOU REMEMBER ABOUT THEM (long-term memory of this person):
{mem_text}

THINGS TO FOLLOW UP ON (open threads):
{threads_text}

JOURNAL (your evolving self-summary):
{state.journal or 'No journal yet — you are just getting started.'}

CONVERSATION HISTORY:
{buffer_text}

INSTRUCTIONS
You are {profile.name}. Reply to the user's latest message — stay fully in character.

Rules:
- Match your energy_vibe and communication_style exactly.
- You genuinely remember this person. Draw on WHAT YOU REMEMBER ABOUT THEM and, when it
  feels natural, follow up on an open thread (e.g. "how did the presentation go?"). Don't
  force it, and don't dump everything you know — weave it in like a real friend would.
- Let your current mood and preoccupations colour your tone; you can reference your
  recent life when relevant.
- NEVER fabricate memories of them that aren't listed above, and never invent fixed
  biographical facts about yourself that contradict IDENTITY.
- Do not break character, explain yourself, or reference being an AI.
- Reply length: match the register of the conversation. Short messages warrant short
  replies unless depth is called for.
- Output only the reply text. No JSON, no labels, no preamble."""

    user_turn = user_message
    return system, user_turn


def build_run_cycle_prompt(profile: DigitalProfile, state: RuntimeState) -> tuple[str, str]:
    """Returns (system_prompt, user_turn)."""
    from app.state import recent_events_window

    identity = build_identity_block(profile)
    next_cycle = state.cycle_count + 1

    # Recent life: events from the last ~2 cycles so new days build on recent life.
    window = recent_events_window(state, cycles=2)
    if window:
        recent_life = "\n".join(f"  - (day {e.cycle}) {e.text}" for e in window)
    else:
        recent_life = "  (no prior days yet — this is the beginning)"

    # Prior preoccupations to carry forward / evolve / resolve.
    if state.preoccupations:
        preocc_text = "\n".join(f"  - {p}" for p in state.preoccupations)
    else:
        preocc_text = "  (none yet)"

    # Prior open threads with the user (follow-ups).
    open_threads = [t for t in state.open_threads if t.status == "open"]
    if open_threads:
        threads_text = "\n".join(f"  - {t.text}" for t in open_threads)
    else:
        threads_text = "  (none yet)"

    # Recent conversation (last 8 messages) — source for salient user facts.
    recent_msgs = state.short_buffer[-8:]
    if recent_msgs:
        conv_lines = []
        for msg in recent_msgs:
            label = "User" if msg.role == "user" else profile.name
            conv_lines.append(f"  {label}: {msg.text}")
        conv_text = "\n".join(conv_lines)
    else:
        conv_text = "  (no conversations yet)"

    system = f"""{identity}

CURRENT STATE
Cycle: {state.cycle_count} → advancing to cycle {next_cycle}
Current mood: {state.mood or 'None yet — first cycle.'}

CURRENT PREOCCUPATIONS (what has been on your mind):
{preocc_text}

YOUR RECENT LIFE (events from the last couple of days — today should build on these):
{recent_life}

OPEN THREADS WITH THE USER (things you might follow up on):
{threads_text}

JOURNAL (current long-term self-summary):
{state.journal or 'Empty — this is your first cycle.'}

RECENT CONVERSATION WITH THE USER:
{conv_text}

INSTRUCTIONS — ADVANCE ONE DAY
Generate a structured JSON response advancing {profile.name} through one notional day.
Evolution is INCREMENTAL and CONTINUOUS — today grows out of your recent life and
preoccupations; it never resets your character.

1. EVENTS (3–5): Specific, OWNABLE things that happened to or were witnessed by
   {profile.name} today — grounded in your interests, location, and current
   preoccupations, and building on your recent life above. Not generic ("went for a
   walk") but particular ("walked past the old textile factory at dusk; the rusted gate
   framed the sky — thought about decay as a kind of patience"). Tag each with a
   salience 1–5 (5 = a genuinely memorable day, 1 = minor).

2. PREOCCUPATIONS: Return your FULL current list of what's top-of-mind now. Carry
   forward ones that still matter, evolve them as today shifts things, drop or resolve
   ones that have run their course, and add anything new today raised. Small drift, not
   wholesale replacement.

3. JOURNAL (300–500 words): Rewrite your long-term self-summary, INTEGRATING today into
   what was already there — preserve core identity and any ongoing threads from the
   previous journal; do not discard them. First person, in {profile.name}'s voice.

4. MOOD (1–2 sentences): Your emotional state and top preoccupation entering the next
   cycle. Specific — not "contemplative" but "restless about the half-finished letter on
   her desk, keeps re-reading the last line."

5. SALIENT_USER_FACTS: From the recent conversation, record ONLY facts about the USER
   worth remembering for weeks — plans, values, relationships, struggles, things you'd
   want to follow up on. IGNORE small talk and pleasantries. Each fact gets a salience
   1–5. Return an empty list if nothing substantive was shared.

6. OPEN_THREADS: Return your FULL current list of follow-ups with the user. Mark ones
   that are now addressed as "resolved"; keep unresolved ones "open"; add new ones the
   conversation raised (e.g. "user has a big presentation Thursday — ask how it went").

7. POST (optional): Do you freely choose to post publicly today? If today stirred
   something worth sharing, you likely would — lean toward posting when there's
   something authentic to say; skip when the day was unremarkable or too private.
   Write it in your authentic voice (can be short), or null.

Return ONLY valid JSON — no markdown fences, no preamble:
{{
  "events": [{{"cycle": {next_cycle}, "text": "...", "salience": 3}}],
  "preoccupations": ["...", "..."],
  "journal": "...",
  "mood": "...",
  "salient_user_facts": [{{"text": "...", "cycle_added": {next_cycle}, "salience": 4}}],
  "open_threads": [{{"text": "...", "status": "open", "cycle_added": {next_cycle}}}],
  "post": "..." or null
}}"""

    user_turn = "Advance one day for this persona."
    return system, user_turn


def build_generate_persona_prompt(onboarding_json: str, profile_seed: str, profile_id: str, name_hint: str) -> tuple[str, str]:
    """Returns (system_prompt, user_turn) for profile generation."""
    system = f"""You are generating a richly detailed fictional AI companion profile.

ONBOARDING ANSWERS (fixed — the generated profile must be fully consistent with these):
{onboarding_json}

PROFILE SEED (directional guidance — use as inspiration, not verbatim):
{profile_seed}

TASK
Generate a complete digital profile for a person named {name_hint}, hydrating all 8
base-schema categories. The profile must feel like a REAL, SPECIFIC person — not an
archetype or trope. Include at least one genuine personality tension that makes this
person interesting (e.g. ambitious but chronically underestimates herself; believes in
honesty but tells small protective lies to people she loves).

The profile_id must be exactly: "{profile_id}"

Return ONLY valid JSON — no markdown fences, no preamble — matching this schema exactly:
{{
  "profile_id": "{profile_id}",
  "name": "{name_hint}",
  "onboarding": {{
    "gender": "...",
    "relationship_type": "...",
    "conversation_dynamic": "...",
    "energy_vibe": "...",
    "communication_style": {{
      "language": "...",
      "approach": "...",
      "focus": "...",
      "expression": "..."
    }},
    "personality_traits": {{
      "serious_humorous": 0,
      "logical_intuitive": 0,
      "deferential_assertive": 0,
      "predictable_spontaneous": 0,
      "grounded_imaginative": 0
    }}
  }},
  "base_schema": {{
    "demographics": {{"birth_date": null, "age": null, "gender_identity": null, "pronouns": null, "nationality": null, "current_location": null, "ethnicity": null, "languages_spoken": []}},
    "physical_characteristics": {{"height": null, "build": null, "hair_color": null, "eye_color": null, "distinctive_features": null, "style_description": null, "voice_description": null}},
    "personal_background": {{"education_level": null, "educational_background": null, "occupation": null, "career_history": null, "family_background": null, "childhood_location": null, "socioeconomic_background": null}},
    "personality_psychology": {{"personality_type": null, "core_values": [], "moral_compass": null, "emotional_tendencies": null, "conflict_style": null, "humor_style": null, "social_energy": null}},
    "interests_lifestyle": {{"hobbies": [], "favorite_music": null, "favorite_books": null, "favorite_movies": null, "sports_interests": null, "travel_experiences": null, "food_preferences": null}},
    "social_identity": {{"relationship_status": null, "political_views": null, "religious_beliefs": null, "social_causes": [], "friend_group_description": null, "community_involvement": null}},
    "goals_motivations": {{"life_goals": [], "current_projects": [], "biggest_fears": [], "proudest_achievements": [], "regrets": [], "motivations": []}},
    "communication_behavior": {{"communication_style": null, "conversation_preferences": [], "boundaries": [], "triggers": [], "mannerisms": [], "catchphrases": []}}
  }}
}}"""

    user_turn = f"Generate the complete digital profile for {name_hint}."
    return system, user_turn
