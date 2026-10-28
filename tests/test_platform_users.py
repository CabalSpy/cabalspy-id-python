from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from cabalspy_id import (
    PLATFORM_WEBHOOK_EVENTS,
    WEBHOOK_EVENTS,
    AsyncCabalSpyID,
    BadRequestError,
    CabalSpyID,
    ConflictError,
    NotFoundError,
    PermissionError,
    PlanUserLimitError,
    PlatformImportError,
    RateLimitError,
    ServerError,
)

from .conftest import Recorder, api_error, ok

KEY = "csid_api_testkey"
SOL = "So11111111111111111111111111111111111111112"
EVM = "0x52908400098527886E0F7030069857D2E4169EE7"


def make(handler: Any = None, **kwargs: Any) -> tuple[CabalSpyID, Recorder]:
    rec = Recorder(handler or (lambda r: ok({})))
    kwargs.setdefault("max_retries", 0)
    return CabalSpyID(KEY, http_client=rec.client(), **kwargs), rec


def query(req: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}


def body(req: httpx.Request) -> Any:
    return json.loads(req.content)


def call(req: httpx.Request) -> tuple[str, str, Any]:
    """(method, path, query or JSON body) of a recorded request."""
    if req.method == "GET":
        return req.method, req.url.path, query(req)
    return req.method, req.url.path, body(req)


# ── every endpoint: method, path, query / body ───────────────────────────────


def test_every_platform_user_endpoint() -> None:
    csid, rec = make()
    csid.upsert_platform_user("u1", wallets=[SOL, {"address": EVM, "chains": ["base"], "source": "privy"}])
    csid.upsert_platform_user("u1", display_name=None, avatar_url="https://cdn.example.com/a.png")
    csid.import_platform_users([{"external_id": "u2", "wallets": [SOL]}])
    csid.platform_user("u1")
    csid.platform_user(csid_id="4b7c")
    csid.update_platform_user("u1", display_name="Alice")
    csid.platform_users(limit=10, cursor="c1")
    csid.delete_platform_user("u1")
    csid.add_platform_user_wallets("u1", wallets=[EVM])
    csid.delete_platform_user_wallet("u1", address=EVM)
    csid.start_wallet_verification("u1", chain="solana", address=SOL)
    csid.wallet_verification("v1")
    csid.cancel_wallet_verification("v1")
    csid.platform_user_profile("u1", period="30d")
    csid.platform_leaderboard(blockchain="solana", period="1d", sort="volume", limit=5, cursor="w", trust="verified")
    csid.platform_settings()
    csid.update_platform_settings(white_label=True, data_scope="platform", wallet_trust="verified_only")
    csid.platform_inbound()
    csid.enable_platform_inbound()
    csid.disable_platform_inbound()
    csid.platform_user_session("u1")
    csid.platform_user_claim_link("u1", return_url="https://app.example.com/done")
    csid.platform_user_claim_link(csid_id="4b7c")
    csid.connect_platform_user_x("u1", return_url="https://app.example.com/x")
    csid.disconnect_platform_user_x("u1")
    csid.link_platform_user_telegram("u1")
    csid.platform_user_telegram("u1")
    csid.unlink_platform_user_telegram("u1")
    csid.platform_user_kol("u1")
    csid.request_platform_user_volume_check("u1")
    csid.apply_platform_user_kol("u1")

    P = "/v1/platform-users"
    assert [call(r) for r in rec.requests] == [
        (
            "POST",
            P,
            {
                "external_id": "u1",
                "wallets": [SOL, {"address": EVM, "chains": ["base"], "source": "privy"}],
            },
        ),
        ("POST", P, {"external_id": "u1", "display_name": None, "avatar_url": "https://cdn.example.com/a.png"}),
        ("POST", P + "/import", {"users": [{"external_id": "u2", "wallets": [SOL]}]}),
        ("GET", P, {"external_id": "u1"}),
        ("GET", P, {"csid_id": "4b7c"}),
        ("POST", P + "/update", {"external_id": "u1", "display_name": "Alice"}),
        ("GET", P + "/list", {"limit": "10", "cursor": "c1"}),
        ("POST", P + "/delete", {"external_id": "u1"}),
        ("POST", P + "/wallets/add", {"external_id": "u1", "wallets": [EVM]}),
        ("POST", P + "/wallets/delete", {"external_id": "u1", "address": EVM}),
        ("POST", P + "/wallets/verify", {"external_id": "u1", "chain": "solana", "address": SOL}),
        ("GET", P + "/wallets/verification", {"id": "v1"}),
        ("POST", P + "/wallets/verification/cancel", {"id": "v1"}),
        ("GET", P + "/profile", {"external_id": "u1", "period": "30d"}),
        (
            "GET",
            P + "/leaderboard",
            {
                "blockchain": "solana",
                "period": "1d",
                "sort": "volume",
                "trust": "verified",
                "limit": "5",
                "cursor": "w",
            },
        ),
        ("GET", P + "/settings", {}),
        ("POST", P + "/settings", {"white_label": True, "data_scope": "platform", "wallet_trust": "verified_only"}),
        ("GET", P + "/inbound", {}),
        ("POST", P + "/inbound/enable", {}),
        ("POST", P + "/inbound/disable", {}),
        ("POST", P + "/session", {"external_id": "u1"}),
        ("POST", P + "/claim-link", {"external_id": "u1", "return_url": "https://app.example.com/done"}),
        ("POST", P + "/claim-link", {"csid_id": "4b7c"}),
        ("POST", P + "/x/connect", {"external_id": "u1", "return_url": "https://app.example.com/x"}),
        ("POST", P + "/x/disconnect", {"external_id": "u1"}),
        ("POST", P + "/telegram/link", {"external_id": "u1"}),
        ("GET", P + "/telegram", {"external_id": "u1"}),
        ("POST", P + "/telegram/unlink", {"external_id": "u1"}),
        ("GET", P + "/kol", {"external_id": "u1"}),
        ("POST", P + "/kol/volume-check", {"external_id": "u1"}),
        ("POST", P + "/kol/apply", {"external_id": "u1"}),
    ]
    assert all(r.headers["authorization"] == f"Bearer {KEY}" for r in rec.requests)
    assert all(r.headers["content-type"] == "application/json" for r in rec.requests if r.method == "POST")


