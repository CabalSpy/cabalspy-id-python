from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from websockets.asyncio.server import serve

from cabalspy_id import (
    APIConnectionError,
    AsyncCabalSpyID,
    AsyncThesisClient,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    NotFoundError,
    PermissionError,
    PlanUserLimitError,
    ServerError,
    ThesisClient,
)

from .conftest import Recorder, api_error, ok

MINT = "So11111111111111111111111111111111111111112"
USER = "0b6a3a4e-5a4f-4a59-9a59-0f5c5f5c5f5c"


def thesis(tid: str = "t1", **extra: Any) -> dict[str, Any]:
    item = {
        "id": tid,
        "chain": "solana",
        "mint": MINT,
        "kind": "thesis",
        "parent_id": None,
        "body": "Strong community, early.",
        "stance": "bull",
        "author": {
            "csid_id": USER,
            "username": "alice",
            "name": "Alice",
            "image_url": None,
            "kol_badge": True,
            "profile_url": None,
        },
        "likes": 0,
        "replies": 0,
        "reactions": {},
        "my_reactions": [],
        "via": "Test App",
        "created_at": "2026-10-13T00:00:00+00:00",
        "is_mine": False,
        "position": {
            "at_post": {
                "invested_usd": 150,
                "realized_usd": 0,
                "holding_value_usd": None,
                "pnl_usd": None,
                "pnl_percent": None,
            },
            "now": {
                "invested_usd": 150,
                "realized_usd": 0,
                "holding_value_usd": 180,
                "pnl_usd": 30,
                "pnl_percent": 20,
                "status": "holding",
            },
        },
    }
    item.update(extra)
    return item


def make(handler, **kwargs) -> tuple[CabalSpyID, Recorder]:
    rec = Recorder(handler)
    kwargs.setdefault("max_retries", 0)
    return CabalSpyID("k", http_client=rec.client(), **kwargs), rec


def pq(r: httpx.Request) -> str:
    return f"{r.url.path}?{r.url.query.decode()}"


PAGE = {"limit": 20, "total": None, "has_more": False, "next_cursor": None}


def test_reading_paths() -> None:
    csid, rec = make(lambda r: ok([thesis()], pagination=PAGE))
    csid.list_theses(blockchain="solana", mint=MINT, sort="top", stance="bull", limit=5, csid_id=USER)
    csid.thesis_summary(blockchain="solana", mint=MINT)
    csid.thesis("t1", csid_id=USER)
    csid.thesis_replies("t1", limit=10)
    csid.latest_theses(users="instance", blockchain="base")
    csid.user_theses(username="@alice")
    csid.user_theses(csid_id=USER, limit=3)
    csid.thesis_eligibility(blockchain="solana", mint=MINT, csid_id=USER)
    assert [pq(r) for r in rec.requests] == [
        f"/v1/theses?blockchain=solana&mint={MINT}&sort=top&stance=bull&limit=5&csid_id={USER}",
        f"/v1/theses/summary?blockchain=solana&mint={MINT}",
        f"/v1/theses/item?id=t1&csid_id={USER}",
        "/v1/theses/replies?id=t1&limit=10",
        "/v1/theses/latest?blockchain=base&users=instance",
        "/v1/theses/user?username=alice",
        f"/v1/theses/user?csid_id={USER}&limit=3",
        f"/v1/theses/eligibility?blockchain=solana&mint={MINT}&csid_id={USER}",
    ]


def test_writes_post_json_with_instance() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/reactions"):
            return ok({"id": "t1", "reactions": {"like": 1}})
        if r.url.path.endswith("/report"):
            return ok({"reported": True})
        if r.url.path.endswith("/delete"):
            return ok({"deleted": True})
        return ok(thesis())

    csid, rec = make(handler, instance="csid_inst")
    t = csid.post_thesis(blockchain="solana", mint=MINT, body="gm", stance="bull", csid_id=USER)
    assert t["position"]["at_post"]["invested_usd"] == 150
    csid.reply_to_thesis(thesis_id="t1", body="Nice call", csid_id=USER)
    assert csid.react_to_thesis(thesis_id="t1", emoji="like", csid_id=USER)["reactions"]["like"] == 1
    csid.report_thesis(thesis_id="t1", reason="spam", csid_id=USER)
    csid.delete_thesis(thesis_id="t1", csid_id=USER)
    assert [(r.method, pq(r), json.loads(r.content)) for r in rec.requests] == [
        (
            "POST",
            "/v1/theses?instance=csid_inst",
            {"blockchain": "solana", "mint": MINT, "body": "gm", "csid_id": USER, "stance": "bull"},
        ),
        ("POST", "/v1/theses/replies?instance=csid_inst", {"thesis_id": "t1", "body": "Nice call", "csid_id": USER}),
        (
            "POST",
            "/v1/theses/reactions?instance=csid_inst",
            {"thesis_id": "t1", "emoji": "like", "on": True, "csid_id": USER},
        ),
        ("POST", "/v1/theses/report?instance=csid_inst", {"thesis_id": "t1", "reason": "spam", "csid_id": USER}),
        ("POST", "/v1/theses/delete?instance=csid_inst", {"thesis_id": "t1", "csid_id": USER}),
    ]
    assert rec.requests[0].headers["content-type"] == "application/json"


