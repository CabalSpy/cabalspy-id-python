"""CalloutsStream against a local server that behaves like /v1/callouts/stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import serve

from cabalspy_id import (
    CALLOUT_EVENTS,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    PermissionError,
    RateLimitError,
)

MINT = "So11111111111111111111111111111111111111112"
EVENTS = [
    {"event": "callout.created", "data": {"id": "c1", "chain": "solana", "mint": MINT, "score_x": 1.0}},
    {
        "event": "callout.update",
        "data": {
            "id": "c1",
            "chain": "solana",
            "mint": MINT,
            "price_usd": 2.0,
            "market_cap_usd": None,
            "x": 2.0,
            "peak_x": 2.0,
        },
    },
    {"event": "callout.milestone", "data": {"id": "c1", "chain": "solana", "mint": MINT, "milestone_x": 2}},
    {"event": "callout.scored", "data": {"id": "c1", "first_day": {"kind": "candles", "peak_x": 2.5}}},
    {"event": "callout.final", "data": {"id": "c1", "tracking": {"active": False, "stop_reason": "inactive"}}},
    {"event": "callout.removed", "data": {"id": "c1", "chain": "solana", "mint": MINT}},
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
            "deny": ("feature_not_enabled", "Callouts are not enabled for this instance."),
            "busy": ("too_many_connections", "At most 5 callout stream connections per API key."),
        }.get(self.mode)
        if deny or (self.mode == "busy_once" and self.connections == 1):
            code, message = deny or ("too_many_connections", "busy")
            await ws.send(json.dumps({"event": "error", "error": {"code": code, "message": message}}))
            await ws.close(code=4403)
            return
        q = {k: v[0] for k, v in parse_qs(urlsplit(ws.request.path).query).items()}
        await ws.send(
            json.dumps(
                {
                    "event": "ready",
                    "data": {"events": list(CALLOUT_EVENTS), "chain": q.get("chain"), "mint": q.get("mint")},
                }
            )
        )
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
        s.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/callouts/stream"  # type: ignore[attr-defined]
        yield s


def client(s: Server, **kwargs: Any) -> CabalSpyID:
    return CabalSpyID("k", callouts_stream_url=s.url, **kwargs)  # type: ignore[attr-defined]


async def wait_for(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)


async def test_events_are_parsed(server: Server) -> None:
    cs = client(server, instance="csid_app").callouts_stream(chain="solana", mint=MINT)
    got: list[tuple[str, Any]] = []
    for name in (*CALLOUT_EVENTS, "heartbeat", "pong"):
        cs.on(name, lambda d, name=name: got.append((name, d)))
    ready = await cs.connect()
    assert ready == {"events": list(CALLOUT_EVENTS), "chain": "solana", "mint": MINT}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "k", "chain": "solana", "mint": MINT, "instance": "csid_app"}
    assert "k" not in cs.safe_url.split("api_key=")[1]
    await wait_for(lambda: len(got) >= 7)
    await cs.ping()
    await wait_for(lambda: got[-1][0] == "pong")
    await cs.close()
    assert [n for n, _ in got] == ["heartbeat", *CALLOUT_EVENTS, "pong"]
    data = dict(got[1:7])
    assert data["callout.created"]["score_x"] == 1.0
    assert data["callout.update"]["price_usd"] == 2.0
    assert data["callout.milestone"]["milestone_x"] == 2
    assert data["callout.scored"]["first_day"]["kind"] == "candles"
    assert data["callout.final"]["tracking"]["stop_reason"] == "inactive"
    assert data["callout.removed"] == {"id": "c1", "chain": "solana", "mint": MINT}
    assert got[0][1] == {"ts": 1}
    assert json.loads(server.received[0]) == {"op": "ping"}
    assert not cs.connected


async def test_async_handlers_and_decorator(server: Server) -> None:
    cs = client(server).callouts_stream()
    seen: list[str] = []

    @cs.on("callout.created")
    async def on_created(c: Any) -> None:
        seen.append(c["id"])

    def boom(_c: Any) -> None:
        raise ValueError("handler failed")

    errors: list[Any] = []
    cs.on("callout.removed", boom)
    cs.on("error", errors.append)
    await cs.connect()
    await wait_for(lambda: bool(seen) and bool(errors))
    cs.off("callout.removed", boom)
    await cs.close()
    assert seen == ["c1"]
    assert isinstance(errors[0], ValueError)
    with pytest.raises(ValueError):
        cs.on("callout.deleted", print)


async def test_iteration(server: Server) -> None:
    seen: list[str] = []
    async with client(server).callouts_stream() as cs:
        async for ev in cs:
            seen.append(ev["event"])
            if len(seen) == len(CALLOUT_EVENTS):
                break
    assert seen == list(CALLOUT_EVENTS)


async def test_iteration_without_context_manager(server: Server) -> None:
    cs = client(server).callouts_stream()
    first: dict[str, Any] = {}
    async for ev in cs:
        first = ev
        break
    assert first["event"] == "callout.created"
    await cs.close()


async def test_feature_not_enabled_is_fatal(server: Server) -> None:
    server.mode = "deny"
    cs = client(server).callouts_stream(reconnect_delay=0.01)
    with pytest.raises(PermissionError) as e:
        await cs.connect()
    assert e.value.code == "feature_not_enabled"
    with pytest.raises(PermissionError):
        await asyncio.wait_for(cs.run_forever(), 2)
    assert server.connections == 1


async def test_too_many_connections_reconnects(server: Server) -> None:
    server.mode = "busy_once"
    cs = client(server).callouts_stream(reconnect_delay=0.01)
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
    cs = client(server).callouts_stream(reconnect_delay=0.01)
    events: list[str] = []
    cs.on("reconnecting", lambda d: events.append("reconnecting"))
    cs.on("ready", lambda d: events.append("ready"))
    await cs.connect()
    await wait_for(lambda: server.connections == 2 and events.count("ready") == 2)
    await cs.close()
    assert events == ["ready", "reconnecting", "ready"]


async def test_connection_error() -> None:
    cs = CabalSpyID("k", callouts_stream_url="ws://127.0.0.1:1/v1/callouts/stream").callouts_stream(reconnect=False)
    with pytest.raises(Exception) as e:
        await cs.connect()
    assert getattr(e.value, "code", None) == "ws_error"


def test_local_validation() -> None:
    with pytest.raises(BadRequestError) as e:
        CabalSpyID("k").callouts_stream(chain="tron")  # type: ignore[arg-type]
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError) as e:
        CabalSpyID("k").callouts_stream(mint=MINT)
    assert e.value.parameter == "chain"
    with pytest.raises(AuthenticationError):
        CabalSpyID("").callouts_stream()
    cs = CabalSpyID("k").callouts_stream()
    assert cs.safe_url == "wss://api-id.cabalspy.xyz/v1/callouts/stream?api_key=***"
