"""
LLM client with pluggable provider (Anthropic Claude or Google Gemini).
All LLM calls go through this module.
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any

# Verify TLS against the OS trust store rather than only certifi. This makes
# HTTPS work behind corporate TLS-inspecting proxies (e.g. SealSuite SWG on
# managed machines), whose private root CA lives in the OS keychain but not in
# certifi. No-op on hosts where the standard CA bundle already suffices.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # pragma: no cover - falls back to certifi
    pass

from app.models import (
    DigitalProfile,
    InitiationResponse,
    RunCycleResponse,
    RuntimeState,
)
from app.prompts import build_initiation_prompt, build_reply_prompt, build_run_cycle_prompt

# ─── Provider abstraction ─────────────────────────────────────────────────────

def _get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def _call_anthropic(system: str, user: str, temperature: float, max_tokens: int, model_name: str) -> str:
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def _call_zai(system: str, user: str, temperature: float, max_tokens: int, model_name: str) -> str:
    """z.ai (Zhipu) via its OpenAI-compatible endpoint."""
    from openai import OpenAI  # type: ignore

    client = OpenAI(
        api_key=os.environ["ZAI_API_KEY"],
        base_url=os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"),
    )
    kwargs: dict = dict(
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    # GLM-4.5+ "think" by default, which can eat the token budget and truncate JSON.
    # Disable it (mirrors the Gemini thinking_budget=0 fix).
    if any(v in model_name for v in ("4.5", "4.6", "4.7", "4.8")):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content
    if text is None:
        raise RuntimeError(f"z.ai model {model_name} returned no text (finish_reason="
                           f"{resp.choices[0].finish_reason})")
    return text


def _call_google(system: str, user: str, temperature: float, max_tokens: int, model_name: str) -> str:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    # Gemma models don't accept a separate system role — fold it into the prompt.
    is_gemma = "gemma" in model_name.lower()
    if is_gemma:
        contents = f"{system}\n\n---\n\n{user}"
        config_kwargs = dict(temperature=temperature, max_output_tokens=max_tokens)
    else:
        contents = user
        config_kwargs = dict(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        # 2.5+/3.x models spend output-token budget on "thinking"; disable it so
        # the full response (often JSON) is not truncated.
        if "2.5" in model_name or "-3" in model_name or "3." in model_name:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = response.text
    if text is None:
        raise RuntimeError(
            f"Google model {model_name} returned no text (finish_reason="
            f"{response.candidates[0].finish_reason if response.candidates else 'unknown'})"
        )
    return text


# Transient error signatures worth retrying (rate limit / temporary unavailability).
_TRANSIENT_MARKERS = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded", "high demand")
_MAX_RETRIES = 5
_MAX_WAIT = 35.0  # cap so a single request can't hang indefinitely


def _is_transient(err: Exception) -> bool:
    msg = str(err)
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def _suggested_delay(err: Exception) -> float | None:
    """Extract the provider's suggested retryDelay (e.g. 'retryDelay': '26s') if present."""
    import re
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(err))
    if m:
        return float(m.group(1))
    return None