def test_validation() -> None:
    csid, rec = make(lambda r: ok({}))
    with pytest.raises(BadRequestError):
        csid.list_theses(blockchain="solana", mint="")
    with pytest.raises(BadRequestError):
        csid.list_theses(blockchain="solana", mint=MINT, sort="hot")  # type: ignore[arg-type]
    with pytest.raises(BadRequestError) as e:
        csid.react_to_thesis(thesis_id="t", emoji="🙂", csid_id=USER)  # type: ignore[arg-type]
    assert e.value.parameter == "emoji"
    with pytest.raises(BadRequestError):
        csid.report_thesis(thesis_id="t", reason="meh", csid_id=USER)  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        csid.post_thesis(blockchain="solana", mint=MINT, body="x", csid_id="")
    with pytest.raises(BadRequestError):
        csid.user_theses(csid_id=USER, username="a")
    assert rec.requests == []


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (403, "not_a_holder", PermissionError),
        (403, "consent_required", PermissionError),
        (403, "plan_user_limit", PlanUserLimitError),
        (404, "not_found", NotFoundError),
        (400, "duplicate", BadRequestError),
    ],
)
def test_error_mapping(status: int, code: str, cls: type) -> None:
    csid, _ = make(lambda r: api_error(status, code))
    with pytest.raises(cls):
        csid.post_thesis(blockchain="solana", mint=MINT, body="x", csid_id=USER)


def test_writes_are_not_retried_after_server_or_network_errors() -> None:
    csid, rec = make(lambda r: api_error(500, "internal_error"), max_retries=3)
    with pytest.raises(ServerError):
        csid.post_thesis(blockchain="solana", mint=MINT, body="x", csid_id=USER)
    assert len(rec.requests) == 1

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("reset")

    csid, rec = make(boom, max_retries=3)
    with pytest.raises(APIConnectionError):
        csid.reply_to_thesis(thesis_id="t", body="x", csid_id=USER)
    assert len(rec.requests) == 1


def test_write_retried_after_api_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    answers = iter([api_error(429, "rate_limit_exceeded", headers={"Retry-After": "1"}), ok(thesis())])
    csid, rec = make(lambda r: next(answers), max_retries=2)
    csid.post_thesis(blockchain="solana", mint=MINT, body="x", csid_id=USER)
    assert len(rec.requests) == 2


def test_iter_theses() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor=" in r.url.query.decode():
            return ok([thesis("t2")], pagination=PAGE)
        return ok([thesis("t1")], pagination={**PAGE, "has_more": True, "next_cursor": "c"})

    csid, _ = make(handler)
    assert [t["id"] for t in csid.iter_theses(blockchain="solana", mint=MINT)] == ["t1", "t2"]


async def test_async_theses() -> None:
    rec = Recorder(lambda r: ok([thesis()], pagination=PAGE) if r.method == "GET" else ok(thesis()))
    async with AsyncCabalSpyID("k", http_client=rec.async_client(), max_retries=0) as csid:
        assert [t["id"] async for t in csid.iter_theses(blockchain="solana", mint=MINT)] == ["t1"]
        assert (await csid.post_thesis(blockchain="solana", mint=MINT, body="x", csid_id=USER))["id"] == "t1"


# ── public thesis API ────────────────────────────────────────────────────────

BASE = "https://id.cabalspy.xyz/thesis/v1"


