from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

import pytest

from cabalspy_id import WebhookVerificationError, sign_webhook, verify_webhook

RAW_KEY = os.urandom(24)
SECRET = "whsec_" + base64.b64encode(RAW_KEY).decode()
BODY = json.dumps(
    {
        "id": "evt_1",
        "type": "wallet.verified",
        "created_at": "2026-10-13T00:00:00+00:00",
        "sandbox": False,
        "data": {"sub": "user-1", "address": "So1", "chain": "solana"},
    },
    separators=(",", ":"),
).encode()
NOW = 1_760_000_000


def server_sign(key: bytes, msg_id: str, ts: int, body: bytes) -> str:
    """Exactly like the server (csid/app/events.py sign())."""
    return "v1," + base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()


def headers(sig: str | None = None, msg_id: str = "evt_1") -> dict[str, str]:
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": str(NOW),
        "webhook-signature": sig or server_sign(RAW_KEY, "evt_1", NOW, BODY),
    }


def test_verifies_server_signature() -> None:
    event = verify_webhook(BODY, headers(), SECRET, now=NOW)
    assert event["type"] == "wallet.verified"
    assert event["data"]["sub"] == "user-1"


def test_case_insensitive_headers_and_str_body() -> None:
    h = {k.title(): v for k, v in headers().items()}
    assert verify_webhook(BODY.decode(), h, SECRET, now=NOW)["id"] == "evt_1"


def test_secret_roll() -> None:
    old = server_sign(os.urandom(24), "evt_1", NOW, BODY)
    cur = server_sign(RAW_KEY, "evt_1", NOW, BODY)
    assert verify_webhook(BODY, headers(f"{old} {cur}"), SECRET, now=NOW)


def test_sign_webhook_matches_server() -> None:
    assert sign_webhook(SECRET, "evt_1", NOW, BODY) == server_sign(RAW_KEY, "evt_1", NOW, BODY)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"payload": BODY.replace(b"So1", b"So2")}, "invalid_signature"),
        ({"headers": headers(msg_id="evt_2")}, "invalid_signature"),
        ({"now": NOW + 301}, "timestamp_too_old"),
        ({"now": NOW - 301}, "timestamp_too_new"),
        ({"headers": {"webhook-id": "evt_1", "webhook-timestamp": str(NOW)}}, "missing_headers"),
        ({"secret": "whsec_" + base64.b64encode(os.urandom(24)).decode()}, "invalid_signature"),
        ({"secret": "whsec_not base64!"}, "invalid_secret"),
    ],
)
def test_rejects(kwargs: dict, code: str) -> None:
    args = {"payload": BODY, "headers": headers(), "secret": SECRET, "now": NOW, **kwargs}
    with pytest.raises(WebhookVerificationError) as e:
        verify_webhook(args.pop("payload"), args.pop("headers"), args.pop("secret"), **args)
    assert e.value.code == code
