"""
LLM client with pluggable provider (Anthropic Claude or Google Gemini).
All LLM calls go through this module.
"""
from __future__ import annotations

import json
import os
import random
from typing import Any

from app.models import (
    DELAY_BUCKETS,
    DelayBucket,
    DigitalProfile,
    RunCycleResponse,
    RuntimeState,
)
from app.prompts import build_reply_prompt, build_run_cycle_prompt

# ─── Provider abstraction ─────────────────────────────────────────────────────

def _get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def _call_anthropic(system: str, user: str, temperature: float = 0.85, max_tokens: int = 2048) -> str:
    import anthropic  # type: ignore

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def _call_google(system: str, user: str, temperature: float = 0.85, max_tokens: int = 2048) -> str:
    import google.generativeai as genai  # type: ignore

    model_name = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system,
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    response = model.generate_content(user)
    return response.text


def _llm_call(system: str, user: str, temperature: float = 0.85, max_tokens: int = 2048) -> str:
    provider = _get_provider()
    if provider == "anthropic":
        return _call_anthropic(system, user, temperature, max_tokens)
    if provider == "google":
        return _call_google(system, user, temperature, max_tokens)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'anthropic' or 'google'.")


def _parse_json_with_retry(raw: str, system: str, user: str, temperature: float) -> Any:
    """Parse JSON from LLM output; retry once on failure."""
    # Strip markdown fences if the model wrapped it
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # One retry: ask the model to fix its own output
        fix_system = "Fix the following invalid JSON and return only valid JSON, no markdown fences."
        fix_user = f"Invalid JSON:\n{raw}"
        raw2 = _llm_call(fix_system, fix_user, temperature=0.2, max_tokens=2048)
        cleaned2 = raw2.strip()
        if cleaned2.startswith("```"):
            lines2 = cleaned2.split("\n")
            cleaned2 = "\n".join(lines2[1:-1] if lines2[-1].strip() == "```" else lines2[1:])
        return json.loads(cleaned2)


# ─── Public LLM operations ────────────────────────────────────────────────────

def reply(
    profile: DigitalProfile,
    state: RuntimeState,
    user_message: str,
) -> tuple[str, DelayBucket]:
    """
    Generate a persona reply to a user message.
    Returns (reply_text, delay_bucket).
    """
    system, user = build_reply_prompt(profile, state, user_message)
    text = _llm_call(system, user, temperature=0.85, max_tokens=1024)
    bucket: DelayBucket = random.choice(DELAY_BUCKETS)
    return text.strip(), bucket


def run_cycle(
    profile: DigitalProfile,
    state: RuntimeState,
) -> RunCycleResponse:
    """
    Advance the persona one notional day.
    Returns a RunCycleResponse (events, journal, mood, optional post).
    """
    system, user = build_run_cycle_prompt(profile, state)
    raw = _llm_call(system, user, temperature=0.90, max_tokens=2048)
    data = _parse_json_with_retry(raw, system, user, temperature=0.90)
    return RunCycleResponse.model_validate(data)


def generate_persona(system: str, user: str) -> str:
    """
    Raw LLM call for profile generation (used by scripts/generate_profiles.py).
    Returns raw text (caller parses JSON).
    """
    return _llm_call(system, user, temperature=0.90, max_tokens=4096)