def public_handler(r: httpx.Request) -> httpx.Response:
    path = r.url.path.removeprefix("/thesis/v1")
    if r.method == "GET" and path == f"/tokens/solana/{MINT}":
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [thesis()],
                "pagination": {"limit": 20, "has_more": False, "next_cursor": None},
                "token": {
                    "chain": "solana",
                    "mint": MINT,
                    "name": "Solana",
                    "symbol": "SOL",
                    "logo": None,
                    "price_usd": 100,
                },
                "summary": {"theses": 1, "bull": 1, "bear": 0, "authors": 1},
            },
        )
    if path.endswith("/me"):
        return httpx.Response(
            200, json={"success": True, "data": {"can_post": True, "can_reply": True, "holder": True, "paused": False}}
        )
    if r.method == "DELETE":
        return httpx.Response(200, json={"success": True, "data": {"deleted": True}})
    if path.endswith("/reactions"):
        return httpx.Response(200, json={"success": True, "data": {"id": "t1", "reactions": {"🚀": 1}}})
    if path.endswith("/report"):
        return httpx.Response(200, json={"success": True, "data": {"reported": True}})
    return httpx.Response(201, json={"success": True, "data": thesis()})


def test_public_client_reads_and_writes() -> None:
    rec = Recorder(public_handler)
    tc = ThesisClient(http_client=rec.client())
    page = tc.list("solana", MINT, sort="top")
    assert page.items[0]["id"] == "t1" and page.token["symbol"] == "SOL" and page.summary["bull"] == 1
    assert "authorization" not in rec.requests[0].headers
    with pytest.raises(AuthenticationError) as e:
        tc.post("solana", MINT, body="x")
    assert e.value.code == "sign_in_required"
    tc.set_access_token("at-1")
    assert tc.me("solana", MINT)["can_post"] is True
    tc.post("solana", MINT, body="gm", stance="bear")
    tc.reply("t1", "agree")
    tc.react("t1", "🚀")
    tc.report("t1", "scam", "rug")
    tc.delete("t1")
    writes = rec.requests[1:]
    assert [
        (r.method, str(r.url).removeprefix(BASE), json.loads(r.content) if r.content else None) for r in writes
    ] == [
        ("GET", f"/tokens/solana/{MINT}/me", None),
        ("POST", f"/tokens/solana/{MINT}", {"body": "gm", "stance": "bear"}),
        ("POST", "/items/t1/replies", {"body": "agree"}),
        ("POST", "/items/t1/reactions", {"emoji": "🚀", "on": True}),
        ("POST", "/items/t1/report", {"reason": "scam", "note": "rug"}),
        ("DELETE", "/items/t1", None),
    ]
    assert all(r.headers["authorization"] == "Bearer at-1" for r in writes)


def test_public_client_errors() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "/tokens/" in r.url.path:
            return httpx.Response(
                403, json={"success": False, "error": {"code": "not_a_holder", "message": "Holders only"}}
            )
        return httpx.Response(401, json={"success": False, "error": {"code": "invalid_token", "message": "Expired"}})

    tc = ThesisClient("at", http_client=Recorder(handler).client())
    with pytest.raises(PermissionError) as e:
        tc.post("solana", MINT, body="x")
    assert e.value.code == "not_a_holder"
    with pytest.raises(AuthenticationError):
        tc.reply("t1", "x")
    with pytest.raises(BadRequestError):
        tc.summary("tron", MINT)  # type: ignore[arg-type]


async def test_async_public_client() -> None:
    async with AsyncThesisClient(http_client=Recorder(public_handler).async_client()) as tc:
        assert [t["id"] async for t in tc.iterate("solana", MINT)] == ["t1"]


# ── live: stream theses and the public socket ────────────────────────────────


