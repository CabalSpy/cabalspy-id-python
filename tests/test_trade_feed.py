"""Trade Feed (feed, traders, notifications), against mocked HTTP."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from cabalspy_id import (
    TRADE_FEED_FILTERS,
    TRADE_FEED_WEBHOOK_EVENTS,
    WEBHOOK_EVENTS,
    AsyncCabalSpyID,
    BadRequestError,
    CabalSpyID,
    ConflictError,
    NotFoundError,
    PermissionError,
    PlanUserLimitError,
    RateLimitError,
    ServerError,
    TradeFeedItem,
    api,
)

from .conftest import Recorder, api_error, ok
from .test_platform_users import call, make, query

KEY = "csid_api_testkey"
MINT = "3Pkrq4MmLvDXyn1fa3sz5MekKRkZkc1iLDcz5AzWpump"

TRADER: dict[str, Any] = {
    "csid_id": "t1",
    "username": "MazeCCC",
    "name": "Maze",
    "image_url": None,
    "kol": True,
    "profile_url": "https://id.cabalspy.xyz/u/MazeCCC",
}
LINKS: dict[str, Any] = {"token": "https://app.cabalspy.xyz/token/x", "terminal": None, "profile": None}
TRADE_ITEM: dict[str, Any] = {
    "id": "t3b1f0c9e8d7a6b5c4d3e2f1a0b9c8d7e",
    "type": "trade",
    "timestamp": "2026-11-01T18:40:05Z",
    "trader": TRADER,
    "trade": {
        "blockchain": "solana",
        "mint": MINT,
        "symbol": "CPT",
        "name": "Copycat",
        "logo": None,
        "side": "sell",
        "label": "partial",
        "sold_percent": 50.0,
        "amount_native": 1.5,
        "currency": "SOL",
        "amount_usd": 225.0,
        "token_amount": 500.0,
        "price_usd": 0.45,
        "pnl_usd": 150.0,
        "pnl_percent": 200.0,
        "wallet": "W1",
        "wallet_url": None,
        "tx_signature": "2Bq7",
        "tx_url": None,
    },
    "links": LINKS,
    "cursor": "c1",
}
THESIS_ITEM: dict[str, Any] = {
    "id": "h8a1d2c3b",
    "type": "thesis",
    "timestamp": "2026-11-01T18:21:44Z",
    "trader": TRADER,
    "thesis": {
        "id": "8a1d2c3b",
        "blockchain": "solana",
        "mint": MINT,
        "symbol": "CPT",
        "name": "Copycat",
        "logo": None,
        "stance": "bull",
        "body": "Dev still holding.",
        "likes": 12,
        "replies": 3,
        "url": "https://id.cabalspy.xyz/try/thesis?chain=solana&mint=x",
    },
    "links": LINKS,
    "cursor": "c2",
}
SETTINGS: dict[str, Any] = {
    "notify_buys": True,
    "notify_sells": True,
    "notify_theses": True,
    "min_native": {"SOL": 0.5, "BNB": 0.0, "ETH": 0.0},
    "muted": False,
    "copy": {
        "enabled": False,
        "mode": "fixed_usd",
        "amount_usd": 50.0,
        "percent": 100.0,
        "max_usd": None,
        "sides": "both",
        "slippage_bps": 300,
        "updated_at": None,
    },
}
ENTRY: dict[str, Any] = {
    "trader": TRADER,
    "trading_public": True,
    "added_at": "2026-10-20T09:12:00+00:00",
    "in_trade_feeds": 128,
    "settings": SETTINGS,
}
NOTIFICATION: dict[str, Any] = {
    "id": 48213,
    "event": "trade_feed.trade",
    "text": "Trade Feed: @MazeCCC sold $CPT",
    "created_at": "2026-11-01T18:40:06Z",
    "data": TRADE_ITEM,
}


# ── every endpoint: method, path, query / body ───────────────────────────────


def test_every_trade_feed_endpoint() -> None:
    csid, rec = make()
    csid.trade_feed("u1")
    csid.trade_feed(csid_id="f1", filter="theses", limit=5, cursor="abc")
    csid.trade_feed_traders("u1")
    csid.trade_feed_traders(csid_id="f1", limit=300, cursor="MTAw")
    csid.add_trade_feed_trader("u1", trader="@MazeCCC", min_sol=0.5)
    csid.add_trade_feed_trader(
        csid_id="f1",
        trader_external_id="u2",
        notify_buys=True,
        notify_sells=False,
        notify_theses=True,
        min_sol=0,
        min_bnb=1,
        min_eth=0.25,
        muted=False,
    )
    csid.add_trade_feed_trader("u1", trader="t1")
    csid.remove_trade_feed_trader("u1", trader="MazeCCC")
    csid.remove_trade_feed_trader(csid_id="f1", trader_external_id="u2")
    csid.trade_feed_notifications("u1")
    csid.trade_feed_notifications(csid_id="f1", limit=20, cursor="n1")

    assert [call(r) for r in rec.requests] == [
        ("GET", "/v1/trade-feed", {"external_id": "u1"}),
        ("GET", "/v1/trade-feed", {"csid_id": "f1", "filter": "theses", "limit": "5", "cursor": "abc"}),
        ("GET", "/v1/trade-feed/traders", {"external_id": "u1"}),
        ("GET", "/v1/trade-feed/traders", {"csid_id": "f1", "limit": "300", "cursor": "MTAw"}),
        ("POST", "/v1/trade-feed/traders", {"external_id": "u1", "trader": "@MazeCCC", "min_sol": 0.5}),
        (
            "POST",
            "/v1/trade-feed/traders",
            {
                "csid_id": "f1",
                "trader_external_id": "u2",
                "notify_buys": True,
                "notify_sells": False,
                "notify_theses": True,
                "min_sol": 0,
                "min_bnb": 1,
                "min_eth": 0.25,
                "muted": False,
            },
        ),
        ("POST", "/v1/trade-feed/traders", {"external_id": "u1", "trader": "t1"}),
        ("POST", "/v1/trade-feed/traders/delete", {"external_id": "u1", "trader": "MazeCCC"}),
        ("POST", "/v1/trade-feed/traders/delete", {"csid_id": "f1", "trader_external_id": "u2"}),
        ("GET", "/v1/trade-feed/notifications", {"external_id": "u1"}),
        ("GET", "/v1/trade-feed/notifications", {"csid_id": "f1", "limit": "20", "cursor": "n1"}),
    ]
    assert all(r.headers["Authorization"] == f"Bearer {KEY}" for r in rec.requests)


def test_returns_items_traders_and_results() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        path = r.url.path
        if path == "/v1/trade-feed":
            return ok([TRADE_ITEM, THESIS_ITEM], pagination={"limit": 30, "next_cursor": None, "has_more": False})
        if path == "/v1/trade-feed/traders" and r.method == "GET":
            pagination = {"limit": 100, "total": 1, "max": 300, "next_cursor": None, "has_more": False}
            return ok([ENTRY], pagination=pagination)
        if path == "/v1/trade-feed/traders":
            data = {"in_trade_feed": True, "created": True, "trader": TRADER, "settings": SETTINGS}
            return httpx.Response(201, json={"success": True, "data": data})
        if path == "/v1/trade-feed/traders/delete":
            return ok({"in_trade_feed": False, "removed": True})
        return ok([NOTIFICATION], pagination={"limit": 50, "next_cursor": None, "has_more": False})

    csid, _ = make(handler)
    items: list[TradeFeedItem] = csid.trade_feed("u1")
    trade, thesis = items
    assert trade["type"] == "trade" and trade["trade"]["label"] == "partial" and trade["trade"]["sold_percent"] == 50
    assert thesis["type"] == "thesis" and thesis["thesis"]["stance"] == "bull"
    entry = csid.trade_feed_traders("u1")[0]
    assert entry["settings"]["min_native"]["SOL"] == 0.5 and entry["settings"]["copy"]["enabled"] is False
    assert entry["in_trade_feeds"] == 128 and entry["trading_public"]
    page = csid.get_raw("/trade-feed/traders", {"external_id": "u1"})
    assert page.pagination == {"limit": 100, "total": 1, "max": 300, "next_cursor": None, "has_more": False}
    added = csid.add_trade_feed_trader("u1", trader="MazeCCC")
    assert added["created"] and added["in_trade_feed"] and added["trader"]["username"] == "MazeCCC"
    assert csid.remove_trade_feed_trader("u1", trader="MazeCCC") == {"in_trade_feed": False, "removed": True}
    n = csid.trade_feed_notifications("u1")[0]
    assert n["id"] == 48213 and n["event"] == "trade_feed.trade" and n["data"]["id"] == TRADE_ITEM["id"]


def test_trade_feed_validation() -> None:
    csid, rec = make()
    with pytest.raises(BadRequestError) as e:
        csid.trade_feed()  # no user
    assert e.value.parameter == "external_id|csid_id"
    with pytest.raises(BadRequestError):
        csid.trade_feed("u1", csid_id="f1")  # both
    with pytest.raises(BadRequestError) as e:
        csid.trade_feed("u1", filter="mints")  # type: ignore[arg-type]
    assert e.value.allowed == list(TRADE_FEED_FILTERS)
    for bad_limit in (0, 101, True, 2.5):
        with pytest.raises(BadRequestError) as e:
            csid.trade_feed("u1", limit=bad_limit)  # type: ignore[arg-type]
        assert e.value.parameter == "limit"
    with pytest.raises(BadRequestError):
        csid.trade_feed_notifications("u1", limit=101)
    with pytest.raises(BadRequestError):
        csid.trade_feed_traders("u1", limit=301)
    with pytest.raises(BadRequestError):
        csid.trade_feed_traders()
    with pytest.raises(BadRequestError) as e:
        csid.add_trade_feed_trader("u1")  # no trader
    assert e.value.parameter == "trader"
    with pytest.raises(BadRequestError) as e:
        csid.add_trade_feed_trader("u1", trader="a", trader_external_id="b")
    assert e.value.parameter == "trader|trader_external_id"
    with pytest.raises(BadRequestError):
        csid.add_trade_feed_trader(trader="a")  # no user
    bad: list[tuple[str, Any]] = [
        ("notify_buys", "yes"),
        ("notify_sells", 1),
        ("notify_theses", "false"),
        ("muted", 0),
        ("min_sol", -1),
        ("min_bnb", 1_000_001),
        ("min_eth", "0.5"),
        ("min_sol", True),
        ("min_sol", float("nan")),
    ]
    for name, value in bad:
        with pytest.raises(BadRequestError) as e:
            csid.add_trade_feed_trader("u1", trader="t1", **{name: value})
        assert e.value.parameter == name, (name, value)
    with pytest.raises(BadRequestError) as e:
        csid.remove_trade_feed_trader("u1")
    assert e.value.parameter == "trader"
    with pytest.raises(BadRequestError):
        csid.remove_trade_feed_trader(trader="t1")
    with pytest.raises(BadRequestError):
        list(csid.iter_trade_feed("u1", filter="nope"))  # type: ignore[arg-type]
    assert rec.requests == []


def test_none_settings_are_not_sent() -> None:
    csid, rec = make()
    csid.add_trade_feed_trader("u1", trader="t1", notify_buys=None, min_sol=None, muted=True)
    assert call(rec.requests[0])[2] == {"external_id": "u1", "trader": "t1", "muted": True}


# ── iterators, async ─────────────────────────────────────────────────────────


def test_iterators_follow_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if query(r).get("cursor") is None:
            return ok([{"id": "a"}, {"id": "b"}], pagination={"limit": 2, "has_more": True, "next_cursor": "n1"})
        return ok([{"id": "c"}], pagination={"limit": 2, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    assert [i["id"] for i in csid.iter_trade_feed("u1", filter="buys", limit=2)] == ["a", "b", "c"]
    assert [i["id"] for i in csid.iter_trade_feed_traders(csid_id="f1", limit=2)] == ["a", "b", "c"]
    assert [i["id"] for i in csid.iter_trade_feed_notifications("u1")] == ["a", "b", "c"]
    assert [call(r) for r in rec.requests] == [
        ("GET", "/v1/trade-feed", {"external_id": "u1", "filter": "buys", "limit": "2"}),
        ("GET", "/v1/trade-feed", {"external_id": "u1", "filter": "buys", "limit": "2", "cursor": "n1"}),
        ("GET", "/v1/trade-feed/traders", {"csid_id": "f1", "limit": "2"}),
        ("GET", "/v1/trade-feed/traders", {"csid_id": "f1", "limit": "2", "cursor": "n1"}),
        ("GET", "/v1/trade-feed/notifications", {"external_id": "u1"}),
        ("GET", "/v1/trade-feed/notifications", {"external_id": "u1", "cursor": "n1"}),
    ]


async def test_async_trade_feed() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        path = r.url.path
        if r.method == "POST" and path == "/v1/trade-feed/traders":
            return ok({"in_trade_feed": True, "created": False, "trader": TRADER, "settings": SETTINGS})
        if path == "/v1/trade-feed/traders/delete":
            return ok({"in_trade_feed": False, "removed": False})
        if query(r).get("cursor"):
            return ok([{"id": "b"}], pagination={"has_more": False, "next_cursor": None})
        return ok([{"id": "a"}], pagination={"has_more": True, "next_cursor": "n"})

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.trade_feed("u1"))[0]["id"] == "a"
        assert [i["id"] async for i in csid.iter_trade_feed(csid_id="f1", filter="sells")] == ["a", "b"]
        assert [i["id"] async for i in csid.iter_trade_feed_traders("u1")] == ["a", "b"]
        assert [i["id"] async for i in csid.iter_trade_feed_notifications("u1", limit=1)] == ["a", "b"]
        assert (await csid.trade_feed_traders("u1"))[0]["id"] == "a"
        assert (await csid.trade_feed_notifications("u1"))[0]["id"] == "a"
        added = await csid.add_trade_feed_trader("u1", trader="t1", notify_theses=False)
        assert added["created"] is False
        assert (await csid.remove_trade_feed_trader("u1", trader="t1"))["removed"] is False
    assert call(rec.requests[-2]) == (
        "POST",
        "/v1/trade-feed/traders",
        {"external_id": "u1", "trader": "t1", "notify_theses": False},
    )


# ── errors ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (400, "cannot_add_self", BadRequestError),
        (403, "consent_required", PermissionError),
        (403, "trading_private", PermissionError),
        (403, "plan_user_limit", PlanUserLimitError),
        (404, "trader_not_found", NotFoundError),
        (404, "platform_user_not_found", NotFoundError),
        (409, "trade_feed_full", ConflictError),
        (429, "rate_limited", RateLimitError),
        (503, "service_unavailable", ServerError),
    ],
)
def test_add_errors_are_not_retried(status: int, code: str, cls: type[Exception]) -> None:
    csid, rec = make(lambda r: api_error(status, code, headers={"Retry-After": "0"}), max_retries=2)
    with pytest.raises(cls) as e:
        csid.add_trade_feed_trader("u1", trader="MazeCCC")
    assert e.value.code == code  # type: ignore[attr-defined]
    assert e.value.status == status  # type: ignore[attr-defined]
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (403, "consent_required", PermissionError),
        (403, "plan_user_limit", PlanUserLimitError),
        (404, "platform_user_not_found", NotFoundError),
        (400, "invalid_parameter", BadRequestError),
    ],
)
def test_read_errors(status: int, code: str, cls: type[Exception]) -> None:
    csid, _ = make(lambda r: api_error(status, code))
    with pytest.raises(cls) as e:
        csid.trade_feed("u1")
    assert e.value.code == code  # type: ignore[attr-defined]


# ── webhooks, exports, options ───────────────────────────────────────────────


def test_trade_feed_webhook_events() -> None:
    assert TRADE_FEED_WEBHOOK_EVENTS == ("trade_feed.trade", "trade_feed.thesis")
    assert set(TRADE_FEED_WEBHOOK_EVENTS) <= set(WEBHOOK_EVENTS)


def test_exports() -> None:
    import cabalspy_id

    assert cabalspy_id.__version__ == "0.9.0"
    assert api.TradeFeedStream is cabalspy_id.TradeFeedStream
    assert cabalspy_id.TRADE_FEED_EVENTS == ("trade_feed.trade", "trade_feed.thesis")
    assert "ready" in cabalspy_id.TRADE_FEED_STREAM_EVENTS
    for name in (
        "TradeFeedStream",
        "TradeFeedItem",
        "TradeFeedTradeItem",
        "TradeFeedThesisItem",
        "TradeFeedTrader",
        "TradeFeedTraderResult",
        "TradeFeedRemoveResult",
        "TradeFeedNotification",
        "TradeFeedSettings",
        "TradeFeedEvent",
        "TRADE_FEED_FILTERS",
        "TRADE_FEED_WEBHOOK_EVENTS",
        "MAX_TRADE_FEED_TRADERS",
    ):
        assert name in cabalspy_id.__all__ and name in api.__all__, name
        assert hasattr(api, name), name


def test_client_option() -> None:
    assert CabalSpyID("k", trade_feed_stream_url="ws://x/y/").trade_feed_stream_url == "ws://x/y"
    assert CabalSpyID("k").trade_feed_stream_url == "wss://api-id.cabalspy.xyz/v1/trade-feed/stream"
