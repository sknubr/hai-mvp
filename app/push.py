"""
Push notification surface (Phase 2 stub).

The owned delivery surface today is the web app + the `/inbox` poll + the browser
Notifications API, which surface new persona messages without a server push. Real
Web Push / PWA delivery is deferred; until then `notify` is a logging no-op so the
rest of the system can call it unconditionally.
"""
from __future__ import annotations


def notify(user_id: str, title: str, body: str, url: str = "/") -> None:
    """Deliver an out-of-band notification to the user. No-op until Web Push lands.
    The `/inbox` poller is what actually surfaces messages in the meantime."""
    print(f"[push:noop] user={user_id} title={title!r} body={body!r} url={url}")
