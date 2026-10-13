"""Stream tests against a local websockets server that behaves like /v1/stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import serve

from cabalspy_id import APIConnectionError, CabalSpyID, PermissionError

TRADE = {
    "signature": "s1",
    "blockchain": "solana",
    "wallet": "W1",
    "mint": "M1",
    "transaction_type": "buy",
    "token_symbol": "TKN",
    "token_name": "Token",
    "token_logo": None,
    "token_amount": 10,
    "value": 1.5,
    "value_usd": 300,
    "currency": "SOL",
    "timestamp": "2026-10-13T00:00:00Z",
    "trader": {"csid_id": "u1", "username": "alice", "name": "Alice", "image_url": None, "kol": True},
}


class FakeServer:
    """Speaks the server's protocol; ``mode`` controls what a connection does."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.mode = "ok"
        self.connections = 0
        self.received: list[str] = []

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        self.paths.append(ws.request.path)
        q = {k: v[0] for k, v in parse_qs(urlsplit(ws.request.path).query).items()}
        if self.mode == "plan":
            await ws.send(
                json.dumps({"event": "error", "error": {"code": "plan_required", "message": "Pro plan needed."}})
            )
            await ws.close(code=4403)
            return
        await ws.send(
            json.dumps({"event": "subscribed", "data": {"blockchain": q.get("blockchain", "all"), "scope": "instance"}})
        )
        if self.mode == "drop_once" and self.connections == 1:
            await ws.close(code=1011)
            return
        if self.mode == "silent":
            await ws.wait_closed()
            return
        await ws.send(json.dumps({"event": "trade", "data": TRADE}))
        await ws.send(json.dumps({"event": "heartbeat", "ts": 1760000000}))
        async for msg in ws:
            self.received.append(msg)
            if msg == "ping":
                await ws.send(json.dumps({"event": "pong"}))


@pytest.fixture
async def server():
    fake = FakeServer()
    async with serve(fake.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        fake.url = f"ws://127.0.0.1:{port}/v1/stream"  # type: ignore[attr-defined]
        yield fake


def client(server: FakeServer) -> CabalSpyID:
    return CabalSpyID("csid_api_k/ey", instance="csid_inst", stream_url=server.url)  # type: ignore[attr-defined]


async def test_connect_events_and_ping(server: FakeServer) -> None:
    stream = client(server).stream(blockchain="solana")
    got: dict[str, list[Any]] = {"trade": [], "heartbeat": [], "pong": []}
    for name, items in got.items():
        stream.on(name, items.append)
    subscribed = await stream.connect()
    assert subscribed == {"blockchain": "solana", "scope": "instance"}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "csid_api_k/ey", "blockchain": "solana", "instance": "csid_inst"}
    assert "api_key=***" in stream.safe_url
    for _ in range(50):
        if got["heartbeat"]:
            break
        await asyncio.sleep(0.02)
    await stream.ping()
    for _ in range(50):
        if got["pong"]:
            break
        await asyncio.sleep(0.02)
    await stream.close()
    assert got["trade"][0]["signature"] == "s1"
    assert got["heartbeat"] == [{"ts": 1760000000}]
    assert got["pong"] == [{}]
    assert server.received == ["ping"]


async def test_plan_error_is_fatal(server: FakeServer) -> None:
    server.mode = "plan"
    stream = client(server).stream(reconnect_delay=0.01)
    errors: list[Any] = []
    stream.on("error", errors.append)
    with pytest.raises(PermissionError) as e:
        await stream.connect()
    assert e.value.code == "plan_required"
    with pytest.raises(PermissionError):
        await asyncio.wait_for(stream.run_forever(), 2)
    assert server.connections == 1
    assert len(errors) == 1


async def test_reconnects_after_drop(server: FakeServer) -> None:
    server.mode = "drop_once"
    stream = client(server).stream(reconnect_delay=0.01)
    reconnects: list[Any] = []
    trades: list[Any] = []
    stream.on("reconnecting", reconnects.append)
    stream.on("trade", trades.append)
    await stream.connect()
    for _ in range(100):
        if trades:
            break
        await asyncio.sleep(0.02)
    await stream.close()
    assert server.connections == 2
    assert reconnects and reconnects[0]["attempt"] == 1
    assert trades[0]["signature"] == "s1"


async def test_heartbeat_timeout_reconnects(server: FakeServer) -> None:
    server.mode = "silent"
    stream = client(server).stream(heartbeat_timeout=0.2, reconnect_delay=0.01)
    errors: list[Any] = []
    stream.on("error", errors.append)
    await stream.connect()
    for _ in range(100):
        if server.connections >= 2:
            break
        await asyncio.sleep(0.02)
    await stream.close()
    assert server.connections >= 2
    assert isinstance(errors[0], APIConnectionError) and errors[0].code == "heartbeat_timeout"


async def test_async_iteration(server: FakeServer) -> None:
    async with client(server).stream() as stream:
        async for trade in stream:
            assert trade["trader"]["username"] == "alice"
            break
    assert not stream.connected


async def test_iteration_ends_on_close(server: FakeServer) -> None:
    stream = client(server).stream()
    seen: list[str] = []

    async def consume() -> None:
        async for trade in stream:
            seen.append(trade["signature"])
            await stream.close()

    await asyncio.wait_for(consume(), 5)
    assert seen == ["s1"]


def test_stream_needs_key() -> None:
    from cabalspy_id import AuthenticationError

    with pytest.raises(AuthenticationError):
        CabalSpyID("").stream()