def test_instance_is_added_to_posts() -> None:
    csid, rec = make(instance="csid_abc")
    csid.delete_platform_user("u1")
    assert query(rec.requests[0]) == {"instance": "csid_abc"}


def test_verification_qr_returns_svg() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    csid, rec = make(
        lambda r: httpx.Response(200, text=svg, headers={"content-type": "image/svg+xml", "X-RateLimit-Limit": "5"})
    )
    assert csid.wallet_verification_qr("v1") == svg
    assert rec.requests[0].url.path == "/v1/platform-users/wallets/verification/qr"
    assert query(rec.requests[0]) == {"id": "v1"}
    assert csid.last_rate_limit.limit == 5


def test_verification_qr_error() -> None:
    csid, _ = make(lambda r: api_error(404, "verification_not_found"))
    with pytest.raises(NotFoundError) as e:
        csid.wallet_verification_qr("v1")
    assert e.value.code == "verification_not_found"


def test_validation_happens_before_the_request() -> None:
    csid, rec = make()
    with pytest.raises(BadRequestError) as e:
        csid.platform_user()
    assert e.value.parameter == "external_id|csid_id"
    with pytest.raises(BadRequestError):
        csid.platform_user("u1", csid_id="x")
    with pytest.raises(BadRequestError) as e:
        csid.update_platform_user("u1")
    assert e.value.code == "missing_parameter"
    with pytest.raises(BadRequestError) as e:
        csid.add_platform_user_wallets("u1", wallets=[])
    assert e.value.code == "wallet_required"
    with pytest.raises(BadRequestError) as e:
        csid.add_platform_user_wallets("u1", wallets=[SOL] * 11)
    assert e.value.parameter == "wallets"
    with pytest.raises(BadRequestError):
        csid.add_platform_user_wallets("u1", wallets=SOL)
    with pytest.raises(BadRequestError) as e:
        csid.start_wallet_verification("u1", chain="tron", address=SOL)  # type: ignore[arg-type]
    assert e.value.parameter == "chain"
    with pytest.raises(BadRequestError) as e:
        csid.platform_leaderboard(blockchain="solana", trust="everyone")  # type: ignore[arg-type]
    assert e.value.allowed == ["all", "verified"]
    with pytest.raises(BadRequestError):
        csid.platform_user_profile("u1", period="2d")  # type: ignore[arg-type]
    with pytest.raises(BadRequestError):
        csid.update_platform_settings()
    with pytest.raises(BadRequestError) as e:
        csid.update_platform_settings(data_scope="world")  # type: ignore[arg-type]
    assert e.value.allowed == ["csid", "platform"]
    with pytest.raises(BadRequestError):
        csid.connect_platform_user_x("u1", return_url="")
    with pytest.raises(BadRequestError) as e:
        csid.import_platform_users([])
    with pytest.raises(BadRequestError) as e:
        csid.import_platform_users([{"external_id": str(i), "wallets": [SOL]} for i in range(1001)])
    assert e.value.parameter == "users"
    assert rec.requests == []


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (400, "wallet_required", BadRequestError),
        (400, "invalid_address", BadRequestError),
        (403, "plan_user_limit", PlanUserLimitError),
        (403, "claim_disabled", PermissionError),
        (404, "platform_user_not_found", NotFoundError),
        (404, "competition_not_found", NotFoundError),
        (409, "account_claimed", ConflictError),
        (409, "last_wallet", ConflictError),
        (409, "competition_full", ConflictError),
        (429, "rate_limited", RateLimitError),
        (503, "service_unavailable", ServerError),
    ],
)
def test_platform_error_codes(status: int, code: str, cls: type) -> None:
    csid, _ = make(lambda r: api_error(status, code, user_limit=25))
    with pytest.raises(cls) as e:
        csid.upsert_platform_user("u1", wallets=[SOL])
    assert e.value.code == code and e.value.status == status
    if code == "plan_user_limit":
        assert e.value.body["user_limit"] == 25


