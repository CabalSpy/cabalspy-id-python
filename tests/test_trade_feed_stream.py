"""TradeFeedStream against a local server that behaves like /v1/trade-feed/stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import serve

from cabalspy_id import (
    TRADE_FEED_EVENTS,
    AuthenticationError,
    CabalSpyID,
    PermissionError,
    RateLimitError,
)

TRADER = {"csid_id": "t1", "username": "MazeCCC", "name": "Maze", "image_url": None, "kol": True, "profile_url": None}
TRADE = {
    "id": "tk1",
    "type": "trade",
    "timestamp": "2026-11-01T18:40:05Z",
    "trader": TRADER,
    "trade": {"side": "buy", "label": "new", "symbol": "CPT", "amount_native": 1.5, "currency": "SOL"},
    "links": {"token": None, "terminal": None, "profile": None},
    "recipients": ["f1", "f2"],
    "recipients_external": ["u1"],
}
THESIS = {
    "id": "h9",
    "type": "thesis",
    "timestamp": "2026-11-01T18:41:00Z",
    "trader": TRADER,
    "thesis": {"id": "9", "stance": "bear", "body": "Top is in."},
    "links": {"token": None, "terminal": None, "profile": None},
    "recipients": ["f1"],
    "recipients_external": [],
}
EVENTS = [
    {"event": "trade_feed.trade", "id": "ev1", "data": TRADE},
    {"event": "trade_feed.thesis", "id": "ev2", "data": THESIS},
]


class Server:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.received: list[str] = []
        self.mode = "ok"
        self.connections = 0

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        self.paths.append(ws.request.path)
        deny = {
            "deny": ("invalid_api_key", "API key is invalid or does not exist"),
            "busy": ("too_many_connections", "At most 5 Trade Feed stream connections per API key."),
        }.get(self.mode)
        if deny or (self.mode == "busy_once" and self.connections == 1):
            code, message = deny or ("too_many_connections", "busy")
            await ws.send(json.dumps({"event": "error", "error": {"code": code, "message": message}}))
            await ws.close(code=4403)
            return
        await ws.send(json.dumps({"event": "ready", "data": {"events": list(TRADE_FEED_EVENTS)}}))
        await ws.send(json.dumps({"event": "heartbeat", "ts": 1}))
        await ws.send("not json")
        await ws.send(json.dumps({"event": "something.new", "data": {}}))
        for ev in EVENTS:
            await ws.send(json.dumps(ev))
        if self.mode == "drop_once" and self.connections == 1:
            await asyncio.sleep(0.05)
            await ws.close(code=1011)
            return
        async for raw in ws:
            self.received.append(raw)
            if json.loads(raw).get("op") == "ping":
                await ws.send(json.dumps({"event": "pong"}))


@pytest.fixture
async def server():
    s = Server()
    async with serve(s.handler, "127.0.0.1", 0) as srv:
        s.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/trade-feed/stream"  # type: ignore[attr-defined]
        yield s


def client(s: Server, **kwargs: Any) -> CabalSpyID:
    return CabalSpyID("k", trade_feed_stream_url=s.url, **kwargs)  # type: ignore[attr-defined]


async def wait_for(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)


async def test_events_are_parsed(server: Server) -> None:
    tf = client(server, instance="csid_app").trade_feed_stream()
    got: list[tuple[str, Any]] = []
    for name in (*TRADE_FEED_EVENTS, "heartbeat", "pong"):
        tf.on(name, lambda d, name=name: got.append((name, d)))
    ready = await tf.connect()
    assert ready == {"events": ["trade_feed.trade", "trade_feed.thesis"]}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "k", "instance": "csid_app"}
    assert "k" not in tf.safe_url.split("api_key=")[1]
    await wait_for(lambda: len(got) >= 3)
    await tf.ping()
    await wait_for(lambda: got[-1][0] == "pong")
    await tf.close()
    assert [n for n, _ in got] == ["heartbeat", "trade_feed.trade", "trade_feed.thesis", "pong"]
    assert got[1][1]["trade"]["side"] == "buy"
    assert got[1][1]["recipients"] == ["f1", "f2"] and got[1][1]["recipients_external"] == ["u1"]
    assert got[2][1]["thesis"]["stance"] == "bear"
    assert got[0][1] == {"ts": 1}
    assert json.loads(server.received[0]) == {"op": "ping"}
    assert not tf.connected


async def test_async_handlers_and_decorator(server: Server) -> None:
    tf = client(server).trade_feed_stream()
    seen: list[str] = []

    @tf.on("trade_feed.trade")
    async def on_trade(item: Any) -> None:
        seen.append(item["id"])
        raise ValueError("handler failed")

    @tf.on("trade_feed.thesis")
    def on_thesis(item: Any) -> None:
        seen.append(item["id"])

    errors: list[Any] = []
    tf.on("error", errors.append)
    await tf.connect()
    await wait_for(lambda: len(seen) == 2 and bool(errors))
    await tf.close()
    assert seen == ["tk1", "h9"]
    assert isinstance(errors[0], ValueError)
    with pytest.raises(ValueError):
        tf.on("copy_trade.instruction", print)


async def test_iteration_yields_event_ids(server: Server) -> None:
    seen: list[dict[str, Any]] = []
    async with client(server).trade_feed_stream() as tf:
        async for ev in tf:
            seen.append(ev)
            if len(seen) == 2:
                break
    assert [(e["event"], e["id"]) for e in seen] == [("trade_feed.trade", "ev1"), ("trade_feed.thesis", "ev2")]
    assert seen[0]["data"]["id"] == "tk1" and seen[0]["data"]["recipients_external"] == ["u1"]


async def test_iteration_without_context_manager(server: Server) -> None:
    tf = client(server).trade_feed_stream()
    first: dict[str, Any] = {}
    async for ev in tf:
        first = ev
        break
    assert first["id"] == "ev1"
    await tf.close()


async def test_invalid_api_key_is_fatal(server: Server) -> None:
    server.mode = "deny"
    tf = client(server).trade_feed_stream(reconnect_delay=0.01)
    with pytest.raises(PermissionError) as e:
        await tf.connect()
    assert e.value.code == "invalid_api_key"
    with pytest.raises(PermissionError):
        await asyncio.wait_for(tf.run_forever(), 2)
    assert server.connections == 1


async def test_too_many_connections_reconnects(server: Server) -> None:
    server.mode = "busy_once"
    tf = client(server).trade_feed_stream(reconnect_delay=0.01)
    errors: list[Any] = []
    tf.on("error", errors.append)
    with pytest.raises(RateLimitError):
        await tf.connect()
    await wait_for(lambda: tf.connected)
    assert tf.connected and server.connections == 2
    assert errors[0].code == "too_many_connections"
    await tf.close()


async def test_reconnects_after_drop(server: Server) -> None:
    server.mode = "drop_once"
    tf = client(server).trade_feed_stream(reconnect_delay=0.01)
    events: list[str] = []
    tf.on("reconnecting", lambda d: events.append("reconnecting"))
    tf.on("ready", lambda d: events.append("ready"))
    await tf.connect()
    await wait_for(lambda: server.connections == 2 and events.count("ready") == 2)
    await tf.close()
    assert events == ["ready", "reconnecting", "ready"]


async def test_connection_error() -> None:
    url = "ws://127.0.0.1:1/v1/trade-feed/stream"
    tf = CabalSpyID("k", trade_feed_stream_url=url).trade_feed_stream(reconnect=False)
    with pytest.raises(Exception) as e:
        await tf.connect()
    assert getattr(e.value, "code", None) == "ws_error"


def test_local_validation() -> None:
    with pytest.raises(AuthenticationError):
        CabalSpyID("").trade_feed_stream()
    tf = CabalSpyID("k").trade_feed_stream()
    assert tf.safe_url == "wss://api-id.cabalspy.xyz/v1/trade-feed/stream?api_key=***"
