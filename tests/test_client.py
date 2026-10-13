from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from cabalspy_id import (
    SDK_VERSION,
    APIConnectionError,
    AsyncCabalSpyID,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    InvalidResponseError,
    NotFoundError,
    PermissionError,
    PlanUserLimitError,
    RateLimit,
    RateLimitError,
    ServerError,
)

from .conftest import Recorder, api_error, ok

KEY = "csid_api_testkey"


def make(handler, **kwargs) -> tuple[CabalSpyID, Recorder]:
    rec = Recorder(handler)
    kwargs.setdefault("max_retries", 0)
    return CabalSpyID(KEY, http_client=rec.client(), **kwargs), rec


def query(req: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}


def test_sends_key_user_agent_and_reads_rate_limit() -> None:
    csid, rec = make(lambda r: ok({"plan": "pro", "rate_limit_rps": 10}))
    assert csid.me()["plan"] == "pro"
    req = rec.requests[0]
    assert str(req.url) == "https://api-id.cabalspy.xyz/v1/me"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["user-agent"] == f"cabalspy-id-python/{SDK_VERSION}"
    assert csid.last_rate_limit == RateLimit(10, 9, 1)


def test_instance_is_added() -> None:
    csid, rec = make(lambda r: ok([]), instance="csid_abc")
    csid.users(limit=5, kol=True)
    assert rec.requests[0].url.path == "/v1/users"
    assert query(rec.requests[0]) == {"limit": "5", "kol": "true", "instance": "csid_abc"}


def test_health_needs_no_key() -> None:
    rec = Recorder(lambda r: ok({"status": "ok", "trade_sync_age_seconds": 1}))
    csid = CabalSpyID("", http_client=rec.client())
    assert csid.health() == {"status": "ok", "trade_sync_age_seconds": 1}
    assert "authorization" not in rec.requests[0].headers
    with pytest.raises(AuthenticationError):
        csid.me()


def test_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CABALSPY_ID_API_KEY", "")
    monkeypatch.setenv("CABALSPY_API_KEY", "from_env")
    rec = Recorder(lambda r: ok({}))
    CabalSpyID(http_client=rec.client()).me()
    assert rec.requests[0].headers["authorization"] == "Bearer from_env"


def test_every_endpoint() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return ok({})

    csid, rec = make(handler)
    w = {"blockchain": "solana", "address": "So1"}
    csid.profile(username="@alice")
    csid.profile(csid_id="4b7c")
    csid.wallet_lookup("0xABC")
    csid.tracker(**w, period="7d")
    csid.history(**w, limit=1)
    csid.holdings(**w)
    csid.pnl_calendar(**w)
    csid.leaderboard(blockchain="base", period="30d", sort="pnl_usd", limit=10)
    csid.latest_transactions(limit=3)
    csid.users(scope="global")
    got = [f"{r.url.path}?{r.url.query.decode()}" for r in rec.requests]
    assert got == [
        "/v1/profile?username=alice",
        "/v1/profile?csid_id=4b7c",
        "/v1/wallets/lookup?address=0xABC",
        "/v1/wallets/tracker?blockchain=solana&address=So1&period=7d",
        "/v1/wallets/history?blockchain=solana&address=So1&limit=1",
        "/v1/wallets/holdings?blockchain=solana&address=So1",
        "/v1/wallets/pnl_calendar?blockchain=solana&address=So1",
        "/v1/wallets/leaderboard?blockchain=base&period=30d&sort=pnl_usd&limit=10",
        "/v1/transactions/latest?limit=3",
        "/v1/users?scope=global",
    ]


