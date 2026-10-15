"""Webhook verification: Standard Webhooks signatures (standardwebhooks.com).

webhook-id         event id, the same on every retry (dedupe on it)
webhook-timestamp  unix seconds
webhook-signature  "v1,<base64 HMAC-SHA256>" over "<id>.<timestamp>.<body>",
                   keyed with the base64-decoded part of the whsec_ secret.
                   During a secret roll: several, separated by spaces.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from ._errors import WebhookVerificationError

if TYPE_CHECKING:
    from typing import TypeGuard

    from ._types import TradeFeedEvent, TradeFeedThesisEvent, TradeFeedTradeEvent

__all__ = [
    "verify_webhook",
    "sign_webhook",
    "HeaderSource",
    "is_trade_feed_event",
    "is_trade_feed_trade_event",
    "is_trade_feed_thesis_event",
]


class HeaderSource(Protocol):
    """Anything with ``get`` and ``items``: a dict, httpx/Starlette/Django/Flask
    headers, or ``http.server``'s message object."""

    def get(self, key: str, /) -> Any: ...

    def items(self) -> Iterable[tuple[str, Any]]: ...


def _key(secret: str) -> bytes:
    raw = secret[6:] if secret.startswith("whsec_") else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebhookVerificationError(
            "The webhook secret is not valid base64 (expected whsec_...)", code="invalid_secret"
        ) from exc


def _body(payload: bytes | bytearray | str) -> bytes:
    return payload.encode() if isinstance(payload, str) else bytes(payload)


def _header(headers: HeaderSource, name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        for k, v in headers.items():
            if k.lower() == name:
                value = v
                break
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return None if value is None else str(value)


def sign_webhook(secret: str, msg_id: str, timestamp: int | str, payload: bytes | str) -> str:
    """The ``webhook-signature`` header value for a payload. Useful to test your receiver."""
    mac = hmac.new(_key(secret), f"{msg_id}.{timestamp}.".encode() + _body(payload), hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify_webhook(
    payload: bytes | bytearray | str,
    headers: HeaderSource,
    secret: str,
    *,
    tolerance: int = 300,
    now: float | None = None,
) -> dict[str, Any]:
    """Verifies a webhook and returns the parsed event.

    ``payload`` must be the raw request body, exactly as received. Raises
    :class:`~cabalspy_id.WebhookVerificationError` when a header is missing,
    the timestamp is outside ``tolerance`` seconds, or no signature matches.

        event = verify_webhook(request.body, request.headers, os.environ["CSID_WEBHOOK_SECRET"])
    """
    if not secret:
        raise WebhookVerificationError("Missing webhook secret", code="invalid_secret")
    msg_id = _header(headers, "webhook-id")
    ts = _header(headers, "webhook-timestamp")
    signatures = _header(headers, "webhook-signature")
    if not msg_id or not ts or not signatures:
        raise WebhookVerificationError(
            "Missing webhook-id, webhook-timestamp or webhook-signature header", code="missing_headers"
        )
    if not ts.isdigit():
        raise WebhookVerificationError("Invalid webhook-timestamp", code="invalid_timestamp")
    timestamp = int(ts)
    current = int(now if now is not None else time.time())
    if current - timestamp > tolerance:
        raise WebhookVerificationError("Webhook timestamp is too old", code="timestamp_too_old")
    if timestamp - current > tolerance:
        raise WebhookVerificationError("Webhook timestamp is in the future", code="timestamp_too_new")

    body = _body(payload)
    expected = sign_webhook(secret, msg_id, ts, body).split(",", 1)[1]
    for candidate in signatures.split():
        version, _, sig = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            break
    else:
        raise WebhookVerificationError("No matching webhook signature", code="invalid_signature")

    try:
        event = json.loads(body)
    except ValueError as exc:
        raise WebhookVerificationError("Webhook body is not valid JSON", code="invalid_payload") from exc
    if not isinstance(event, dict):
        raise WebhookVerificationError("Webhook body is not a JSON object", code="invalid_payload")
    return event


# ── Trade Feed events ────────────────────────────────────────────────────────


def is_trade_feed_trade_event(event: Mapping[str, Any]) -> TypeGuard[TradeFeedTradeEvent]:
    """True for a ``trade_feed.trade`` event: a trader in your users' Trade Feeds
    traded; ``event["data"]["recipients"]`` are the users to tell."""
    return isinstance(event, Mapping) and event.get("type") == "trade_feed.trade"


def is_trade_feed_thesis_event(event: Mapping[str, Any]) -> TypeGuard[TradeFeedThesisEvent]:
    """True for a ``trade_feed.thesis`` event: a trader in your users' Trade Feeds posted a thesis."""
    return isinstance(event, Mapping) and event.get("type") == "trade_feed.thesis"


def is_trade_feed_event(event: Mapping[str, Any]) -> TypeGuard[TradeFeedEvent]:
    """True for any Trade Feed event (``trade_feed.trade`` or ``trade_feed.thesis``)."""
    return isinstance(event, Mapping) and event.get("type") in ("trade_feed.trade", "trade_feed.thesis")
