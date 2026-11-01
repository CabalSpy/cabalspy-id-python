"""Callouts (an extra per instance) and callout competitions, against mocked HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from cabalspy_id import (
    CALLOUT_COMPETITION_METRICS,
    CALLOUT_SORTS,
    CALLOUT_WEBHOOK_EVENTS,
    COMPETITION_METRICS,
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
from cabalspy_id._errors import is_retryable

from .conftest import Recorder, api_error, ok
from .test_platform_users import call, make, query

KEY = "csid_api_testkey"
SOL = "So11111111111111111111111111111111111111112"

CALLOUT: dict[str, Any] = {
    "id": "c1",
    "chain": "solana",
    "mint": SOL,
    "token": {"name": "Wrapped SOL", "symbol": "SOL", "logo": None},
    "author": {
        "csid_id": "a1",
        "external_id": "u1",
        "name": "Alice",
        "username": None,
        "avatar_url": None,
        "kol": False,
    },
    "note": "gm",
    "called_at": "2026-10-31T12:00:00Z",
    "window_ends_at": "2026-11-01T12:00:00Z",
    "status": "tracking",
    "at_call": {"price_usd": 1.0, "market_cap_usd": 50000.0},
    "now": {"price_usd": 2.0, "market_cap_usd": 100000.0, "x": 2.0, "at": "2026-10-31T13:00:00Z"},
    "peak": {"price_usd": 3.0, "market_cap_usd": 150000.0, "x": 3.0, "at": "2026-10-31T12:30:00Z"},
    "score_x": 3.0,
    "source": "birdeye",
    "tracking": {
        "active": True,
        "phase": "first_day",
        "next_check_at": None,
        "below_10k_since": None,
        "daily_checks": 0,
        "stopped_at": None,
        "stop_reason": None,
    },
}


# ── every endpoint: method, path, query / body ───────────────────────────────


def test_every_callout_endpoint() -> None:
    csid, rec = make()
    csid.create_callout("u1", chain="solana", mint=SOL, note="gm")
    csid.create_callout(csid_id="4b7c", chain="base", mint="0xabc")
    csid.remove_callout("c1", reason="spam")
    csid.remove_callout("c2")
    csid.callouts(
        chain="solana",
        mint=SOL,
        external_id="u1",
        since=datetime(2026, 10, 30, 18, tzinfo=timezone.utc),
        until="2026-10-31T00:00:00Z",
        limit=20,
        cursor="abc",
    )
    csid.callouts()
    csid.callouts(csid_id="4b7c", since=datetime(2026, 10, 30, 20, 0, tzinfo=timezone(timedelta(hours=2))))
    csid.callout("c1")
    csid.callout_stats("u1", hit_x=3)
    csid.callout_stats(csid_id="4b7c")
    csid.callout_leaderboard(period="30d", chain="bnb", sort="hit_rate", min_callouts=3, hit_x=5, limit=10, cursor="x")
    csid.callout_leaderboard()
    csid.callout_settings()
    csid.update_callout_settings(who="kol_only", require_holding=False, cooldown_minutes=0)
    csid.update_callout_settings(cooldown_minutes=60)

    assert [call(r) for r in rec.requests] == [
        ("POST", "/v1/callouts", {"external_id": "u1", "chain": "solana", "mint": SOL, "note": "gm"}),
        ("POST", "/v1/callouts", {"csid_id": "4b7c", "chain": "base", "mint": "0xabc"}),
        ("POST", "/v1/callouts/remove", {"id": "c1", "reason": "spam"}),
        ("POST", "/v1/callouts/remove", {"id": "c2"}),
        (
            "GET",
            "/v1/callouts",
            {
                "chain": "solana",
                "mint": SOL,
                "external_id": "u1",
                "since": "2026-10-30T18:00:00Z",
                "until": "2026-10-31T00:00:00Z",
                "limit": "20",
                "cursor": "abc",
            },
        ),
        ("GET", "/v1/callouts", {}),
        ("GET", "/v1/callouts", {"csid_id": "4b7c", "since": "2026-10-30T18:00:00Z"}),
        ("GET", "/v1/callouts/item", {"id": "c1"}),
        ("GET", "/v1/callouts/stats", {"external_id": "u1", "hit_x": "3"}),
        ("GET", "/v1/callouts/stats", {"csid_id": "4b7c"}),
        (
            "GET",
            "/v1/callouts/leaderboard",
            {
                "period": "30d",
                "chain": "bnb",
                "sort": "hit_rate",
                "min_callouts": "3",
                "hit_x": "5",
                "limit": "10",
                "cursor": "x",
            },
        ),
        ("GET", "/v1/callouts/leaderboard", {}),
        ("GET", "/v1/callouts/settings", {}),
        ("POST", "/v1/callouts/settings", {"who": "kol_only", "require_holding": False, "cooldown_minutes": 0}),
        ("POST", "/v1/callouts/settings", {"cooldown_minutes": 60}),
    ]
    assert all(r.headers["Authorization"] == f"Bearer {KEY}" for r in rec.requests)


def test_naive_datetime_is_utc() -> None:
    csid, rec = make(lambda r: ok([]))
    csid.callouts(since=datetime(2026, 10, 30, 18, 0, 0, 123000))
    assert query(rec.requests[0]) == {"since": "2026-10-30T18:00:00.123000Z"}


def test_returns_the_callout() -> None:
    csid, _ = make(lambda r: httpx.Response(201, json={"success": True, "data": CALLOUT}))
    c = csid.create_callout("u1", chain="solana", mint=SOL)
    assert c["score_x"] == 3.0
    assert c["tracking"]["below_10k_since"] is None
    assert c["at_call"]["market_cap_usd"] == 50000.0


def test_callout_validation() -> None:
    csid, rec = make()
    with pytest.raises(BadRequestError):
        csid.create_callout(chain="solana", mint=SOL)  # no user
    with pytest.raises(BadRequestError):
        csid.create_callout("u1", csid_id="a", chain="solana", mint=SOL)  # both
    with pytest.raises(BadRequestError) as e:
        csid.create_callout("u1", chain="tron", mint=SOL)  # type: ignore[arg-type]
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError) as e:
        csid.create_callout("u1", chain="solana", mint="")
    assert e.value.parameter == "mint"
    with pytest.raises(BadRequestError) as e:
        csid.create_callout("u1", chain="solana", mint=SOL, note="x" * 281)
    assert e.value.parameter == "note"
    with pytest.raises(BadRequestError):
        csid.remove_callout("")
    with pytest.raises(BadRequestError) as e:
        csid.callouts(mint=SOL)
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError):
        csid.callouts(external_id="u1", csid_id="a")
    with pytest.raises(BadRequestError):
        csid.callouts(chain="sol")  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        csid.callout("")
    with pytest.raises(BadRequestError):
        csid.callout_stats()
    for bad in (1, 0.5, 1001, True, "2"):
        with pytest.raises(BadRequestError) as e:
            csid.callout_stats("u1", hit_x=bad)  # type: ignore[arg-type]
        assert e.value.parameter == "hit_x"
    with pytest.raises(BadRequestError) as e:
        csid.callout_leaderboard(period="1y")  # type: ignore[arg-type]
    assert e.value.parameter == "period"
    with pytest.raises(BadRequestError) as e:
        csid.callout_leaderboard(sort="pnl")  # type: ignore[arg-type]
    assert e.value.allowed == list(CALLOUT_SORTS)
    for bad_min in (0, 1001, 2.5):
        with pytest.raises(BadRequestError):
            csid.callout_leaderboard(min_callouts=bad_min)  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        csid.update_callout_settings()
    with pytest.raises(BadRequestError) as e:
        csid.update_callout_settings(who="everyone")  # type: ignore[arg-type]
    assert e.value.allowed == ["all", "kol_only"]
    for bad_cd in (-1, 10081, True):
        with pytest.raises(BadRequestError):
            csid.update_callout_settings(cooldown_minutes=bad_cd)
    assert rec.requests == []


# ── iterators ────────────────────────────────────────────────────────────────


def test_iter_callouts_follows_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        cur = query(r).get("cursor")
        if cur is None:
            return ok([{"id": "c1"}, {"id": "c2"}], pagination={"limit": 2, "has_more": True, "next_cursor": "n1"})
        return ok([{"id": "c3"}], pagination={"limit": 2, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert [c["id"] for c in csid.iter_callouts(chain="solana", limit=2, since=since)] == ["c1", "c2", "c3"]
    assert [query(r) for r in rec.requests] == [
        {"chain": "solana", "since": "2026-10-01T00:00:00Z", "limit": "2"},
        {"chain": "solana", "since": "2026-10-01T00:00:00Z", "limit": "2", "cursor": "n1"},
    ]


def test_iter_callout_leaderboard_follows_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        start = 2 if query(r).get("cursor") else 0
        rows = [{"rank": i + 1, "csid_id": f"a{i}"} for i in range(start, min(start + 2, 3))]
        nxt = "o2" if start == 0 else None
        return ok(
            {"period": "7d", "chain": None, "sort": "avg_peak_x", "hit_x": 2.0, "leaderboard": rows},
            pagination={"limit": 2, "total": 3, "has_more": nxt is not None, "next_cursor": nxt},
        )

    csid, rec = make(handler)
    ranks = [e["rank"] for e in csid.iter_callout_leaderboard(sort="avg_peak_x", min_callouts=2, limit=2)]
    assert ranks == [1, 2, 3]
    assert query(rec.requests[1]) == {"sort": "avg_peak_x", "min_callouts": "2", "limit": "2", "cursor": "o2"}


async def test_async_callouts() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/callouts" and r.method == "GET":
            if query(r).get("cursor"):
                return ok([{"id": "c2"}], pagination={"has_more": False, "next_cursor": None})
            return ok([{"id": "c1"}], pagination={"has_more": True, "next_cursor": "n"})
        if r.url.path == "/v1/callouts/leaderboard":
            return ok({"leaderboard": [{"rank": 1}]}, pagination={"has_more": False, "next_cursor": None})
        if r.url.path == "/v1/callouts/stats":
            return ok({"user": None, "hit_x": 2.0, "periods": {}, "callouts_all_time": 0})
        if r.url.path == "/v1/callouts/settings":
            return ok({"who": "all", "require_holding": True, "cooldown_minutes": 360})
        return httpx.Response(201, json={"success": True, "data": CALLOUT})

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.create_callout("u1", chain="solana", mint=SOL))["id"] == "c1"
        assert (await csid.callout("c1"))["id"] == "c1"
        assert (await csid.remove_callout("c1"))["id"] == "c1"
        assert (await csid.callout_stats("u1"))["callouts_all_time"] == 0
        assert (await csid.callout_settings())["cooldown_minutes"] == 360
        assert (await csid.update_callout_settings(require_holding=True))["who"] == "all"
        assert [c["id"] async for c in csid.iter_callouts()] == ["c1", "c2"]
        assert [e["rank"] async for e in csid.iter_callout_leaderboard(period="1d")] == [1]
        assert (await csid.callouts(chain="eth"))[0]["id"] == "c1"
        assert (await csid.callout_leaderboard())["leaderboard"][0]["rank"] == 1
    assert call(rec.requests[0]) == ("POST", "/v1/callouts", {"external_id": "u1", "chain": "solana", "mint": SOL})


# ── errors ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (403, "feature_not_enabled", PermissionError),
        (403, "kol_only", PermissionError),
        (403, "not_a_holder", PermissionError),
        (403, "invalid_account", PermissionError),
        (403, "posting_paused", PermissionError),
        (403, "consent_required", PermissionError),
        (404, "callout_not_found", NotFoundError),
        (409, "already_called", ConflictError),
        (422, "no_price", BadRequestError),
        (503, "service_unavailable", ServerError),
    ],
)
def test_callout_errors(status: int, code: str, cls: type[Exception]) -> None:
    csid, rec = make(lambda r: api_error(status, code))
    with pytest.raises(cls) as e:
        csid.create_callout("u1", chain="solana", mint=SOL)
    assert e.value.code == code  # type: ignore[attr-defined]
    assert e.value.status == status  # type: ignore[attr-defined]
    assert len(rec.requests) == 1  # writes are not retried after a 5xx


def test_callout_cooldown_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("cabalspy_id._client.time.sleep", sleeps.append)
    csid, rec = make(
        lambda r: api_error(429, "callout_cooldown", headers={"Retry-After": "7200"}, retry_after=7200),
        max_retries=3,
    )
    with pytest.raises(RateLimitError) as e:
        csid.create_callout("u1", chain="solana", mint=SOL)
    assert e.value.code == "callout_cooldown"
    assert e.value.retry_after == 7200
    assert len(rec.requests) == 1
    assert sleeps == []
    assert not is_retryable(e.value)


def test_retry_after_from_the_body_when_no_header() -> None:
    csid, _ = make(lambda r: api_error(429, "callout_cooldown", retry_after=90))
    with pytest.raises(RateLimitError) as e:
        csid.create_callout("u1", chain="solana", mint=SOL)
    assert e.value.retry_after == 90.0


def test_callout_cooldown_on_get_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cabalspy_id._client.time.sleep", lambda s: None)
    csid, rec = make(lambda r: api_error(429, "callout_cooldown", headers={"Retry-After": "60"}), max_retries=3)
    with pytest.raises(RateLimitError):
        csid.get_raw("/callouts")
    assert len(rec.requests) == 1
    # the API's own rate limit still is
    csid, rec = make(lambda r: api_error(429, "rate_limit_exceeded", headers={"Retry-After": "0"}), max_retries=2)
    with pytest.raises(RateLimitError):
        csid.callouts()
    assert len(rec.requests) == 3


# ── /v1/me features, webhooks, exports ───────────────────────────────────────


def test_me_features() -> None:
    csid, _ = make(lambda r: ok({"instance": "app.example.com", "features": ["callouts"]}))
    me = csid.me()
    assert "callouts" in me["features"]


def test_callout_webhook_events() -> None:
    assert CALLOUT_WEBHOOK_EVENTS == ("callout.created", "callout.milestone", "callout.scored", "callout.final")
    assert set(CALLOUT_WEBHOOK_EVENTS) <= set(WEBHOOK_EVENTS)


def test_exports() -> None:
    import cabalspy_id

    assert api.CalloutsStream is cabalspy_id.CalloutsStream
    assert "callout.update" in cabalspy_id.CALLOUT_EVENTS
    assert "ready" in cabalspy_id.CALLOUTS_STREAM_EVENTS
    for name in ("Callout", "CalloutStats", "CalloutLeaderboardEntry", "CalloutSettings", "CALLOUT_SORTS"):
        assert name in cabalspy_id.__all__ and name in api.__all__


# ── callout competitions ─────────────────────────────────────────────────────


def test_callout_competition_create_and_update() -> None:
    csid, rec = make()
    csid.create_competition(
        name="Best caller",
        kind="callouts",
        chain="all",
        metric="avg_peak_x",
        duration_hours=168,
        min_callouts=3,
        hit_x=5,
        enrollment="all_users",
    )
    csid.create_competition(name="Solana calls", kind="callouts", chain="solana", metric="hit_rate", duration_hours=24)
    csid.create_competition(name="Trading", kind="trading", chain="base", metric="pnl_usd", duration_hours=24)
    csid.update_competition("c1", min_callouts=5, hit_x=3.5, chain="all", metric="best_peak_x", note="tighter")
    csid.update_competition("c2", metric="pnl")
    assert [call(r) for r in rec.requests] == [
        (
            "POST",
            "/v1/competitions",
            {
                "name": "Best caller",
                "kind": "callouts",
                "chain": "all",
                "metric": "avg_peak_x",
                "duration_hours": 168,
                "min_callouts": 3,
                "hit_x": 5,
                "enrollment": "all_users",
            },
        ),
        (
            "POST",
            "/v1/competitions",
            {"name": "Solana calls", "kind": "callouts", "chain": "solana", "metric": "hit_rate", "duration_hours": 24},
        ),
        (
            "POST",
            "/v1/competitions",
            {"name": "Trading", "kind": "trading", "chain": "base", "metric": "pnl_usd", "duration_hours": 24},
        ),
        (
            "POST",
            "/v1/competitions/update",
            {"id": "c1", "chain": "all", "metric": "best_peak_x", "min_callouts": 5, "hit_x": 3.5, "note": "tighter"},
        ),
        ("POST", "/v1/competitions/update", {"id": "c2", "metric": "pnl"}),
    ]


def test_callout_competition_validation() -> None:
    csid, rec = make()
    # trading (the default kind): no chain "all", no callout metrics or minimums
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", chain="all", metric="pnl", duration_hours=1)
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", chain="solana", metric="avg_peak_x", duration_hours=1)
    assert e.value.allowed == list(COMPETITION_METRICS)
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", chain="solana", metric="pnl", duration_hours=1, min_callouts=2)
    assert e.value.parameter == "min_callouts"
    # callouts: no trading metrics or minimums
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", kind="callouts", chain="all", metric="pnl", duration_hours=1)
    assert e.value.allowed == list(CALLOUT_COMPETITION_METRICS)
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(
            name="x", kind="callouts", chain="all", metric="callouts", duration_hours=1, min_trades=1
        )
    assert e.value.parameter == "min_trades"
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", kind="callouts", chain="all", metric="callouts", duration_hours=1, hit_x=1)
    assert e.value.parameter == "hit_x"
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", kind="league", chain="all", metric="callouts", duration_hours=1)  # type: ignore[arg-type]
    assert e.value.parameter == "kind"
    # update: the kind is the server's; only the value ranges are checked here
    with pytest.raises(BadRequestError):
        csid.update_competition("c1", hit_x=2000)
    with pytest.raises(BadRequestError):
        csid.update_competition("c1", metric="best")  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        csid.update_competition("c1", chain="tron")  # type: ignore[arg-type]
    assert rec.requests == []


def test_callout_competition_feature_not_enabled() -> None:
    csid, _ = make(lambda r: api_error(403, "feature_not_enabled"))
    with pytest.raises(PermissionError) as e:
        csid.create_competition(name="x", kind="callouts", chain="all", metric="callouts", duration_hours=1)
    assert e.value.code == "feature_not_enabled"


def test_callout_standings_iterate() -> None:
    row = {
        "rank": 1,
        "ranked": True,
        "csid_id": "a1",
        "score": 4.5,
        "callouts": 3,
        "avg_peak_x": 4.5,
        "best_call": {"id": "c1", "chain": "solana", "mint": SOL, "symbol": "SOL", "peak_x": 9.0},
    }
    csid, _ = make(lambda r: ok({"standings": [row]}, pagination={"limit": 100, "total": 1}))
    rows = list(csid.iter_competition_standings("comp"))
    assert rows[0]["best_call"]["peak_x"] == 9.0


async def test_async_callout_competition() -> None:
    rec = Recorder(lambda r: ok({"id": "comp", "kind": "callouts"}))
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        comp = await csid.create_competition(
            name="n", kind="callouts", chain="all", metric="sum_peak_x", duration_hours=2
        )
        assert comp["kind"] == "callouts"
    assert call(rec.requests[0])[2]["kind"] == "callouts"


def test_client_option() -> None:
    assert CabalSpyID("k", callouts_stream_url="ws://x/y/").callouts_stream_url == "ws://x/y"