def test_validation_happens_before_the_request() -> None:
    csid, rec = make(lambda r: ok({}))
    with pytest.raises(BadRequestError):
        csid.profile(username="a", address="b")
    with pytest.raises(BadRequestError) as e:
        csid.tracker(blockchain="tron", address="x")  # type: ignore[arg-type]
    assert e.value.parameter == "blockchain"
    with pytest.raises(BadRequestError) as e:
        csid.tracker(blockchain="eth", address="x", period="2d")  # type: ignore[arg-type]
    assert e.value.allowed == ["6h", "1d", "7d", "30d"]
    with pytest.raises(BadRequestError) as e:
        csid.leaderboard(blockchain="eth", sort="best")  # type: ignore[arg-type]
    assert e.value.parameter == "sort"
    with pytest.raises(BadRequestError) as e:
        csid.holdings(blockchain="eth", address="")
    assert e.value.code == "missing_parameter"
    assert rec.requests == []


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (400, "invalid_parameter", BadRequestError),
        (400, "instance_required", BadRequestError),
        (401, "missing_api_key", AuthenticationError),
        (403, "invalid_api_key", PermissionError),
        (403, "scope_not_allowed", PermissionError),
        (403, "plan_user_limit", PlanUserLimitError),
        (404, "wallet_not_found", NotFoundError),
        (404, "profile_not_found", NotFoundError),
        (429, "rate_limit_exceeded", RateLimitError),
        (503, "service_unavailable", ServerError),
    ],
)
def test_errors(status: int, code: str, cls: type) -> None:
    csid, _ = make(
        lambda r: api_error(status, code, f"msg {code}", {"Retry-After": "1"}, parameter="period", allowed=["1d"])
    )
    with pytest.raises(cls) as e:
        csid.me()
    err = e.value
    assert (err.status, err.code, err.message, err.request_id, err.parameter, err.allowed) == (
        status,
        code,
        f"msg {code}",
        "req_err",
        "period",
        ["1d"],
    )
    assert err.docs == f"https://docs.cabalspy.xyz/cabalspy-id/errors#{code}"
    if isinstance(err, RateLimitError):
        assert err.retry_after == 1
    if isinstance(err, PlanUserLimitError):
        assert err.limited is True
        assert isinstance(err, PermissionError)


def test_retries_429_and_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    answers = iter(
        [
            api_error(429, "rate_limit_exceeded", headers={"Retry-After": "1"}),
            api_error(500, "internal_error"),
            ok({"plan": "free"}),
        ]
    )
    csid, rec = make(lambda r: next(answers), max_retries=2)
    assert csid.me() == {"plan": "free"}
    assert len(rec.requests) == 3
    assert sleeps[0] == 1.0  # Retry-After wins


def test_no_retry_on_4xx() -> None:
    csid, rec = make(lambda r: api_error(404, "wallet_not_found"), max_retries=3)
    with pytest.raises(NotFoundError):
        csid.me()
    assert len(rec.requests) == 1


def test_network_errors_and_bad_bodies() -> None:
    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    csid, _ = make(boom)
    with pytest.raises(APIConnectionError) as e:
        csid.me()
    assert e.value.code == "connection_error"
    csid, _ = make(lambda r: httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(InvalidResponseError):
        csid.me()


def test_iter_users_follows_cursor() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor" not in query(r):
            return ok(
                [{"username": "a"}, {"username": "b"}],
                pagination={"limit": 2, "total": 3, "has_more": True, "next_cursor": "c2"},
            )
        return ok([{"username": "c"}], pagination={"limit": 2, "total": 3, "has_more": False, "next_cursor": None})

    csid, rec = make(handler)
    assert [u["username"] for u in csid.iter_users(limit=2)] == ["a", "b", "c"]
    assert query(rec.requests[1])["cursor"] == "c2"


def test_iter_leaderboard_reads_inner_pagination() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor" not in query(r):
            return ok(
                {"leaderboard": [{"wallet": "w1"}], "pagination": {"limit": 1, "has_more": True, "next_cursor": "w1"}}
            )
        return ok(
            {"leaderboard": [{"wallet": "w2"}], "pagination": {"limit": 1, "has_more": False, "next_cursor": None}}
        )

    csid, _ = make(handler)
    assert [e["wallet"] for e in csid.iter_leaderboard(blockchain="solana", limit=1)] == ["w1", "w2"]


def test_iter_history() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if "cursor" not in query(r):
            return ok(
                {"trades": [{"tx_signature": "s1"}]}, pagination={"limit": 1, "has_more": True, "next_cursor": "n"}
            )
        return ok({"trades": [{"tx_signature": "s2"}]}, pagination={"limit": 1, "has_more": False, "next_cursor": None})

    csid, _ = make(handler)
    sigs = [t["tx_signature"] for t in csid.iter_history(blockchain="solana", address="x", limit=1)]
    assert sigs == ["s1", "s2"]


async def test_async_client() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/v1/users":
            if "cursor" not in query(r):
                return ok([{"username": "a"}], pagination={"limit": 1, "has_more": True, "next_cursor": "x"})
            return ok([{"username": "b"}], pagination={"limit": 1, "has_more": False, "next_cursor": None})
        if r.url.path == "/v1/profile":
            return api_error(403, "plan_user_limit")
        return ok({"plan": "pro"})

    rec = Recorder(handler)
    async with AsyncCabalSpyID(KEY, http_client=rec.async_client(), max_retries=0) as csid:
        assert (await csid.me())["plan"] == "pro"
        assert [u["username"] async for u in csid.iter_users()] == ["a", "b"]
        with pytest.raises(PlanUserLimitError):
            await csid.profile(csid_id="anon_x")
        env = await csid.get_raw("/me")
        assert env.status == 200 and env.meta["request_id"] == "req_test"
