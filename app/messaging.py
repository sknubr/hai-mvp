"""
Transport-agnostic messaging layer (PRD §4) — stubbed to the one owned surface.

The core loop emits outbound messages without knowing how they leave the system.
Today the only surface is the web app (in-app inbox poll + browser notifications),
wrapped here as AppPushAdapter. WhatsApp/SMS adapters and window-aware routing
(PRD §5) slot in behind `route()`/`get_adapter()` later without touching the loop.

Note: persona state mutation (appending to the buffer/transcript) stays in
app.schedule.generate_and_store_*; an adapter's job is only the transport-notify.
"""
from __future__ import annotations

from typing import Literal, Protocol

from app import push as push_module
from app.models import DigitalProfile

Channel = Literal["app", "whatsapp", "sms"]


class Adapter(Protocol):
    name: Channel

    def capabilities(self) -> dict: ...

    def deliver(
        self,
        user_id: str,
        profile: DigitalProfile,
        text: str,
        *,
        initiated_by: Literal["user", "character"] = "user",
    ) -> dict: ...


class AppPushAdapter:
    """The owned surface: in-app inbox poll + (Phase 2) Web Push notification."""

    name: Channel = "app"

    def capabilities(self) -> dict:
        # Unrestricted initiation — no 24h window, no template approval (PRD §6).
        return {
            "can_initiate": True,
            "initiation_window": None,
            "rich_media": True,
            "read_receipts": False,
        }

    def deliver(
        self,
        user_id: str,
        profile: DigitalProfile,
        text: str,
        *,
        initiated_by: Literal["user", "character"] = "user",
    ) -> dict:
        if initiated_by == "character":
            title = f"{profile.name} messaged you"
        else:
            title = f"{profile.name} replied"
        try:
            push_module.notify(user_id, title, text[:140],
                               f"/?persona={profile.profile_id}")
        except Exception as e:  # noqa: BLE001 — delivery must never break the loop
            return {"channel": self.name, "notified": False, "error": str(e)[:120]}
        return {"channel": self.name, "notified": True}


_ADAPTERS: dict[Channel, Adapter] = {"app": AppPushAdapter()}


def get_adapter(channel: Channel) -> Adapter:
    return _ADAPTERS.get(channel, _ADAPTERS["app"])


def route(persona_id: str, user_id: str,
          initiated_by: Literal["user", "character"] = "user") -> Channel:
    """Pick the channel for an outbound message. This is the window-aware-routing
    seam (PRD §5); for now the app is the only owned surface, so it always wins."""
    return "app"
