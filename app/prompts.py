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
    identity = build_identity_block(profile)

    events_text = ""
    if state.recent_events:
        events_text = "\n".join(f"  - {e.text}" for e in state.recent_events)
    else:
        events_text = "  (no events yet — first interaction)"

    buffer_text = ""
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
Cycle: {state.cycle_count}
Mood & preoccupations: {state.mood or 'Not yet established — early days.'}
Recent events (this cycle):
{events_text}

JOURNAL (your evolving self-summary — long-term memory):
{state.journal or 'No journal yet — you are just getting started.'}

CONVERSATION HISTORY:
{buffer_text}

INSTRUCTIONS
You are {profile.name}. Reply to the user's latest message — stay fully in character.

Rules:
- Match your energy_vibe and communication_style exactly.
- Draw naturally on your mood, recent events, or journal when it fits — do not force it,
  but let your current state colour your response.
- Never invent new fixed biographical facts that contradict IDENTITY.
- Do not break character, explain yourself, or reference being an AI.
- Reply length: match the register of the conversation. Short messages warrant short
  replies unless depth is called for.
- Output only the reply text. No JSON, no labels, no preamble."""

    user_turn = user_message
    return system, user_turn


def build_run_cycle_prompt(profile: DigitalProfile, state: RuntimeState) -> tuple[str, str]:
    """Returns (system_prompt, user_turn)."""
    identity = build_identity_block(profile)

    next_cycle = state.cycle_count + 1

    # Last 5 messages for context
    recent_msgs = state.short_buffer[-5:]
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
Mood & preoccupations: {state.mood or 'None yet — first cycle.'}

JOURNAL (current long-term self-summary):
{state.journal or 'Empty — this is your first cycle.'}

RECENT CONVERSATION HIGHLIGHTS:
{conv_text}

INSTRUCTIONS — ADVANCE ONE DAY
Generate a structured JSON response advancing {profile.name} through one notional day.

1. EVENTS (3–5 items): Invent specific, plausible things that happened to or were
   witnessed by {profile.name} today. Ground each in their interests, location, and
   current preoccupations. Events must be SPECIFIC and OWNABLE — not generic
   ("went for a walk") but particular
   ("walked past the old textile factory at dusk and noticed the way the rusted gate
   framed the sky — thought about decay as a kind of patience").
   These events should be usable as conversation material in future chat replies.

2. JOURNAL (300–500 words): Rewrite the long-term self-summary integrating today's
   events and any salient conversation. Preserve core identity — drift is incremental
   (new interests, shifting preoccupations, small mood changes), never character
   reversals. Write in first person, in {profile.name}'s voice, as a private reflection.

3. MOOD (1–2 sentences): {profile.name}'s current emotional state and top preoccupation
   entering the next cycle. Be specific — not "contemplative" but "restless about the
   half-finished letter on her desk, keeps reading the last line."

4. POST (optional): Does {profile.name} freely choose to post publicly today?
   If yes, write the post in their authentic voice — specific, not performative,
   the kind of thing this particular person would actually share.
   Not every cycle needs a post. If no, return null.

Return ONLY valid JSON — no markdown fences, no preamble:
{{
  "events": ["...", "...", "..."],
  "journal": "...",
  "mood": "...",
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
