from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from cabalspy_id import (
    COMPETITION_WEBHOOK_EVENTS,
    AsyncCabalSpyID,
    BadRequestError,
    ConflictError,
)

from .conftest import Recorder, api_error, ok
from .test_platform_users import call, make, query

KEY = "csid_api_testkey"


def test_every_competition_endpoint() -> None:
    csid, rec = make()
    csid.create_competition(
        name="Weekly PnL",
        chain="solana",
        metric="pnl_usd",
        duration_hours=168,
        starts_at=datetime(2026, 11, 1, 18, tzinfo=timezone.utc),
        min_participants=2,
        min_volume_usd=100.0,
        enrollment="all_users",
        prizes=[{"rank": 1, "prize": "100 USDC"}],
    )
    csid.create_competition(name="Quick", chain="base", metric="trades", duration_hours=1)
    csid.competitions(status="running", limit=10, offset=20)
    csid.competition("c1")
    csid.update_competition("c1", duration_hours=48, max_participants=None, note="longer")
    csid.update_competition("c1", description=None)
    csid.cancel_competition("c1")
    csid.join_competition("c1", "u1")
    csid.join_competition("c1", csid_id="4b7c")
    csid.leave_competition("c1", "u1")
    csid.competition_participants("c1", limit=100, offset=100)
    csid.competition_standings("c1", limit=5)

    assert [call(r) for r in rec.requests] == [
        (
            "POST",
            "/v1/competitions",
            {
                "name": "Weekly PnL",
                "chain": "solana",
                "metric": "pnl_usd",
                "duration_hours": 168,
                "starts_at": "2026-11-01T18:00:00+00:00",
                "min_participants": 2,
                "min_volume_usd": 100.0,
                "enrollment": "all_users",
                "prizes": [{"rank": 1, "prize": "100 USDC"}],
            },
        ),
        ("POST", "/v1/competitions", {"name": "Quick", "chain": "base", "metric": "trades", "duration_hours": 1}),
        ("GET", "/v1/competitions", {"status": "running", "limit": "10", "offset": "20"}),
        ("GET", "/v1/competitions/detail", {"id": "c1"}),
        (
            "POST",
            "/v1/competitions/update",
            {"id": "c1", "duration_hours": 48, "max_participants": None, "note": "longer"},
        ),
        ("POST", "/v1/competitions/update", {"id": "c1", "description": None}),
        ("POST", "/v1/competitions/cancel", {"id": "c1"}),
        ("POST", "/v1/competitions/join", {"id": "c1", "external_id": "u1"}),
        ("POST", "/v1/competitions/join", {"id": "c1", "csid_id": "4b7c"}),
        ("POST", "/v1/competitions/leave", {"id": "c1", "external_id": "u1"}),
        ("GET", "/v1/competitions/participants", {"id": "c1", "limit": "100", "offset": "100"}),
        ("GET", "/v1/competitions/standings", {"id": "c1", "limit": "5"}),
    ]


def test_competition_validation() -> None:
    csid, rec = make()
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", chain="solana", metric="best", duration_hours=1)  # type: ignore[arg-type]
    assert e.value.parameter == "metric"
    with pytest.raises(BadRequestError) as e:
        csid.create_competition(name="x", chain="tron", metric="pnl", duration_hours=1)  # type: ignore[arg-type]
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError):
        csid.create_competition(name="", chain="solana", metric="pnl", duration_hours=1)
    with pytest.raises(BadRequestError) as e:
        csid.update_competition("c1", enrollment="everyone")  # type: ignore[arg-type]
    assert e.value.allowed == ["opt_in", "all_users"]
    with pytest.raises(BadRequestError):
        csid.update_competition("c1")
    with pytest.raises(BadRequestError):
        csid.update_competition("c1", note="only a note")
    with pytest.raises(BadRequestError) as e:
        csid.competitions(status="live")  # type: ignore[arg-type]
    assert e.value.parameter == "status"
    with pytest.raises(BadRequestError):
        csid.join_competition("c1")
    with pytest.raises(BadRequestError):
        csid.competition("")
    assert rec.requests == []


@pytest.mark.parametrize("code", ["competition_limit", "competition_closed", "competition_full", "late_join_closed"])
def test_competition_conflicts(code: str) -> None:
    csid, _ = make(lambda r: api_error(409, code))
    with pytest.raises(ConflictError) as e:
        csid.join_competition("c1", "u1")
    assert e.value.code == code


def test_iter_competition_standings_follows_offset() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        offset = int(query(r).get("offset", 0))
        rows = [{"rank": i + 1, "external_id": f"u{i}"} for i in range(offset, min(offset + 2, 5))]
        # the server's has_more is always false on offset routes; the total decides
        return ok(
            {"competition_id": "c1", "standings": rows},
            pagination={"limit": 2, "total": 5, "has_more": False, "next_cursor": None},
        )

    csid, rec = make(handler)
    assert [s["external_id"] for s in csid.iter_competition_standings("c1", limit=2)] == [f"u{i}" for i in range(5)]
    assert [query(r) for r in rec.requests] == [
        {"id": "c1", "limit": "2"},
        {"id": "c1", "limit": "2", "offset": "2"},
        {"id": "c1", "limit": "2", "offset": "4"},
    ]


def test_iter_competitions_and_participants() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        offset = int(query(r).get("offset", 0))
        rows = [{"id": f"c{i}", "csid_id": f"a{i}"} for i in range(offset, min(offset + 2, 3))]
        return ok(rows, pagination={"limit": 2, "total": 3, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    assert [c["id"] for c in csid.iter_competitions(status="ended", limit=2)] == ["c0", "c1", "c2"]
    assert query(rec.requests[0]) == {"status": "ended", "limit": "2"}
    assert [p["csid_id"] for p in csid.iter_competition_participants("c1", limit=2)] == ["a0", "a1", "a2"]
    assert rec.requests[-1].url.path == "/v1/competitions/participants"


def test_iter_stops_on_empty_page() -> None:
    csid, rec = make(lambda r: ok([], pagination={"limit": 50, "total": 10, "has_more": False}))
    assert list(csid.iter_competitions()) == []
    assert len(rec.requests) == 1


def test_competition_webhook_events() -> None:
    assert COMPETITION_WEBHOOK_EVENTS == (
        "competition.started",
        "competition.updated",
        "competition.standings",
        "competition.ended",
    )


async def test_async_competitions() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/competitions/standings":
            offset = int(query(r).get("offset", 0))
            return ok({"standings": [{"rank": offset + 1}]}, pagination={"limit": 1, "total": 2})
        if r.url.path == "/v1/competitions" and r.method == "GET":
            return ok([{"id": "c1"}], pagination={"limit": 50, "total": 1})
        if r.url.path == "/v1/competitions/participants":
            return ok([{"csid_id": "a"}], pagination={"limit": 100, "total": 1})
        return ok({"id": "c1", "joined": True, "already": False})

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.join_competition("c1", "u1"))["joined"] is True
        assert (await csid.create_competition(name="n", chain="eth", metric="volume", duration_hours=2))["id"] == "c1"
        assert [s["rank"] async for s in csid.iter_competition_standings("c1", limit=1)] == [1, 2]
        assert [c["id"] async for c in csid.iter_competitions()] == ["c1"]
        assert [p["csid_id"] async for p in csid.iter_competition_participants("c1")] == ["a"]
    assert call(rec.requests[0]) == ("POST", "/v1/competitions/join", {"id": "c1", "external_id": "u1"})
