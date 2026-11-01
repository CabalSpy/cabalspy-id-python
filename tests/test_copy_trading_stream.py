"""CopyTradingStream against a local server that behaves like /v1/copy-trading/stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import serve

from cabalspy_id import (
    COPY_TRADING_EVENTS,
    AuthenticationError,
    CabalSpyID,
    PermissionError,
    RateLimitError,
)

INSTRUCTION = {
    "id": "i1",
    "type": "copy_instruction",
    "status": "pending",
    "csid_id": "f1",
    "external_id": "u1",
    "action": {"side": "buy", "amount_usd": 20.0, "symbol": "CPT"},
}
EVENTS = [
    {"event": "copy_trade.instruction", "id": "i1", "data": INSTRUCTION},
    {"event": "copy_trade.instruction", "id": "i2", "data": {**INSTRUCTION, "id": "i2", "external_id": None}},
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
            "busy": ("too_many_connections", "At most 5 copy trading stream connections per API key."),
        }.get(self.mode)
        if deny or (self.mode == "busy_once" and self.connections == 1):
            code, message = deny or ("too_many_connections", "busy")
            await ws.send(json.dumps({"event": "error", "error": {"code": code, "message": message}}))
            await ws.close(code=4403)
            return
        await ws.send(json.dumps({"event": "ready", "data": {"events": list(COPY_TRADING_EVENTS)}}))
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
        s.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/copy-trading/stream"  # type: ignore[attr-defined]
        yield s


def client(s: Server, **kwargs: Any) -> CabalSpyID:
    return CabalSpyID("k", copy_trading_stream_url=s.url, **kwargs)  # type: ignore[attr-defined]


async def wait_for(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)


async def test_events_are_parsed(server: Server) -> None:
    cs = client(server, instance="csid_app").copy_trading_stream()
    got: list[tuple[str, Any]] = []
    for name in (*COPY_TRADING_EVENTS, "heartbeat", "pong"):
        cs.on(name, lambda d, name=name: got.append((name, d)))
    ready = await cs.connect()
    assert ready == {"events": ["copy_trade.instruction"]}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "k", "instance": "csid_app"}
    assert "k" not in cs.safe_url.split("api_key=")[1]
    await wait_for(lambda: len(got) >= 3)
    await cs.ping()
    await wait_for(lambda: got[-1][0] == "pong")
    await cs.close()
    assert [n for n, _ in got] == ["heartbeat", "copy_trade.instruction", "copy_trade.instruction", "pong"]
    assert got[1][1]["action"]["amount_usd"] == 20.0
    assert got[1][1]["external_id"] == "u1"
    assert got[2][1]["id"] == "i2"
    assert got[0][1] == {"ts": 1}
    assert json.loads(server.received[0]) == {"op": "ping"}
    assert not cs.connected


async def test_async_handlers_and_decorator(server: Server) -> None:
    cs = client(server).copy_trading_stream()
    seen: list[str] = []

    @cs.on("copy_trade.instruction")
    async def on_instruction(i: Any) -> None:
        seen.append(i["id"])
        if i["id"] == "i2":
            raise ValueError("handler failed")

    errors: list[Any] = []
    cs.on("error", errors.append)
    await cs.connect()
    await wait_for(lambda: len(seen) == 2 and bool(errors))
    await cs.close()
    assert seen == ["i1", "i2"]
    assert isinstance(errors[0], ValueError)
    with pytest.raises(ValueError):
        cs.on("callout.created", print)


async def test_iteration(server: Server) -> None:
    seen: list[dict[str, Any]] = []
    async with client(server).copy_trading_stream() as cs:
        async for ev in cs:
            seen.append(ev)
            if len(seen) == 2:
                break
    assert [(e["event"], e["id"]) for e in seen] == [("copy_trade.instruction", "i1"), ("copy_trade.instruction", "i2")]
    assert seen[0]["data"]["csid_id"] == "f1"


async def test_iteration_without_context_manager(server: Server) -> None:
    cs = client(server).copy_trading_stream()
    first: dict[str, Any] = {}
    async for ev in cs:
        first = ev
        break
    assert first["id"] == "i1"
    await cs.close()


async def test_invalid_api_key_is_fatal(server: Server) -> None:
    server.mode = "deny"
    cs = client(server).copy_trading_stream(reconnect_delay=0.01)
    with pytest.raises(PermissionError) as e:
        await cs.connect()
    assert e.value.code == "invalid_api_key"
    with pytest.raises(PermissionError):
        await asyncio.wait_for(cs.run_forever(), 2)
    assert server.connections == 1


async def test_too_many_connections_reconnects(server: Server) -> None:
    server.mode = "busy_once"
    cs = client(server).copy_trading_stream(reconnect_delay=0.01)
    errors: list[Any] = []
    cs.on("error", errors.append)
    with pytest.raises(RateLimitError):
        await cs.connect()
    await wait_for(lambda: cs.connected)
    assert cs.connected and server.connections == 2
    assert errors[0].code == "too_many_connections"
    await cs.close()


async def test_reconnects_after_drop(server: Server) -> None:
    server.mode = "drop_once"
    cs = client(server).copy_trading_stream(reconnect_delay=0.01)
    events: list[str] = []
    cs.on("reconnecting", lambda d: events.append("reconnecting"))
    cs.on("ready", lambda d: events.append("ready"))
    await cs.connect()
    await wait_for(lambda: server.connections == 2 and events.count("ready") == 2)
    await cs.close()
    assert events == ["ready", "reconnecting", "ready"]


async def test_connection_error() -> None:
    url = "ws://127.0.0.1:1/v1/copy-trading/stream"
    cs = CabalSpyID("k", copy_trading_stream_url=url).copy_trading_stream(reconnect=False)
    with pytest.raises(Exception) as e:
        await cs.connect()
    assert getattr(e.value, "code", None) == "ws_error"


def test_local_validation() -> None:
    with pytest.raises(AuthenticationError):
        CabalSpyID("").copy_trading_stream()
    cs = CabalSpyID("k").copy_trading_stream()
    assert cs.safe_url == "wss://api-id.cabalspy.xyz/v1/copy-trading/stream?api_key=***"
