from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from cabalspy_id import (
    AsyncThesisClient,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    PermissionError,
    ThesisClient,
    sign_webhook,
    verify_webhook,
)

from .conftest import Recorder, api_error, ok

USER = "0b6a3a4e-5a4f-4a59-9a59-0f5c5f5c5f5c"
NOTICE = {
    "id": 7,
    "kind": "post_hidden",
    "text": "Your post was hidden after several reports.",
    "data": {"thesis_id": "t1"},
    "created_at": "2026-10-14T00:00:00+00:00",
    "read": False,
    "appealable": True,
    "appeal": None,
}


def test_data_api_notifications_and_appeal() -> None:
    rec = Recorder(lambda r: ok({"unread": 1, "items": [NOTICE]}) if r.method == "GET" else ok({"appealed": True}))
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    n = csid.thesis_notifications(USER)
    assert n["unread"] == 1 and n["items"][0]["appealable"] is True
    csid.appeal_thesis_decision(USER, 7, "The token was not a scam, see the contract.")
    get, post = rec.requests
    assert f"{get.url.path}?{get.url.query.decode()}" == f"/v1/theses/notifications?csid_id={USER}"
    assert post.method == "POST" and post.url.path == "/v1/theses/appeal"
    assert json.loads(post.content) == {
        "csid_id": USER,
        "notification_id": 7,
        "message": "The token was not a scam, see the contract.",
    }
    with pytest.raises(BadRequestError):
        csid.thesis_notifications("")


def test_reporting_paused_is_permission_error() -> None:
    rec = Recorder(lambda r: api_error(403, "reporting_paused", "You can't report until 2026-10-20 UTC"))
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    with pytest.raises(PermissionError) as e:
        csid.report_thesis(thesis_id="t", reason="spam", csid_id=USER)
    assert e.value.code == "reporting_paused" and e.value.status == 403


def public(r: httpx.Request) -> httpx.Response:
    if r.url.path.endswith("/me/notifications"):
        return httpx.Response(200, json={"success": True, "data": {"unread": 1, "items": [NOTICE]}})
    if r.url.path.endswith("/read"):
        return httpx.Response(200, json={"success": True, "data": {"read": True}})
    if r.url.path.endswith("/appeal"):
        return httpx.Response(201, json={"success": True, "data": {"appealed": True}})
    return httpx.Response(
        200,
        json={
            "success": True,
            "data": {
                "can_post": True,
                "can_reply": True,
                "holder": True,
                "paused": False,
                "user": {"csid_id": USER},
                "notices": {"unread": 1, "latest": NOTICE["text"], "url": "https://id.cabalspy.xyz/me/notifications"},
            },
        },
    )


def test_public_notifications() -> None:
    rec = Recorder(public)
    tc = ThesisClient("at", client_id="csid_app", http_client=rec.client())
    assert tc.notifications()["items"][0]["kind"] == "post_hidden"
    tc.mark_notifications_read()
    tc.appeal(7, "Please look again, this was a real analysis.")
    assert tc.me("solana", "So11111111111111111111111111111111111111112")["notices"]["unread"] == 1
    base = "https://id.cabalspy.xyz/thesis/v1"
    assert [
        (r.method, str(r.url).removeprefix(base), json.loads(r.content) if r.content else None)
        for r in rec.requests[:3]
    ] == [
        ("GET", "/me/notifications", None),
        ("POST", "/me/notifications/read", None),
        ("POST", "/me/notifications/7/appeal", {"message": "Please look again, this was a real analysis."}),
    ]
    assert all(r.headers["authorization"] == "Bearer at" for r in rec.requests)
    with pytest.raises(AuthenticationError):
        ThesisClient(client_id="csid_app", http_client=rec.client()).notifications()


async def test_async_public_notifications() -> None:
    async with AsyncThesisClient("at", client_id="csid_app", http_client=Recorder(public).async_client()) as tc:
        assert (await tc.notifications())["unread"] == 1
        assert (await tc.mark_notifications_read())["read"] is True
        assert (await tc.appeal(7, "Please look again."))["appealed"] is True


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("thesis.reply", {"sub": USER, "reply": {"id": "r1", "kind": "reply"}}),
        (
            "thesis.reaction",
            {
                "sub": USER,
                "thesis_id": "t1",
                "chain": "solana",
                "mint": "M",
                "emoji": "like",
                "on": True,
                "reactions": {"like": 3},
            },
        ),
    ],
)
def test_new_webhook_types(kind: str, data: dict) -> None:
    secret = "whsec_" + base64.b64encode(b"s" * 24).decode()
    body = json.dumps({"id": "e", "type": kind, "created_at": "x", "sandbox": False, "data": data})
    ts = int(time.time())
    sig = sign_webhook(secret, "e", ts, body)
    event = verify_webhook(body, {"webhook-id": "e", "webhook-timestamp": str(ts), "webhook-signature": sig}, secret)
    assert event["type"] == kind and event["data"] == data