def test_posts_are_not_retried_on_platform_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    csid, rec = make(lambda r: api_error(429, "rate_limited"), max_retries=2)
    with pytest.raises(RateLimitError):
        csid.upsert_platform_user("u1", wallets=[SOL])
    assert len(rec.requests) == 1  # writes retry only the API-wide limit (rate_limit_exceeded)


def test_webhook_event_names() -> None:
    for name in ("platform_user.created", "platform_user.claimed", "wallet.added", "verification.expired"):
        assert name in PLATFORM_WEBHOOK_EVENTS and name in WEBHOOK_EVENTS
    assert "competition.ended" in WEBHOOK_EVENTS


# ── pagination ───────────────────────────────────────────────────────────────


def test_iter_platform_users_follows_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor" not in query(r):
            return ok(
                [{"external_id": "a"}, {"external_id": "b"}],
                pagination={"limit": 2, "total": 3, "has_more": True, "next_cursor": "Yw=="},
            )
        return ok([{"external_id": "c"}], pagination={"limit": 2, "total": 3, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    assert [u["external_id"] for u in csid.iter_platform_users(limit=2)] == ["a", "b", "c"]
    assert [r.url.path for r in rec.requests] == ["/v1/platform-users/list"] * 2
    assert query(rec.requests[0]) == {"limit": "2"}
    assert query(rec.requests[1]) == {"limit": "2", "cursor": "Yw=="}


def test_iter_platform_leaderboard_reads_envelope_pagination() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor" not in query(r):
            return ok(
                {"blockchain": "solana", "leaderboard": [{"wallet": "w1", "external_id": "a"}]},
                pagination={"limit": 1, "total": 2, "has_more": True, "next_cursor": "w1"},
            )
        return ok(
            {"blockchain": "solana", "leaderboard": [{"wallet": "w2", "external_id": "b"}]},
            pagination={"limit": 1, "total": 2, "has_more": False, "next_cursor": None},
        )

    csid, rec = make(handler)
    entries = list(csid.iter_platform_leaderboard(blockchain="solana", sort="pnl_usd", limit=1))
    assert [e["external_id"] for e in entries] == ["a", "b"]
    assert query(rec.requests[1]) == {"blockchain": "solana", "sort": "pnl_usd", "limit": "1", "cursor": "w1"}


# ── bulk import: chunking, retries, resuming ─────────────────────────────────


def users(n: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"external_id": f"u{i}", "wallets": [SOL]} for i in range(start, start + n)]


def created(items: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(items)
    return {
        "summary": {"created": n, "updated": 0, "unchanged": 0, "rejected": 0},
        "results": [
            {"external_id": u["external_id"], "csid_id": f"id-{u['external_id']}", "status": "created"} for u in items
        ],
    }


def test_bulk_import_chunks_and_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("no sleep expected"))
    csid, rec = make(lambda r: ok(created(body(r)["users"])))
    result = csid.bulk_import_platform_users(users(2500))
    sizes = [len(body(r)["users"]) for r in rec.requests]
    assert sizes == [1000, 1000, 500]
    assert all(r.url.path == "/v1/platform-users/import" for r in rec.requests)
    assert result["summary"] == {"created": 2500, "updated": 0, "unchanged": 0, "rejected": 0}
    assert [r["external_id"] for r in result["results"]] == [f"u{i}" for i in range(2500)]
    assert result["requests"] == 3


def test_bulk_import_respects_chunk_size_and_body_limit() -> None:
    csid, rec = make(lambda r: ok(created(body(r)["users"])))
    csid.bulk_import_platform_users(users(5), chunk_size=2)
    assert [len(body(r)["users"]) for r in rec.requests] == [2, 2, 1]

    csid, rec = make(lambda r: ok(created(body(r)["users"])))
    big = [{"external_id": f"u{i}", "wallets": [SOL], "display_name": "x" * 400} for i in range(30)]
    csid.bulk_import_platform_users(big, max_body_bytes=5_000)
    assert all(len(r.content) <= 5_000 for r in rec.requests)
    assert sum(len(body(r)["users"]) for r in rec.requests) == 30
    assert len(rec.requests) > 1


def test_bulk_import_retries_429_with_retry_after_without_resending_done_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 2:  # the second chunk is refused once
            return api_error(429, "rate_limit_exceeded", headers={"Retry-After": "3"})
        return ok(created(body(r)["users"]))

    csid, rec = make(handler)
    result = csid.bulk_import_platform_users(users(4), chunk_size=2)
    sent = [[u["external_id"] for u in body(r)["users"]] for r in rec.requests]
    assert sent == [["u0", "u1"], ["u2", "u3"], ["u2", "u3"]]
    assert sleeps == [3.0]
    assert result["summary"]["created"] == 4
    assert result["requests"] == 3


def test_bulk_import_resends_only_rate_limited_users(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    monkeypatch.setattr("time.time", lambda: 1_000_065.0)  # 45 s into a minute

    def handler(r: httpx.Request) -> httpx.Response:
        items = body(r)["users"]
        if len(items) == 3:  # first call: the last two hit the per-minute limit for new users
            res = created(items[:1])["results"] + [
                {
                    "external_id": u["external_id"],
                    "status": "rejected",
                    "error": {"code": "rate_limited", "message": "At most 2000 new platform users per minute."},
                }
                for u in items[1:]
            ]
            return ok({"summary": {}, "results": res})
        return ok(created(items))

    csid, rec = make(handler)
    result = csid.bulk_import_platform_users(users(3))
    sent = [[u["external_id"] for u in body(r)["users"]] for r in rec.requests]
    assert sent == [["u0", "u1", "u2"], ["u1", "u2"]]
    assert sleeps == [16.0]  # until the next minute, plus one second
    assert [r["status"] for r in result["results"]] == ["created"] * 3
    assert result["summary"] == {"created": 3, "updated": 0, "unchanged": 0, "rejected": 0}


def test_bulk_import_gives_up_on_rate_limited_users_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    limited = {"status": "rejected", "error": {"code": "rate_limited", "message": "slow down"}}
    csid, rec = make(
        lambda r: ok({"results": [{**limited, "external_id": u["external_id"]} for u in body(r)["users"]]})
    )
    result = csid.bulk_import_platform_users(users(2), max_attempts=3)
    assert len(rec.requests) == 3
    assert result["summary"]["rejected"] == 2


def test_bulk_import_keeps_other_rejections() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return ok(
            {
                "results": [
                    {"external_id": "u0", "status": "unchanged", "csid_id": "a"},
                    {
                        "external_id": "u1",
                        "status": "rejected",
                        "error": {"code": "plan_user_limit", "message": "full"},
                    },
                ]
            }
        )

    csid, rec = make(handler)
    result = csid.bulk_import_platform_users(users(2))
    assert len(rec.requests) == 1
    assert result["summary"] == {"created": 0, "updated": 0, "unchanged": 1, "rejected": 1}


def test_bulk_import_stops_with_partial_result_and_remaining(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 2:
            return api_error(500, "internal_error")
        return ok(created(body(r)["users"]))

    csid, rec = make(handler, max_retries=2)
    with pytest.raises(PlatformImportError) as e:
        csid.bulk_import_platform_users(users(6), chunk_size=2)
    err = e.value
    assert len(rec.requests) == 2  # a 500 on a write is not retried
    assert err.status == 500 and err.code == "internal_error"
    assert isinstance(err.__cause__, ServerError)
    assert [r["external_id"] for r in err.result["results"]] == ["u0", "u1"]
    assert err.result["summary"]["created"] == 2
    assert [u["external_id"] for u in err.remaining] == ["u2", "u3", "u4", "u5"]

    # resume with the rest
    csid, rec = make(lambda r: ok(created(body(r)["users"])))
    assert csid.bulk_import_platform_users(err.remaining)["summary"]["created"] == 4


def test_bulk_import_gives_up_on_429_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    csid, rec = make(lambda r: api_error(429, "rate_limit_exceeded"))
    with pytest.raises(PlatformImportError) as e:
        csid.bulk_import_platform_users(users(3), max_attempts=2)
    assert len(rec.requests) == 2
    assert e.value.status == 429
    assert len(e.value.remaining) == 3 and e.value.result["results"] == []


def test_bulk_import_arguments() -> None:
    csid, rec = make()
    with pytest.raises(ValueError):
        csid.bulk_import_platform_users(users(1), chunk_size=1001)
    with pytest.raises(ValueError):
        csid.bulk_import_platform_users(users(1), max_attempts=0)
    with pytest.raises(BadRequestError):
        csid.bulk_import_platform_users({"external_id": "u1"})  # type: ignore[arg-type]
    assert csid.bulk_import_platform_users([]) == {
        "summary": {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0},
        "results": [],
        "requests": 0,
    }
    assert rec.requests == []


# ── async ────────────────────────────────────────────────────────────────────


async def test_async_platform_users(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    calls = {"import": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/platform-users/import":
            calls["import"] += 1
            if calls["import"] == 1:
                return api_error(429, "rate_limit_exceeded", headers={"Retry-After": "2"})
            return ok(created(body(r)["users"]))
        if r.url.path == "/v1/platform-users/list":
            if "cursor" not in query(r):
                return ok([{"external_id": "a"}], pagination={"has_more": True, "next_cursor": "x"})
            return ok([{"external_id": "b"}], pagination={"has_more": False, "next_cursor": None})
        if r.url.path == "/v1/platform-users/leaderboard":
            return ok({"leaderboard": [{"wallet": "w"}]}, pagination={"has_more": False, "next_cursor": None})
        if r.url.path.endswith("/qr"):
            return httpx.Response(200, text="<svg/>")
        return ok({"external_id": "u1", "created": True})

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.upsert_platform_user("u1", wallets=[SOL]))["created"] is True
        assert (await csid.platform_user_kol("u1"))["external_id"] == "u1"
        assert await csid.wallet_verification_qr("v1") == "<svg/>"
        result = await csid.bulk_import_platform_users(users(3), chunk_size=2)
        assert result["summary"]["created"] == 3 and result["requests"] == 3
        assert [u["external_id"] async for u in csid.iter_platform_users()] == ["a", "b"]
        assert [e["wallet"] async for e in csid.iter_platform_leaderboard(blockchain="base")] == ["w"]
    assert sleeps == [2.0]
    imports = [[u["external_id"] for u in body(r)["users"]] for r in rec.requests if r.url.path.endswith("/import")]
    assert imports == [["u0", "u1"], ["u0", "u1"], ["u2"]]
    assert call(rec.requests[1]) == ("GET", "/v1/platform-users/kol", {"external_id": "u1"})


async def test_async_bulk_import_failure() -> None:
    rec = Recorder(lambda r: api_error(403, "invalid_api_key"))
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        with pytest.raises(PlatformImportError) as e:
            await csid.bulk_import_platform_users(users(2))
    assert e.value.code == "invalid_api_key"
    assert len(e.value.remaining) == 2
