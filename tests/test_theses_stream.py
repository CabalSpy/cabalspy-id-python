"""ThesesStream against a local server that behaves like /v1/theses/stream, plus scope options."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from websockets.asyncio.server import serve

from cabalspy_id import AuthenticationError, BadRequestError, CabalSpyID, PermissionError, ThesisClient

from .conftest import Recorder, ok

MINT = "So11111111111111111111111111111111111111112"
EVM = "0xAbC0000000000000000000000000000000000001"


class Server:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.frames: list[list[Any]] = []
        self.mode = "ok"
        self.connections = 0

    async def handler(self, ws: Any) -> None:
        self.connections += 1
        self.paths.append(ws.request.path)
        frames: list[Any] = []
        self.frames.append(frames)
        if self.mode == "deny":
            await ws.send(json.dumps({"event": "error", "error": {"code": "invalid_api_key", "message": "bad key"}}))
            await ws.close(code=4403)
            return
        q = {k: v[0] for k, v in parse_qs(urlsplit(ws.request.path).query).items()}
        await ws.send(json.dumps({"event": "ready", "data": {"scope": q.get("scope", "global"), "max_tokens": 200}}))
        if self.mode == "drop_once" and self.connections == 1:
            await asyncio.sleep(0.1)
            await ws.close(code=1011)
            return
        async for raw in ws:
            frame = json.loads(raw)
            frames.append(frame)
            if frame.get("op") == "ping":
                await ws.send(json.dumps({"event": "pong", "data": {}}))
            elif frame.get("op") == "subscribe" and frame.get("tokens") == [{"blockchain": "solana", "mint": "bad"}]:
                await ws.send(
                    json.dumps({"event": "error", "error": {"code": "invalid_parameter", "message": "bad mint"}})
                )
            elif frame.get("op") in ("subscribe", "unsubscribe"):
                await ws.send(
                    json.dumps(
                        {
                            "event": "subscribed",
                            "data": {"all": bool(frame.get("all")), "tokens": frame.get("tokens", [])},
                        }
                    )
                )
                if frame.get("op") == "subscribe":
                    await ws.send(
                        json.dumps({"event": "thesis", "data": {"id": "t1", "blockchain": "solana", "mint": MINT}})
                    )
                    await ws.send(
                        json.dumps(
                            {"event": "thesis.removed", "data": {"id": "t1", "blockchain": "solana", "mint": MINT}}
                        )
                    )


@pytest.fixture
async def server():
    s = Server()
    async with serve(s.handler, "127.0.0.1", 0) as srv:
        s.url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/v1/theses/stream"  # type: ignore[attr-defined]
        yield s


def client(s: Server) -> CabalSpyID:
    return CabalSpyID("k", theses_stream_url=s.url)  # type: ignore[attr-defined]


async def wait_for(cond: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)


async def test_subscribe_flow_and_events(server: Server) -> None:
    ts = client(server).theses_stream(scope="instance")
    got: list[str] = []
    ts.on("thesis", lambda t: got.append(f"thesis:{t['id']}"))
    ts.on("thesis.removed", lambda r: got.append(f"removed:{r['id']}"))
    ts.on("subscribed", lambda s: got.append(f"subscribed:{len(s['tokens'])}"))
    ts.on("pong", lambda _p: got.append("pong"))
    await ts.subscribe([{"blockchain": "solana", "mint": MINT}])  # remembered, sent on ready
    ready = await ts.connect()
    assert ready == {"scope": "instance", "max_tokens": 200}
    q = {k: v[0] for k, v in parse_qs(urlsplit(server.paths[0]).query).items()}
    assert q == {"api_key": "k", "scope": "instance"}
    await ts.subscribe([{"blockchain": "solana", "mint": MINT}, {"blockchain": "base", "mint": EVM}])
    await ts.unsubscribe([{"blockchain": "base", "mint": EVM.lower()}])
    await ts.subscribe_all()
    await ts.unsubscribe_all()
    await ts.ping()
    await wait_for(lambda: "pong" in got)
    await ts.close()
    assert server.frames[0] == [
        {"op": "subscribe", "tokens": [{"blockchain": "solana", "mint": MINT}]},
        {"op": "subscribe", "tokens": [{"blockchain": "base", "mint": EVM}]},
        {"op": "unsubscribe", "tokens": [{"blockchain": "base", "mint": EVM.lower()}]},
        {"op": "subscribe", "all": True},
        {"op": "unsubscribe", "all": True},
        {"op": "ping"},
    ]
    assert got[:3] == ["subscribed:1", "thesis:t1", "removed:t1"]
    assert ts.subscriptions == {"all": False, "tokens": []}


async def test_bad_frame_is_not_fatal(server: Server) -> None:
    ts = client(server).theses_stream()
    errors: list[Any] = []
    ts.on("error", errors.append)
    await ts.connect()
    await ts._send({"op": "subscribe", "tokens": [{"blockchain": "solana", "mint": "bad"}]})
    await wait_for(lambda: bool(errors))
    assert isinstance(errors[0], BadRequestError) and errors[0].code == "invalid_parameter"
    assert ts.connected
    await ts.close()


async def test_refusal_is_fatal(server: Server) -> None:
    server.mode = "deny"
    ts = client(server).theses_stream(reconnect_delay=0.01)
    with pytest.raises(PermissionError) as e:
        await ts.connect()
    assert e.value.code == "invalid_api_key"
    with pytest.raises(PermissionError):
        await asyncio.wait_for(ts.run_forever(), 2)
    assert server.connections == 1


async def test_resubscribes_after_reconnect(server: Server) -> None:
    server.mode = "drop_once"
    ts = client(server).theses_stream(reconnect_delay=0.01)
    await ts.subscribe_all()
    await ts.subscribe([{"blockchain": "solana", "mint": MINT}])
    await ts.connect()
    await wait_for(lambda: server.connections == 2 and len(server.frames[1]) >= 2)
    await ts.close()
    assert server.frames[1][:2] == [
        {"op": "subscribe", "all": True},
        {"op": "subscribe", "tokens": [{"blockchain": "solana", "mint": MINT}]},
    ]


async def test_iteration(server: Server) -> None:
    seen: list[str] = []
    async with client(server).theses_stream() as ts:
        await ts.subscribe_all()
        async for ev in ts:
            seen.append(ev["event"])
            if len(seen) == 2:
                break
    assert seen == ["thesis", "thesis.removed"]


async def test_local_validation() -> None:
    ts = CabalSpyID("k").theses_stream()
    with pytest.raises(BadRequestError):
        await ts.subscribe([{"blockchain": "tron", "mint": "x"}])
    with pytest.raises(BadRequestError) as e:
        await ts.subscribe([{"blockchain": "base", "mint": f"0x{i:040x}"} for i in range(201)])
    assert e.value.code == "too_many_tokens"
    with pytest.raises(BadRequestError):
        CabalSpyID("k").theses_stream(scope="mine")  # type: ignore[arg-type]


# ── scope on reads ───────────────────────────────────────────────────────────


def test_data_api_scope() -> None:
    rec = Recorder(lambda r: ok([], pagination={"limit": 20, "has_more": False, "next_cursor": None}))
    csid = CabalSpyID("k", http_client=rec.client(), max_retries=0)
    csid.list_theses(blockchain="solana", mint=MINT, scope="instance")
    csid.thesis_summary(blockchain="solana", mint=MINT, scope="global")
    csid.latest_theses(scope="instance")
    list(csid.iter_theses(blockchain="solana", mint=MINT, scope="instance"))
    scopes = [parse_qs(r.url.query.decode()).get("scope", [None])[0] for r in rec.requests]
    assert scopes == ["instance", "global", "instance", "instance"]
    with pytest.raises(BadRequestError):
        csid.list_theses(blockchain="solana", mint=MINT, scope="mine")  # type: ignore[arg-type]


def test_public_client_scope_and_attribution() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.method == "POST":
            return httpx.Response(201, json={"success": True, "data": {"id": "t"}})
        if r.url.path.endswith("/summary"):
            return httpx.Response(200, json={"success": True, "data": {"theses": 0}})
        return httpx.Response(200, json={"success": True, "data": [], "pagination": {}, "token": {}, "summary": {}})

    rec = Recorder(handler)
    tc = ThesisClient("at", scope="instance", client_id="csid_app", http_client=rec.client())
    tc.list("solana", MINT)
    tc.summary("solana", MINT, scope="global")
    tc.post("solana", MINT, body="gm")
    tc.reply("t", "yes")
    qs = [dict(parse_qs(r.url.query.decode())) for r in rec.requests[:2]]
    assert qs == [{"scope": ["instance"], "client_id": ["csid_app"]}, {"scope": ["global"]}]
    assert json.loads(rec.requests[2].content) == {"body": "gm", "client_id": "csid_app"}
    assert json.loads(rec.requests[3].content) == {"body": "yes", "client_id": "csid_app"}
    assert tc.live("solana", MINT).url.endswith(f"/ws/solana/{MINT}?client_id=csid_app&scope=instance")
    assert (
        ThesisClient(client_id="csid_app")
        .live("solana", MINT, scope="global")
        .url.endswith("?client_id=csid_app&scope=global")
    )
    with pytest.raises(AuthenticationError):
        ThesisClient(scope="instance")
