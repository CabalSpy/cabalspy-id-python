"""People can sign in with X, Telegram or Google.

Accounts without X have no X profile: ``x`` is None, ``twitter`` is None and the
handle is ``tg.<name>`` (Telegram) or ``id.<hex>`` (Google). X handles never
contain a dot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

HandleKind = Literal["x", "telegram", "google"]

__all__ = ["HandleKind", "handle_kind", "has_x"]

_MISSING = object()


def handle_kind(handle: str) -> HandleKind:
    """Which identity a CabalSpy ID handle comes from: ``tg.`` = Telegram, ``id.`` = Google, else X."""
    if handle.startswith("tg."):
        return "telegram"
    if handle.startswith("id."):
        return "google"
    return "x"


def has_x(user: Mapping[str, Any] | None) -> bool:
    """True when the user has an X account connected.

    Works with userinfo / ID token claims, Data API profiles, trading profile
    blocks, leaderboard profiles and thesis authors. Uses ``x`` first, then
    ``twitter``, then the handle (``preferred_username`` / ``username``); the ID
    token carries no ``x`` claim, so there the handle decides.
    """
    if not user:
        return False
    x = user.get("x", _MISSING)
    if x is not _MISSING:
        return x is not None
    twitter = user.get("twitter", _MISSING)
    if twitter is not _MISSING:
        return bool(twitter)
    handle = user.get("preferred_username") or user.get("username")
    return isinstance(handle, str) and bool(handle) and handle_kind(handle) == "x"