def _model_chain() -> list[str]:
    """Primary model + comma-separated fallbacks (rolled to on transient exhaustion)."""
    provider = _get_provider()
    if provider == "anthropic":
        primary = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        fallbacks = os.getenv("ANTHROPIC_MODEL_FALLBACKS", "")
    elif provider == "zai":
        primary = os.getenv("ZAI_MODEL", "glm-4.7-flash")
        fallbacks = os.getenv("ZAI_MODEL_FALLBACKS", "")
    else:
        primary = os.getenv("GOOGLE_MODEL", "gemini-3.1-flash-lite")
        fallbacks = os.getenv("GOOGLE_MODEL_FALLBACKS", "")
    chain = [primary] + [m.strip() for m in fallbacks.split(",") if m.strip()]
    # De-dup while preserving order
    seen, out = set(), []
    for m in chain:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _attempt_with_retries(fn, system, user, temperature, max_tokens, model_name) -> str:
    """Call one model, retrying transient errors (honoring suggested retryDelay).
    Re-raises the last error if all retries are exhausted (caller may fall back)."""
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(system, user, temperature, max_tokens, model_name)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if not _is_transient(e) or attempt == _MAX_RETRIES - 1:
                raise
            suggested = _suggested_delay(e)
            if suggested is not None:
                wait = min(suggested + random.uniform(0.5, 1.5), _MAX_WAIT)
            else:
                wait = min((2 ** attempt) + 1 + random.uniform(0, 1.5), _MAX_WAIT)
            print(f"[llm retry] {model_name}: transient ({str(e)[:50]}...); waiting {wait:.1f}s "
                  f"(attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def _llm_call(system: str, user: str, temperature: float = 0.85, max_tokens: int = 2048) -> str:
    provider = _get_provider()
    if provider == "anthropic":
        fn = _call_anthropic
    elif provider == "google":
        fn = _call_google
    elif provider == "zai":
        fn = _call_zai
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'anthropic', 'google', or 'zai'.")

    chain = _model_chain()
    last_err: Exception | None = None
    for i, model_name in enumerate(chain):
        try:
            return _attempt_with_retries(fn, system, user, temperature, max_tokens, model_name)
        except Exception as e:  # noqa: BLE001
            last_err = e
            # Only roll to the next model on transient exhaustion; surface real errors.
            if _is_transient(e) and i < len(chain) - 1:
                print(f"[llm fallback] {model_name} exhausted; falling back to {chain[i + 1]}")
                continue
            raise
    raise last_err  # type: ignore[misc]


def _parse_json_with_retry(raw: str, system: str, user: str, temperature: float) -> Any:
    """Parse JSON from LLM output; retry once on failure."""
    # Strip markdown fences if the model wrapped it
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        # One retry: ask the model to fix its own output
        fix_system = "Fix the following invalid JSON and return only valid JSON, no markdown fences."
        fix_user = f"Invalid JSON:\n{raw}"
        raw2 = _llm_call(fix_system, fix_user, temperature=0.2, max_tokens=2048)
        cleaned2 = raw2.strip()
        if cleaned2.startswith("```"):
            lines2 = cleaned2.split("\n")
            cleaned2 = "\n".join(lines2[1:-1] if lines2[-1].strip() == "```" else lines2[1:])
        return json.loads(cleaned2, strict=False)


# ─── Public LLM operations ────────────────────────────────────────────────────

def reply(
    profile: DigitalProfile,
    state: RuntimeState,
    user_message: str,
    recalled: list | None = None,
    short_term_summary: str = "",
) -> str:
    """
    Generate a persona reply to a user message.
    `recalled` are the memory items surfaced for this turn (PRD §9); they are
    rendered into the prompt and reinforced by the caller.
    Returns the reply text. (The delay bucket is chosen separately in app.delays.)
    """
    system, user = build_reply_prompt(profile, state, user_message, recalled, short_term_summary)
    text = _llm_call(system, user, temperature=0.85, max_tokens=1024)
    return text.strip()


def run_cycle(
    profile: DigitalProfile,
    state: RuntimeState,
    store=None,
) -> RunCycleResponse:
    """
    Advance the persona one notional day AND consolidate memory ("sleep") in a
    single call. `store` supplies the current memory items to consolidate.
    Returns a RunCycleResponse.
    """
    system, user = build_run_cycle_prompt(profile, state, store)
    # Larger payload now (events + journal + memory consolidation) — give it room.
    raw = _llm_call(system, user, temperature=0.90, max_tokens=4096)
    data = _parse_json_with_retry(raw, system, user, temperature=0.90)
    next_cycle = state.cycle_count + 1

    # Tolerate the model returning events/facts/threads/memories as bare strings.
    if isinstance(data, dict):
        evs = data.get("events")
        if isinstance(evs, list):
            data["events"] = [
                {"cycle": next_cycle, "text": e, "salience": 3} if isinstance(e, str) else e
                for e in evs
            ]
        facts = data.get("salient_user_facts")
        if isinstance(facts, list):
            data["salient_user_facts"] = [
                {"text": f, "cycle_added": next_cycle, "salience": 3} if isinstance(f, str) else f
                for f in facts
            ]
        threads = data.get("open_threads")
        if isinstance(threads, list):
            data["open_threads"] = [
                {"text": t, "status": "open", "cycle_added": next_cycle} if isinstance(t, str) else t
                for t in threads
            ]
        for key in ("new_memories", "consolidated_memory"):
            mems = data.get(key)
            if isinstance(mems, list):
                data[key] = [
                    {"content": m, "salience": 50, "tag": "observed", "source": "conversation"}
                    if isinstance(m, str) else m
                    for m in mems
                ]
    return RunCycleResponse.model_validate(data)


def initiate(
    profile: DigitalProfile,
    state: RuntimeState,
    recalled: list | None = None,
    short_term_summary: str = "",
    idle_human: str = "a while",
) -> InitiationResponse:
    """One-shot judge+write for a character-initiated reach-out (PRD §5): decide
    whether to text the user first and, if so, write the opener. Returns an
    InitiationResponse (reach_out defaults False on any shape surprise)."""
    system, user = build_initiation_prompt(
        profile, state, recalled, short_term_summary, idle_human
    )
    raw = _llm_call(system, user, temperature=0.9, max_tokens=512)
    data = _parse_json_with_retry(raw, system, user, temperature=0.9)
    if not isinstance(data, dict):
        return InitiationResponse(reach_out=False, reason="unparseable response")
    return InitiationResponse.model_validate(data)


def generate_persona(system: str, user: str) -> str:
    """
    Raw LLM call for profile generation (used by scripts/generate_profiles.py).
    Returns raw text (caller parses JSON).
    """
    return _llm_call(system, user, temperature=0.90, max_tokens=4096)


def generate_onboarding(onboarding_json: str) -> dict:
    """
    Generate a persona (name + hydrated base_schema) from a user's onboarding answers.
    Returns a parsed dict: {"name": str, "base_schema": {...}}.
    """
    from app.prompts import build_onboarding_prompt

    system, user = build_onboarding_prompt(onboarding_json)
    raw = _llm_call(system, user, temperature=0.90, max_tokens=4096)
    data = _parse_json_with_retry(raw, system, user, temperature=0.90)
    if not isinstance(data, dict) or "base_schema" not in data:
        raise ValueError("Onboarding generation returned an unexpected shape.")
    return data