@pytest.fixture
async def ws_server():
    state: dict[str, Any] = {"paths": [], "mode": "stream"}

    async def handler(ws: Any) -> None:
        state["paths"].append(ws.request.path)
        if state["mode"] == "refuse":
            await ws.close(code=1008)
            return
        if state["mode"] == "stream":
            q = {k: v[0] for k, v in parse_qs(urlsplit(ws.request.path).query).items()}
            await ws.send(
                json.dumps(
                    {
                        "event": "subscribed",
                        "data": {
                            "blockchain": q.get("blockchain", "all"),
                            "events": q.get("events", "trades").split(","),
                            "mint": q.get("mint"),
                            "scope": "instance",
                        },
                    }
                )
            )
            await ws.send(json.dumps({"event": "thesis", "data": {"blockchain": "solana", **thesis("t9")}}))
            await ws.send(
                json.dumps(
                    {
                        "event": "thesis.reply",
                        "data": {"blockchain": "solana", **thesis("r1", kind="reply", parent_id="t9")},
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "event": "thesis.reaction",
                        "data": {"blockchain": "solana", "mint": MINT, "id": "t9", "reactions": {"like": 2}},
                    }
                )
            )
            await ws.send(
                json.dumps({"event": "thesis.removed", "data": {"blockchain": "solana", "mint": MINT, "id": "t9"}})
            )
        else:  # public live socket
            await ws.send(json.dumps({"type": "thesis", "chain": "solana", "mint": MINT, "data": thesis("t5")}))
            await ws.send(
                json.dumps(
                    {
                        "type": "reaction",
                        "chain": "solana",
                        "mint": MINT,
                        "data": {"id": "t5", "reactions": {"like": 1}},
                    }
                )
            )
            await ws.send(json.dumps({"type": "removed", "chain": "solana", "mint": MINT, "data": {"id": "t5"}}))
            await ws.send(json.dumps({"type": "heartbeat"}))
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as srv:
        state["port"] = srv.sockets[0].getsockname()[1]
        yield state


async def test_stream_thesis_events(ws_server: dict[str, Any]) -> None:
    csid = CabalSpyID("k", stream_url=f"ws://127.0.0.1:{ws_server['port']}/v1/stream")
    stream = csid.stream(events=["trades", "theses"], blockchain="solana", mint=MINT)
    got: list[str] = []
    stream.on("thesis", lambda t: got.append(f"thesis:{t['id']}"))
    stream.on("thesis.reply", lambda t: got.append(f"reply:{t['parent_id']}"))
    stream.on("thesis.reaction", lambda r: got.append(f"reaction:{r['reactions']['like']}"))
    stream.on("thesis.removed", lambda r: got.append(f"removed:{r['id']}"))
    sub = await stream.connect()
    assert sub["mint"] == MINT
    q = {k: v[0] for k, v in parse_qs(urlsplit(ws_server["paths"][0]).query).items()}
    assert q == {"api_key": "k", "events": "trades,theses", "blockchain": "solana", "mint": MINT}
    for _ in range(100):
        if len(got) == 4:
            break
        await asyncio.sleep(0.02)
    await stream.close()
    assert got == ["thesis:t9", "reply:t9", "reaction:2", "removed:t9"]


async def test_stream_theses_iterator(ws_server: dict[str, Any]) -> None:
    csid = CabalSpyID("k", stream_url=f"ws://127.0.0.1:{ws_server['port']}/v1/stream")
    seen: list[str] = []
    async with csid.stream(events=["theses"]) as stream:
        async for ev in stream.theses():
            seen.append(ev["event"])
            if len(seen) == 4:
                break
    assert seen == ["thesis", "thesis.reply", "thesis.reaction", "thesis.removed"]


def test_stream_validation() -> None:
    csid = CabalSpyID("k")
    with pytest.raises(BadRequestError):
        csid.stream(events=["news"])  # type: ignore[list-item]
    with pytest.raises(BadRequestError):
        csid.stream(events=["theses"], mint=MINT)


async def test_public_live(ws_server: dict[str, Any]) -> None:
    ws_server["mode"] = "public"
    tc = ThesisClient(ws_url=f"ws://127.0.0.1:{ws_server['port']}/thesis/v1/ws")
    live = tc.live("solana", MINT)
    got: list[str] = []
    live.on("thesis", lambda t: got.append(t["id"]))
    live.on("reaction", lambda r: got.append(f"r:{r['id']}"))
    live.on("removed", lambda r: got.append(f"x:{r['id']}"))
    live.on("heartbeat", lambda _h: got.append("hb"))
    await live.connect()
    assert ws_server["paths"][0] == f"/thesis/v1/ws/solana/{MINT}"
    for _ in range(100):
        if len(got) == 4:
            break
        await asyncio.sleep(0.02)
    await live.close()
    assert got == ["t5", "r:t5", "x:t5", "hb"]


async def test_public_live_refused_is_final(ws_server: dict[str, Any]) -> None:
    ws_server["mode"] = "refuse"
    live = ThesisClient(ws_url=f"ws://127.0.0.1:{ws_server['port']}/thesis/v1/ws").live(
        "solana", MINT, reconnect_delay=0.01
    )
    await live.connect()
    with pytest.raises(PermissionError):
        await asyncio.wait_for(live.run_forever(), 3)
    assert len(ws_server["paths"]) == 1
