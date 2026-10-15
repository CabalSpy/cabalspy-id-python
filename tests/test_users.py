from __future__ import annotations

import httpx

from cabalspy_id import CabalSpyID, api, handle_kind, has_x, thesis

from .conftest import Recorder, ok

TELEGRAM_PROFILE = {
    "csid_id": "u-tg",
    "username": "tg.alice",
    "name": "Alice",
    "image_url": None,
    "bio": None,
    "twitter": None,
    "telegram": "https://t.me/alice",
    "x": None,
    "kol": {"badge": False, "since": None},
    "profile_url": "https://id.cabalspy.xyz/u/tg.alice",
    "wallets": [],
    "joined_at": "2026-10-15T00:00:00Z",
}


def test_has_x() -> None:
    assert has_x(TELEGRAM_PROFILE) is False
    assert has_x({**TELEGRAM_PROFILE, "username": "alice", "twitter": "https://x.com/alice", "x": {"id": "1"}}) is True
    assert has_x({"sub": "u", "preferred_username": "id.0a1b2c3d4e", "x": None}) is False
    assert has_x({"sub": "u", "preferred_username": "alice"}) is True  # ID token: no x claim
    assert has_x({"sub": "u", "preferred_username": "tg.bob"}) is False
    assert has_x({"username": "id.ff", "twitter": None, "telegram": ""}) is False
    assert has_x({"username": "alice", "twitter": ""}) is False
    assert has_x({"username": None}) is False
    assert has_x(None) is False
    assert has_x({}) is False
    assert api.has_x is has_x and thesis.has_x is has_x


def test_handle_kind() -> None:
    assert handle_kind("tg.alice") == "telegram"
    assert handle_kind("id.0a1b2c3d4e") == "google"
    assert handle_kind("alice") == "x"


def test_profile_without_x_passes_through() -> None:
    rec = Recorder(lambda r: ok(TELEGRAM_PROFILE))
    with CabalSpyID("k", http_client=httpx.Client(transport=httpx.MockTransport(rec)), max_retries=0) as csid:
        p = csid.profile(username="tg.alice")
    assert p["x"] is None and p["twitter"] is None and p["telegram"] == "https://t.me/alice"
    assert rec.requests[0].url.params["username"] == "tg.alice"
