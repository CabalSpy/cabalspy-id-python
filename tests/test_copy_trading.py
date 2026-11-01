"""Copy trading (settings per user and trader, instructions, status reports), against mocked HTTP."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from cabalspy_id import (
    COPY_INSTRUCTION_STATUSES,
    COPY_REPORT_STATUSES,
    COPY_TRADING_WEBHOOK_EVENTS,
    WEBHOOK_EVENTS,
    AsyncCabalSpyID,
    BadRequestError,
    CabalSpyID,
    ConflictError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ServerError,
    api,
)

from .conftest import Recorder, api_error, ok
from .test_platform_users import call, make, query

KEY = "csid_api_testkey"
MINT = "So11111111111111111111111111111111111111112"
TX = "5" * 88

TRADER: dict[str, Any] = {
    "csid_id": "t1",
    "username": "ctkol",
    "name": "Ctkol",
    "image_url": None,
    "kol": True,
    "profile_url": "https://id.cabalspy.xyz/u/ctkol",
}
COPY: dict[str, Any] = {
    "enabled": True,
    "mode": "fixed_usd",
    "amount_usd": 25.0,
    "percent": 100.0,
    "max_usd": 20.0,
    "sides": "both",
    "slippage_bps": 300,
    "updated_at": "2026-11-01T12:00:00Z",
}
SETTING: dict[str, Any] = {"trader": TRADER, "copy": COPY, "managed_by_other_platform": False}
INSTRUCTION: dict[str, Any] = {
    "id": "9f0b1c2d-0000-4000-8000-000000000001",
    "type": "copy_instruction",
    "status": "pending",
    "created_at": "2026-11-01T12:00:00Z",
    "expires_at": "2026-11-01T12:02:00Z",
    "csid_id": "f1",
    "trader": TRADER,
    "action": {
        "blockchain": "solana",
        "mint": MINT,
        "symbol": "CPT",
        "name": None,
        "logo": None,
        "side": "buy",
        "amount_usd": 20.0,
        "amount_native": 0.133333333,
        "currency": "SOL",
        "sell_percent": None,
        "price_usd": 0.15,
        "max_price_usd": 0.1545,
        "min_price_usd": None,
        "slippage_bps": 300,
    },
    "source_trade": {"blockchain": "solana", "mint": MINT, "side": "buy", "label": "new", "amount_usd": 150.0},
    "settings": COPY,
    "links": {"token": None, "terminal": None, "profile": None},
    "tx_signature": None,
    "executed_amount_usd": None,
    "note": None,
    "updated_at": "2026-11-01T12:00:00Z",
}


# ── every endpoint: method, path, query / body ───────────────────────────────


def test_every_copy_trading_endpoint() -> None:
    csid, rec = make()
    csid.copy_trading_settings("u1")
    csid.copy_trading_settings(csid_id="f1", trader="ctkol")
    csid.copy_trading_settings("u1", trader_external_id="u2")
    csid.update_copy_trading_settings(
        "u1",
        trader="ctkol",
        enabled=True,
        mode="fixed_usd",
        amount_usd=25,
        max_usd=20,
        sides="buys",
        slippage_bps=150,
    )
    csid.update_copy_trading_settings(csid_id="f1", trader_external_id="u2", mode="percent", percent=10, max_usd=None)
    csid.update_copy_trading_settings("u1", trader="t1", enabled=False)
    csid.copy_instructions()
    csid.copy_instructions("u1", status="expired", limit=2, cursor="abc")
    csid.copy_instructions(csid_id="f1", status="executed")
    csid.copy_instruction("i1")
    csid.report_copy_instruction("i1", status="executed", tx_signature=TX, executed_amount_usd=19.8)
    csid.report_copy_instruction("i2", status="failed", note="insufficient balance")
    csid.report_copy_instruction("i3", status="skipped")

    assert [call(r) for r in rec.requests] == [
        ("GET", "/v1/copy-trading/settings", {"external_id": "u1"}),
        ("GET", "/v1/copy-trading/settings", {"csid_id": "f1", "trader": "ctkol"}),
        ("GET", "/v1/copy-trading/settings", {"external_id": "u1", "trader_external_id": "u2"}),
        (
            "POST",
            "/v1/copy-trading/settings",
            {
                "external_id": "u1",
                "trader": "ctkol",
                "enabled": True,
                "mode": "fixed_usd",
                "amount_usd": 25,
                "max_usd": 20,
                "sides": "buys",
                "slippage_bps": 150,
            },
        ),
        (
            "POST",
            "/v1/copy-trading/settings",
            {"csid_id": "f1", "trader_external_id": "u2", "mode": "percent", "percent": 10, "max_usd": None},
        ),
        ("POST", "/v1/copy-trading/settings", {"external_id": "u1", "trader": "t1", "enabled": False}),
        ("GET", "/v1/copy-trading/instructions", {}),
        (
            "GET",
            "/v1/copy-trading/instructions",
            {"external_id": "u1", "status": "expired", "limit": "2", "cursor": "abc"},
        ),
        ("GET", "/v1/copy-trading/instructions", {"csid_id": "f1", "status": "executed"}),
        ("GET", "/v1/copy-trading/instructions/item", {"id": "i1"}),
        (
            "POST",
            "/v1/copy-trading/instructions/status",
            {"id": "i1", "status": "executed", "tx_signature": TX, "executed_amount_usd": 19.8},
        ),
        (
            "POST",
            "/v1/copy-trading/instructions/status",
            {"id": "i2", "status": "failed", "note": "insufficient balance"},
        ),
        ("POST", "/v1/copy-trading/instructions/status", {"id": "i3", "status": "skipped"}),
    ]
    assert all(r.headers["Authorization"] == f"Bearer {KEY}" for r in rec.requests)


def test_returns_settings_and_instruction() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/copy-trading/settings":
            if r.method == "POST":
                return httpx.Response(201, json={"success": True, "data": SETTING})
            return ok(SETTING if query(r).get("trader") else [SETTING])
        if r.url.path == "/v1/copy-trading/instructions":
            return ok([INSTRUCTION], pagination={"limit": 50, "next_cursor": None, "has_more": False})
        return ok({**INSTRUCTION, "status": "executed", "tx_signature": TX, "executed_amount_usd": 19.8})

    csid, _ = make(handler)
    s = csid.update_copy_trading_settings("u1", trader="ctkol", enabled=True)
    assert s["copy"]["max_usd"] == 20.0 and s["trader"]["username"] == "ctkol"
    assert not s["managed_by_other_platform"]
    assert csid.copy_trading_settings("u1")[0]["copy"]["enabled"] is True
    assert csid.copy_trading_settings("u1", trader="ctkol")["copy"]["slippage_bps"] == 300
    i = csid.copy_instructions("u1")[0]
    assert i["type"] == "copy_instruction" and i["action"]["side"] == "buy" and i["action"]["max_price_usd"] == 0.1545
    done = csid.report_copy_instruction(i["id"], status="executed", tx_signature=TX, executed_amount_usd=19.8)
    assert done["status"] == "executed" and done["executed_amount_usd"] == 19.8


def test_copy_trading_validation() -> None:
    csid, rec = make()
    with pytest.raises(BadRequestError):
        csid.copy_trading_settings()  # no user
    with pytest.raises(BadRequestError):
        csid.copy_trading_settings("u1", csid_id="f1")  # both
    with pytest.raises(BadRequestError) as e:
        csid.copy_trading_settings("u1", trader="a", trader_external_id="b")
    assert e.value.parameter == "trader|trader_external_id"
    with pytest.raises(BadRequestError) as e:
        csid.update_copy_trading_settings("u1", enabled=True)  # no trader
    assert e.value.parameter == "trader"
    with pytest.raises(BadRequestError) as e:
        csid.update_copy_trading_settings("u1", trader="ctkol")  # no setting
    assert e.value.code == "missing_parameter"
    with pytest.raises(BadRequestError) as e:
        csid.update_copy_trading_settings("u1", trader="ctkol", mode="all_in")  # type: ignore[arg-type]
    assert e.value.allowed == ["fixed_usd", "percent"]
    with pytest.raises(BadRequestError) as e:
        csid.update_copy_trading_settings("u1", trader="ctkol", sides="sells")  # type: ignore[arg-type]
    assert e.value.allowed == ["buys", "both"]
    with pytest.raises(BadRequestError) as e:
        csid.update_copy_trading_settings("u1", trader="ctkol", enabled="yes")  # type: ignore[arg-type]
    assert e.value.parameter == "enabled"
    bad: list[tuple[str, Any]] = [
        ("amount_usd", 0),
        ("amount_usd", 1_000_001),
        ("amount_usd", "abc"),
        ("amount_usd", float("inf")),
        ("percent", 2000),
        ("percent", -1),
        ("max_usd", 0),
        ("max_usd", True),
        ("slippage_bps", 0),
        ("slippage_bps", 5001),
        ("slippage_bps", 2.5),
    ]
    for name, value in bad:
        with pytest.raises(BadRequestError) as e:
            csid.update_copy_trading_settings("u1", trader="ctkol", **{name: value})
        assert e.value.parameter == name, (name, value)
    with pytest.raises(BadRequestError):
        csid.copy_instructions("u1", csid_id="f1")
    with pytest.raises(BadRequestError) as e:
        csid.copy_instructions(status="bogus")  # type: ignore[arg-type]
    assert e.value.allowed == list(COPY_INSTRUCTION_STATUSES)
    for bad_limit in (0, 101, True):
        with pytest.raises(BadRequestError):
            csid.copy_instructions(limit=bad_limit)
    with pytest.raises(BadRequestError):
        csid.copy_instruction("")
    with pytest.raises(BadRequestError):
        csid.report_copy_instruction("", status="executed")
    with pytest.raises(BadRequestError) as e:
        csid.report_copy_instruction("i1", status="done")  # type: ignore[arg-type]
    assert e.value.allowed == list(COPY_REPORT_STATUSES)
    with pytest.raises(BadRequestError) as e:
        csid.report_copy_instruction("i1", status="pending")  # type: ignore[arg-type]
    assert e.value.parameter == "status"
    with pytest.raises(BadRequestError) as e:
        csid.report_copy_instruction("i1", status="executed", tx_signature="short")
    assert e.value.parameter == "tx_signature"
    with pytest.raises(BadRequestError) as e:
        csid.report_copy_instruction("i1", status="executed", executed_amount_usd=0)
    assert e.value.parameter == "executed_amount_usd"
    assert rec.requests == []


def test_none_leaves_settings_unchanged() -> None:
    csid, rec = make()
    csid.update_copy_trading_settings("u1", trader="ctkol", enabled=None, amount_usd=None, sides="both")
    assert call(rec.requests[0])[2] == {"external_id": "u1", "trader": "ctkol", "sides": "both"}


# ── iterators, async ─────────────────────────────────────────────────────────


def test_iter_copy_instructions_follows_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if query(r).get("cursor") is None:
            return ok([{"id": "i1"}, {"id": "i2"}], pagination={"limit": 2, "has_more": True, "next_cursor": "n1"})
        return ok([{"id": "i3"}], pagination={"limit": 2, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    assert [i["id"] for i in csid.iter_copy_instructions("u1", status="pending", limit=2)] == ["i1", "i2", "i3"]
    assert [query(r) for r in rec.requests] == [
        {"external_id": "u1", "status": "pending", "limit": "2"},
        {"external_id": "u1", "status": "pending", "limit": "2", "cursor": "n1"},
    ]


async def test_async_copy_trading() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/copy-trading/settings":
            return ok(SETTING if r.method == "POST" or query(r).get("trader") else [SETTING])
        if r.url.path == "/v1/copy-trading/instructions":
            if query(r).get("cursor"):
                return ok([{"id": "i2"}], pagination={"has_more": False, "next_cursor": None})
            return ok([{"id": "i1"}], pagination={"has_more": True, "next_cursor": "n"})
        return ok(INSTRUCTION)

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.copy_trading_settings("u1"))[0]["trader"]["csid_id"] == "t1"
        assert (await csid.copy_trading_settings("u1", trader="t1"))["copy"]["mode"] == "fixed_usd"
        s = await csid.update_copy_trading_settings("u1", trader="t1", amount_usd=5)
        assert s["copy"]["enabled"]
        assert (await csid.copy_instructions())[0]["id"] == "i1"
        assert [i["id"] async for i in csid.iter_copy_instructions(csid_id="f1")] == ["i1", "i2"]
        assert (await csid.copy_instruction("i1"))["status"] == "pending"
        assert (await csid.report_copy_instruction("i1", status="skipped"))["id"] == INSTRUCTION["id"]
    assert call(rec.requests[2]) == (
        "POST",
        "/v1/copy-trading/settings",
        {"external_id": "u1", "trader": "t1", "amount_usd": 5},
    )


# ── errors ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (403, "consent_required", PermissionError),
        (403, "trading_private", PermissionError),
        (404, "trader_not_found", NotFoundError),
        (409, "copy_managed_elsewhere", ConflictError),
        (409, "trade_feed_full", ConflictError),
    ],
)
def test_settings_errors(status: int, code: str, cls: type[Exception]) -> None:
    csid, rec = make(lambda r: api_error(status, code))
    with pytest.raises(cls) as e:
        csid.update_copy_trading_settings("u1", trader="ctkol", enabled=True)
    assert e.value.code == code  # type: ignore[attr-defined]
    assert e.value.status == status  # type: ignore[attr-defined]
    assert len(rec.requests) == 1


def test_not_in_trade_feed() -> None:
    csid, _ = make(lambda r: api_error(404, "not_in_trade_feed"))
    with pytest.raises(NotFoundError) as e:
        csid.copy_trading_settings("u1", trader="someone")
    assert e.value.code == "not_in_trade_feed"


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (409, "already_reported", ConflictError),
        (404, "not_found", NotFoundError),
        (400, "invalid_parameter", BadRequestError),
    ],
)
def test_report_errors(status: int, code: str, cls: type[Exception]) -> None:
    csid, rec = make(lambda r: api_error(status, code))
    with pytest.raises(cls) as e:
        csid.report_copy_instruction("i1", status="failed")
    assert e.value.code == code  # type: ignore[attr-defined]
    assert len(rec.requests) == 1


def test_report_is_not_retried_after_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cabalspy_id._client.time.sleep", lambda s: None)
    csid, rec = make(lambda r: api_error(503, "service_unavailable"), max_retries=3)
    with pytest.raises(ServerError):
        csid.report_copy_instruction("i1", status="executed")
    assert len(rec.requests) == 1
    # the trade feed's own rate limit on settings is not retried either (only rate_limit_exceeded is)
    csid, rec = make(lambda r: api_error(429, "rate_limited", headers={"Retry-After": "0"}), max_retries=2)
    with pytest.raises(RateLimitError):
        csid.update_copy_trading_settings("u1", trader="ctkol", enabled=True)
    assert len(rec.requests) == 1


# ── webhooks, exports, options ───────────────────────────────────────────────


def test_copy_trading_webhook_events() -> None:
    assert COPY_TRADING_WEBHOOK_EVENTS == ("copy_trade.instruction",)
    assert set(COPY_TRADING_WEBHOOK_EVENTS) <= set(WEBHOOK_EVENTS)


def test_exports() -> None:
    import cabalspy_id

    assert api.CopyTradingStream is cabalspy_id.CopyTradingStream
    assert cabalspy_id.COPY_TRADING_EVENTS == ("copy_trade.instruction",)
    assert "ready" in cabalspy_id.COPY_TRADING_STREAM_EVENTS
    for name in (
        "CopyInstruction",
        "CopyTradingSetting",
        "CopySettings",
        "CopyAction",
        "CopyTrader",
        "COPY_MODES",
        "COPY_TRADING_WEBHOOK_EVENTS",
        "CopyTradingStream",
    ):
        assert name in cabalspy_id.__all__ and name in api.__all__


def test_client_option() -> None:
    assert CabalSpyID("k", copy_trading_stream_url="ws://x/y/").copy_trading_stream_url == "ws://x/y"
    assert CabalSpyID("k").copy_trading_stream_url == "wss://api-id.cabalspy.xyz/v1/copy-trading/stream"
