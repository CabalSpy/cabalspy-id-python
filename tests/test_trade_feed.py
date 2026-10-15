"""Trade Feed: Data API methods (sync + async), the stream against a local server, webhooks, module."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from websockets.asyncio.server import serve

import cabalspy_id
import cabalspy_id.api
import cabalspy_id.trade_feed
from cabalspy_id import (
    SDK_VERSION,
    AsyncCabalSpyID,
    BadRequestError,
    CabalSpyID,
    CabalSpyIDError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    is_trade_feed_event,
    is_trade_feed_thesis_event,
    is_trade_feed_trade_event,
    sign_webhook,
    verify_webhook,
)

from .conftest import META, RATE, Recorder, api_error, ok

USER = "0b6a3a4e-5a4f-4a59-9a59-0f5c5f5c5f5c"
MINT = "So11111111111111111111111111111111111111112"
TRADER = {
    "csid_id": "11111111-2222-4333-8444-555555555555",
    "username": "alice",
    "name": "Alice",
    "image_url": None,
    "kol": True,
    "profile_url": "https://id.cabalspy.xyz/u/alice",
}
TRADE_ITEM: dict[str, Any] = {
    "id": "t0123456789abcdef0123456789abcdef",
    "type": "trade",
    "timestamp": "2026-10-15T12:00:00Z",
    "trader": TRADER,
    "trade": {
        "blockchain": "solana",
        "mint": MINT,
        "symbol": "ABC",
        "name": "Abc",
        "logo": None,
        "side": "sell",
        "label": "partial",
        "sold_percent": 50.0,
        "amount_native": 1.5,
        "currency": "SOL",
        "amount_usd": 300.0,
        "token_amount": 1000.0,
        "price_usd": 0.3,
        "pnl_usd": 120.0,
        "pnl_percent": 66.67,
        "wallet": "WaLLet",
        "wallet_url": "https://solscan.io/account/WaLLet",
        "tx_signature": "sig",
        "tx_url": "https://solscan.io/tx/sig",
    },
    "links": {
        "token": f"https://app.cabalspy.xyz/token/{MINT}",
        "terminal": f"https://app.cabalspy.xyz/token/{MINT}",
        "profile": TRADER["profile_url"],
    },
    "cursor": "c1",
}
THESIS_ITEM: dict[str, Any] = {
    "id": "h42",
    "type": "thesis",
    "timestamp": "2026-10-15T11:00:00Z",
    "trader": TRADER,
    "thesis": {
        "id": "42",
        "blockchain": "base",
        "mint": "0xabc",
        "symbol": None,
        "name": None,
        "logo": None,
        "stance": "bull",
        "body": "up",
        "likes": 1,
        "replies": 0,
        "url": "https://id.cabalspy.xyz/try/thesis?chain=base&mint=0xabc",
    },
    "links": {"token": "https://id.cabalspy.xyz/try/thesis?chain=base&mint=0xabc", "terminal": None, "profile": None},
}
SETTINGS = {
    "notify_buys": True,
    "notify_sells": True,
    "notify_theses": False,
    "min_native": {"SOL": 0.5, "BNB": 0.0, "ETH": 0.0},
    "muted": False,
}
EVENT_DATA = {**{k: v for k, v in TRADE_ITEM.items() if k != "cursor"}, "recipients": [USER]}


def path(r: httpx.Request) -> str:
    q = r.url.query.decode()
    return f"{r.url.path}?{q}" if q else r.url.path


def paged(first: list[Any], second: list[Any], cursor: str) -> Recorder:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.params.get("cursor"):
            return ok(second, pagination={"limit": 1, "next_cursor": None, "has_more": False})
        return ok(first, pagination={"limit": 1, "next_cursor": cursor, "has_more": True})

    return Recorder(handler)


# ── Data API ────────────────────────────────────────────────────────────────


def test_feed_with_filter_and_pagination() -> None:
    rec = paged([TRADE_ITEM], [THESIS_ITEM], "c1")
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    page = csid.trade_feed(USER, filter="sells", limit=1)
    assert page[0]["trade"]["label"] == "partial"
    first = rec.requests[0]
    assert path(first) == f"/v1/trade-feed?csid_id={USER}&filter=sells&limit=1"
    assert first.headers["authorization"] == "Bearer k"
    assert first.headers["user-agent"] == f"cabalspy-id-python/{SDK_VERSION}"
    assert [i["id"] for i in csid.iter_trade_feed(USER, limit=1)] == [TRADE_ITEM["id"], "h42"]
    assert path(rec.requests[2]) == f"/v1/trade-feed?csid_id={USER}&limit=1&cursor=c1"
    with pytest.raises(BadRequestError) as e:
        csid.trade_feed(USER, filter="everything")  # type: ignore[arg-type]
    assert e.value.code == "invalid_parameter"
    with pytest.raises(BadRequestError):
        csid.trade_feed("")


def test_traders_add_remove() -> None:
    entry = {"trader": TRADER, "trading_public": True, "added_at": "2026-10-15T00:00:00+00:00", "in_trade_feeds": 3}
    entry["settings"] = SETTINGS
    calls = {"add": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/trade-feed/traders" and r.method == "GET":
            return ok(
                [entry], pagination={"limit": 100, "total": 1, "max": 300, "next_cursor": None, "has_more": False}
            )
        if r.url.path == "/v1/trade-feed/traders/delete":
            return ok({"in_trade_feed": False, "removed": True})
        calls["add"] += 1
        status = 201 if calls["add"] == 1 else 200
        data = {"in_trade_feed": True, "created": status == 201, "trader": TRADER, "settings": SETTINGS}
        return httpx.Response(status, json={"success": True, "data": data, "meta": META}, headers=RATE)

    rec = Recorder(handler)
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    traders = csid.get_raw("/trade-feed/traders", {"csid_id": USER})
    assert traders.pagination == {"limit": 100, "total": 1, "max": 300, "next_cursor": None, "has_more": False}
    assert csid.trade_feed_traders(USER, limit=100)[0]["settings"]["min_native"]["SOL"] == 0.5
    assert path(rec.requests[1]) == f"/v1/trade-feed/traders?csid_id={USER}&limit=100"
    assert len(list(csid.iter_trade_feed_traders(USER))) == 1

    added = csid.add_to_trade_feed(USER, "@alice", notify_theses=False, min_sol=0.5)
    assert added["created"] is True
    post = rec.requests[-1]
    assert post.method == "POST" and post.url.path == "/v1/trade-feed/traders"
    assert json.loads(post.content) == {"notify_theses": False, "min_sol": 0.5, "csid_id": USER, "trader": "@alice"}
    assert csid.add_to_trade_feed(USER, "alice", muted=True)["created"] is False

    assert csid.remove_from_trade_feed(USER, "alice") == {"in_trade_feed": False, "removed": True}
    assert json.loads(rec.requests[-1].content) == {"csid_id": USER, "trader": "alice"}
    with pytest.raises(BadRequestError) as e:
        csid.add_to_trade_feed(USER, "")
    assert e.value.parameter == "trader"


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (404, "trader_not_found", NotFoundError),
        (400, "cannot_add_self", BadRequestError),
        (403, "trading_private", PermissionError),
        (403, "consent_required", PermissionError),
        (409, "trade_feed_full", CabalSpyIDError),
        (429, "rate_limited", RateLimitError),
        (400, "invalid_cursor", BadRequestError),
    ],
)
def test_errors(status: int, code: str, cls: type[CabalSpyIDError]) -> None:
    rec = Recorder(lambda r: api_error(status, code))
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=2)
    with pytest.raises(cls) as e:
        csid.add_to_trade_feed(USER, "bob")
    assert e.value.code == code and e.value.status == status
    assert len(rec.requests) == 1  # writes are not retried (only the API's own rate_limit_exceeded)


def test_notifications() -> None:
    n = {
        "id": 9,
        "event": "trade_feed.trade",
        "text": "Trade Feed: @alice sold $ABC",
        "created_at": "x",
        "data": TRADE_ITEM,
    }
    rec = paged([n], [], "n9")
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    assert csid.trade_feed_notifications(USER, limit=1)[0]["event"] == "trade_feed.trade"
    assert path(rec.requests[0]) == f"/v1/trade-feed/notifications?csid_id={USER}&limit=1"
    assert len(list(csid.iter_trade_feed_notifications(USER, limit=1))) == 1
    assert path(rec.requests[2]) == f"/v1/trade-feed/notifications?csid_id={USER}&limit=1&cursor=n9"


async def test_async_client() -> None:
    rec = paged([TRADE_ITEM], [THESIS_ITEM], "c1")
    async with AsyncCabalSpyID("k", http_client=rec.async_client(), max_retries=0) as csid:
        page = await csid.trade_feed(USER, filter="all")
        assert page[0]["id"] == TRADE_ITEM["id"]
        items = [i["type"] async for i in csid.iter_trade_feed(USER)]
        assert items == ["trade", "thesis"]
        assert [t async for t in csid.iter_trade_feed_traders(USER)]
        assert [t async for t in csid.iter_trade_feed_notifications(USER)]
        added = await csid.add_to_trade_feed(USER, "alice")
        assert added == [TRADE_ITEM]  # the mock answers every GET/POST with the first page
        await csid.remove_from_trade_feed(USER, "alice")
        await csid.trade_feed_traders(USER)
        await csid.trade_feed_notifications(USER)
    assert rec.requests[-3].url.path == "/v1/trade-feed/traders/delete"


# ── stream ──────────────────────────────────────────────────────────────────


class Server:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.received: list[str] = []
        self.mode = "ok"
        self.connections = 0

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        self.paths.append(ws.request.path)
        if self.mode == "deny":
            await ws.send(json.dumps({"event": "error", "error": {"code": "invalid_api_key", "message": "bad key"}}))
            await ws.close(code=4403)
            return
        if self.mode == "busy" and self.connections == 1:
            await ws.send(json.dumps({"event": "error", "error": {"code": "too_many_connections", "message": "5"}}))
            await ws.close(code=4403)
            return
        await ws.send(json.dumps({"event": "ready", "data": {"events": ["trade_feed.trade", "trade_feed.thesis"]}}))
        await ws.send(json.dumps({"event": "trade_feed.trade", "id": "ev-1", "data": EVENT_DATA}))
        await ws.send(
            json.dumps({"event": "trade_feed.thesis", "id": "ev-2", "data": {**THESIS_ITEM, "recipients": [USER]}})
        )
        await ws.send(json.dumps({"event": "heartbeat", "ts": 5}))
        async for raw in ws:
            self.received.append(raw)
            if raw == "ping":
                await ws.send(json.dumps({"event": "pong"}))


@pytest.fixture
async def server():
    s = Server()
    async with serve(s.handler, "127.0.0.1", 0) as srv:
        s.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/trade-feed/stream"  # type: ignore[attr-defined]
        yield s


def client(s: Server) -> CabalSpyID:
    return CabalSpyID("k", instance="csid_i", trade_feed_stream_url=s.url)  # type: ignore[attr-defined]


async def wait_for(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)


async def test_stream_events(server: Server) -> None:
    tf = client(server).trade_feed_stream()
    got: list[str] = []
    tf.on("trade_feed.trade", lambda d: got.append(f"trade:{d['trade']['label']}:{','.join(d['recipients'])}"))
    tf.on("trade_feed.thesis", lambda d: got.append(f"thesis:{d['thesis']['stance']}"))
    tf.on("heartbeat", lambda h: got.append(f"hb:{h['ts']}"))
    tf.on("pong", lambda _p: got.append("pong"))
    ready = await tf.connect()
    assert ready == {"events": ["trade_feed.trade", "trade_feed.thesis"]}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "k", "instance": "csid_i"}
    assert urlsplit(server.paths[0]).path == "/v1/trade-feed/stream"
    assert "api_key=***" in tf.safe_url
    await tf.ping()
    await wait_for(lambda: "pong" in got)
    await tf.close()
    assert got == [f"trade:partial:{USER}", "thesis:bull", "hb:5", "pong"]
    assert server.received == ["ping"]
    with pytest.raises(ValueError):
        tf.on("trade", lambda _d: None)


async def test_stream_iterator(server: Server) -> None:
    seen: list[tuple[str, str]] = []
    async with client(server).trade_feed_stream() as tf:
        async for ev in tf:
            seen.append((ev["event"], ev["id"]))
            if len(seen) == 2:
                break
    assert seen == [("trade_feed.trade", "ev-1"), ("trade_feed.thesis", "ev-2")]


async def test_stream_refusal_is_fatal(server: Server) -> None:
    server.mode = "deny"
    tf = client(server).trade_feed_stream(reconnect_delay=0.01)
    with pytest.raises(PermissionError) as e:
        await tf.connect()
    assert e.value.code == "invalid_api_key"
    await asyncio.sleep(0.1)
    assert server.connections == 1


async def test_stream_too_many_connections_is_retried(server: Server) -> None:
    server.mode = "busy"
    tf = client(server).trade_feed_stream(reconnect_delay=0.01)
    with pytest.raises(RateLimitError):
        await tf.connect()
    await wait_for(lambda: tf.connected)
    assert server.connections == 2
    await tf.close()


def test_stream_needs_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CABALSPY_ID_API_KEY", raising=False)
    monkeypatch.delenv("CABALSPY_API_KEY", raising=False)
    with pytest.raises(cabalspy_id.AuthenticationError):
        CabalSpyID().trade_feed_stream()


# ── webhooks and module ─────────────────────────────────────────────────────


def test_webhook_type_guards() -> None:
    secret = "whsec_" + "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    body = json.dumps(
        {"id": "evt_tf", "type": "trade_feed.trade", "created_at": "2026-10-15T12:00:02+00:00", "sandbox": False}
        | {"data": EVENT_DATA}
    )
    ts = int(time.time())
    headers = {
        "webhook-id": "evt_tf",
        "webhook-timestamp": str(ts),
        "webhook-signature": sign_webhook(secret, "evt_tf", ts, body),
    }
    event = verify_webhook(body, headers, secret)
    assert is_trade_feed_event(event) and not is_trade_feed_thesis_event(event)
    assert is_trade_feed_trade_event(event)
    assert event["data"]["recipients"] == [USER]
    assert event["data"]["trade"]["pnl_usd"] == 120.0
    assert not is_trade_feed_event({"type": "thesis.created"})
    assert is_trade_feed_thesis_event({"type": "trade_feed.thesis"})
    assert "trade_feed.trade" in cabalspy_id.WEBHOOK_EVENTS


def test_trade_feed_module_is_the_same_objects() -> None:
    m = cabalspy_id.trade_feed
    assert m.CabalSpyID is cabalspy_id.CabalSpyID
    assert m.TradeFeedStream is cabalspy_id.TradeFeedStream
    assert cabalspy_id.api.TradeFeedStream is cabalspy_id.TradeFeedStream
    assert m.is_trade_feed_trade_event is cabalspy_id.is_trade_feed_trade_event
    assert m.PermissionError is cabalspy_id.PermissionError
    assert m.TRADE_FEED_FILTERS == ("all", "buys", "sells", "theses")
    assert m.TRADE_FEED_MAX_TRADERS == 300
    assert m.DEFAULT_TRADE_FEED_STREAM_URL == "wss://api-id.cabalspy.xyz/v1/trade-feed/stream"
    assert m.TRADE_FEED_STREAM_EVENTS[0] == "ready"
    for name in m.__all__:
        assert getattr(m, name) is not None
