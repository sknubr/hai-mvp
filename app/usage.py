"""
Per-user soft daily call cap, to protect the shared LLM key during the
feedback round. Counts LLM-backed actions (messages + cycles) per UTC day in
data/state/{user_id}/usage.json. A paid key makes this moot — raise or unset
HAI_DAILY_CALL_CAP to disable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).parent.parent / "data" / "state"


def _cap() -> int:
    try:
        return int(os.getenv("HAI_DAILY_CALL_CAP", "80"))
    except ValueError:
        return 80


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _path(user_id: str) -> Path:
    d = STATE_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "usage.json"


def _read(user_id: str) -> dict:
    p = _path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": _today(), "count": 0}


def _count_today(user_id: str) -> int:
    data = _read(user_id)
    return data["count"] if data.get("date") == _today() else 0


def under_cap(user_id: str) -> bool:
    cap = _cap()
    if cap <= 0:
        return True
    return _count_today(user_id) < cap


def record_call(user_id: str) -> None:
    today = _today()
    data = _read(user_id)
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] += 1
    _path(user_id).write_text(json.dumps(data))
