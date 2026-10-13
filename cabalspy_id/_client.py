"""Data API clients for CabalSpy ID (https://api-id.cabalspy.xyz/v1), sync and async.

The endpoint methods live once in :class:`_Endpoints`. They return whatever the
underlying requester returns: a dict on the sync client, an awaitable on the
async one.

Auth: ``Authorization: Bearer <API_KEY>``. The same key as the CabalSpy API,
with the "CabalSpy ID" toggle enabled on the API keys page of
https://apidashboard.cabalspy.xyz.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import TYPE_CHECKING, Any

import httpx

from ._constants import (
    CHAINS,
    DEFAULT_BASE_URL,
    DEFAULT_STREAM_URL,
    LEADERBOARD_SORTS,
    PERIODS,
    SCOPES,
    USER_AGENT,
    Chain,
    LeaderboardSort,
    Period,
    Scope,
)
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    CabalSpyIDError,
    InvalidResponseError,
    RateLimit,
    RateLimitError,
    error_from_status,
    is_retryable,
)

if TYPE_CHECKING:
    from ._stream import CabalSpyIDStream

__all__ = ["CabalSpyID", "AsyncCabalSpyID", "Envelope"]


class Envelope:
    """A full API response: data plus pagination, meta and rate limit headers."""

    __slots__ = ("data", "meta", "pagination", "rate_limit", "status")

    def __init__(
        self,
        data: Any,
        pagination: dict[str, Any] | None,
        meta: dict[str, Any],
        rate_limit: RateLimit,
        status: int,
    ) -> None:
        self.data = data
        self.pagination = pagination
        self.meta = meta
        self.rate_limit = rate_limit
        self.status = status

    def __repr__(self) -> str:
        keys = list(self.data)[:5] if isinstance(self.data, dict) else type(self.data).__name__
        return f"Envelope(status={self.status}, data_keys={keys})"


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drops None and empty values so they never reach the query string."""
    out: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        out[key] = "true" if value is True else "false" if value is False else value
    return out


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _backoff(attempt: int, last: BaseException | None) -> float:
    """Server Retry-After wins over our own exponential backoff."""
    if isinstance(last, RateLimitError) and last.retry_after is not None:
        return float(min(last.retry_after, 60.0))
    return float(min(0.5 * 2.0 ** (attempt - 1), 8.0) + random.random() * 0.25)


def _one_of(value: Any, allowed: tuple[str, ...], parameter: str) -> None:
    if value is not None and value not in allowed:
        raise BadRequestError(
            f"Invalid value for {parameter!r}: {value!r}",
            code="invalid_parameter",
            parameter=parameter,
            allowed=list(allowed),
        )


def _required(value: Any, parameter: str) -> None:
    if value is None or value == "":
        raise BadRequestError(f"Parameter {parameter!r} is required", code="missing_parameter", parameter=parameter)


def _wallet(blockchain: Any, address: Any) -> None:
    _required(blockchain, "blockchain")
    _one_of(blockchain, CHAINS, "blockchain")
    _required(address, "address")


def _page_pagination(page: Envelope) -> dict[str, Any] | None:
    """Envelope-level pagination, or the leaderboard's inside ``data``."""
    inner = page.data.get("pagination") if isinstance(page.data, dict) else None
    return page.pagination or inner


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINTS  (shared between the sync and async clients)
# ═══════════════════════════════════════════════════════════════════════════


class _Endpoints:
    def _get(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Any:  # pragma: no cover
        raise NotImplementedError

    # ── account ──────────────────────────────────────────────────────────

    def health(self) -> Any:
        """GET /v1/health — service health and trade sync freshness. No API key needed.

        Returns :class:`~cabalspy_id.HealthResponse`.
        """
        return self._get("/health", auth=False)

    def me(self) -> Any:
        """GET /v1/me — the key's instance, plan, request rate and users with data.

        Returns :class:`~cabalspy_id.MeResponse`.
        """
        return self._get("/me")

    # ── users ────────────────────────────────────────────────────────────

    def users(
        self,
        *,
        limit: int | None = None,
        kol: bool | None = None,
        cursor: str | None = None,
        scope: Scope | None = None,
    ) -> Any:
        """GET /v1/users — users of your instance (within the plan's user limit), newest first.

        ``limit`` 1-100 (default 50); ``kol=True`` only users with the KOL badge.
        Returns a list of :class:`~cabalspy_id.Profile`.
        """
        _one_of(scope, SCOPES, "scope")
        return self._get(
            "/users",
            {"limit": limit, "kol": "true" if kol else None, "cursor": cursor, "scope": scope},
        )

    def profile(
        self,
        *,
        username: str | None = None,
        csid_id: str | None = None,
        address: str | None = None,
        scope: Scope | None = None,
    ) -> Any:
        """GET /v1/profile — one user by X username, ``csid_id`` (the ``sub`` of
        their ID token) or a verified wallet address. Pass exactly one.

        An anonymous ``anon_...`` sub raises :class:`~cabalspy_id.PlanUserLimitError`.
        Returns :class:`~cabalspy_id.Profile`.
        """
        if sum(1 for v in (username, csid_id, address) if v) != 1:
            raise BadRequestError(
                "Pass exactly one of: username, csid_id, address.",
                code="missing_parameter",
                parameter="username|csid_id|address",
            )
        _one_of(scope, SCOPES, "scope")
        return self._get(
            "/profile",
            {
                "username": username.lstrip("@") if username else None,
                "csid_id": csid_id,
                "address": address,
                "scope": scope,
            },
        )

    def wallet_lookup(self, address: str, *, scope: Scope | None = None) -> Any:
        """GET /v1/wallets/lookup — which of your users verified this wallet.

        Returns :class:`~cabalspy_id.WalletLookupResponse`.
        """
        _required(address, "address")
        return self._get("/wallets/lookup", {"address": address, "scope": scope})

    # ── trading ──────────────────────────────────────────────────────────

    def tracker(
        self, *, blockchain: Chain, address: str, period: Period | None = None, scope: Scope | None = None
    ) -> Any:
        """GET /v1/wallets/tracker — stats, realized PnL, win-rate distribution,
        tokens, PnL chart (cumulative from 0) and trades of a verified wallet.

        Same numbers as the CabalSpy API. Returns :class:`~cabalspy_id.TrackerResponse`.
        """
        _wallet(blockchain, address)
        _one_of(period, PERIODS, "period")
        return self._get(
            "/wallets/tracker",
            {"blockchain": blockchain, "address": address, "period": period, "scope": scope},
        )

    def history(
        self,
        *,
        blockchain: Chain,
        address: str,
        limit: int | None = None,
        cursor: str | None = None,
        scope: Scope | None = None,
    ) -> Any:
        """GET /v1/wallets/history — lifetime stats, token overview and one page
        of trades (``limit`` 1-1000, default 500).

        Returns :class:`~cabalspy_id.HistoryResponse`.
        """
        _wallet(blockchain, address)
        return self._get(
            "/wallets/history",
            {"blockchain": blockchain, "address": address, "limit": limit, "cursor": cursor, "scope": scope},
        )

    def holdings(self, *, blockchain: Chain, address: str, scope: Scope | None = None) -> Any:
        """GET /v1/wallets/holdings — current balances with USD value (dust under $0.01 hidden).

        Returns :class:`~cabalspy_id.HoldingsResponse`.
        """
        _wallet(blockchain, address)
        return self._get("/wallets/holdings", {"blockchain": blockchain, "address": address, "scope": scope})

    def pnl_calendar(self, *, blockchain: Chain, address: str, scope: Scope | None = None) -> Any:
        """GET /v1/wallets/pnl_calendar — realized PnL per UTC day, grouped by month.

        Returns :class:`~cabalspy_id.PnlCalendarResponse`.
        """
        _wallet(blockchain, address)
        return self._get("/wallets/pnl_calendar", {"blockchain": blockchain, "address": address, "scope": scope})

    def leaderboard(
        self,
        *,
        blockchain: Chain,
        period: Period | None = None,
        sort: LeaderboardSort | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        scope: Scope | None = None,
    ) -> Any:
        """GET /v1/wallets/leaderboard — your users ranked by volume, pnl,
        pnl_usd, win_rate or trades (``limit`` 1-500, default 100).

        ``scope="global"`` (every CabalSpy ID user) is Enterprise only.
        Returns :class:`~cabalspy_id.LeaderboardResponse`.
        """
        _required(blockchain, "blockchain")
        _one_of(blockchain, CHAINS, "blockchain")
        _one_of(period, PERIODS, "period")
        _one_of(sort, LEADERBOARD_SORTS, "sort")
        _one_of(scope, SCOPES, "scope")
        return self._get(
            "/wallets/leaderboard",
            {
                "blockchain": blockchain,
                "period": period,
                "sort": sort,
                "limit": limit,
                "cursor": cursor,
                "scope": scope,
            },
        )

    def latest_transactions(
        self, *, blockchain: Chain | None = None, limit: int | None = None, scope: Scope | None = None
    ) -> Any:
        """GET /v1/transactions/latest — newest trades of your users, each with the trader.

        Omit ``blockchain`` for every chain; ``limit`` 1-100 (default 50).
        Returns a list of :class:`~cabalspy_id.Trade`.
        """
        _one_of(blockchain, CHAINS, "blockchain")
        return self._get("/transactions/latest", {"blockchain": blockchain, "limit": limit, "scope": scope})


# ═══════════════════════════════════════════════════════════════════════════
#  CLIENTS
# ═══════════════════════════════════════════════════════════════════════════


class _BaseClient(_Endpoints):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        instance: str | None = None,
        base_url: str | None = None,
        stream_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else (_env("CABALSPY_ID_API_KEY") or _env("CABALSPY_API_KEY") or "")
        )
        #: Instance client_id, only needed when the account has several.
        self.instance = instance or _env("CABALSPY_ID_INSTANCE")
        self.base_url = (base_url or _env("CABALSPY_ID_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.stream_url = (stream_url or _env("CABALSPY_ID_STREAM_URL") or DEFAULT_STREAM_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._extra_headers = dict(headers or {})
        #: Rate limit state from the most recent request.
        self.last_rate_limit = RateLimit()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, instance={self.instance!r})"

    # ── plumbing shared by both clients ──────────────────────────────────

    def _prepare(
        self, path: str, params: Mapping[str, Any] | None, auth: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        if auth and not self._api_key:
            raise AuthenticationError(
                "Missing API key. Pass api_key= or set CABALSPY_ID_API_KEY "
                "(the CabalSpy API key with CabalSpy ID enabled).",
                status=401,
                code="missing_api_key",
            )
        query = _clean_params(params)
        if auth and self.instance and "instance" not in query:
            query["instance"] = self.instance
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if auth:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self._extra_headers)
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        return url, query, headers

    def _interpret(self, response: httpx.Response, path: str) -> Envelope:
        """Turns an HTTP response into an Envelope, or raises the right error."""
        rate_limit = RateLimit(
            _int_header(response.headers, "X-RateLimit-Limit"),
            _int_header(response.headers, "X-RateLimit-Remaining"),
            _int_header(response.headers, "X-RateLimit-Reset"),
        )
        self.last_rate_limit = rate_limit
        try:
            parsed: Any = response.json() if response.content else None
        except ValueError:
            parsed = None

        if response.status_code >= 400:
            body = parsed.get("error") if isinstance(parsed, dict) else None
            raise error_from_status(
                response.status_code,
                body if isinstance(body, dict) else None,
                rate_limit,
                _int_header(response.headers, "Retry-After"),
                f"HTTP {response.status_code} on GET {path}",
            )
        if not isinstance(parsed, dict) or "data" not in parsed:
            raise InvalidResponseError(
                f"Unexpected response shape on GET {path}: no data field",
                status=response.status_code,
                code="invalid_response",
                rate_limit=rate_limit,
            )
        return Envelope(
            parsed["data"], parsed.get("pagination"), parsed.get("meta") or {}, rate_limit, response.status_code
        )

    def _connection_error(self, exc: Exception, path: str) -> APIConnectionError:
        if isinstance(exc, httpx.TimeoutException):
            return APIConnectionError(f"Request timed out after {self.timeout}s: GET {path}", code="timeout")
        return APIConnectionError(f"Network error: {exc}", code="connection_error")

    def stream(
        self,
        *,
        blockchain: Chain | None = None,
        scope: Scope | None = None,
        **kwargs: Any,
    ) -> CabalSpyIDStream:
        """Live trades of your users over WebSocket (Pro plan and up). Async only.

        Needs the ``stream`` extra: ``pip install "cabalspy-id[stream]"``.
        """
        if not self._api_key:
            raise AuthenticationError("The stream needs an API key.", status=401, code="missing_api_key")
        from ._stream import CabalSpyIDStream

        return CabalSpyIDStream(
            self.stream_url, self._api_key, blockchain=blockchain, scope=scope, instance=self.instance, **kwargs
        )


class CabalSpyID(_BaseClient):
    """Synchronous Data API client.

    from cabalspy_id import CabalSpyID

    csid = CabalSpyID()                     # reads CABALSPY_ID_API_KEY / CABALSPY_API_KEY
    me = csid.me()
    user = csid.profile(csid_id=claims["sub"])
    """

    def __init__(self, api_key: str | None = None, *, http_client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._owns_http = http_client is None

    def __enter__(self) -> CabalSpyID:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def get_raw(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Envelope:
        """Any GET, returning the full envelope (data, pagination, meta, rate limit)."""
        url, query, headers = self._prepare(path, params, auth)
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(_backoff(attempt, last))
            try:
                response = self._http.get(url, params=query, headers=headers)
            except httpx.HTTPError as exc:
                last = self._connection_error(exc, path)
                continue
            try:
                return self._interpret(response, path)
            except CabalSpyIDError as exc:
                if is_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: GET {path}")

    def _get(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Any:
        return self.get_raw(path, params, auth=auth).data

    def pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, max_pages: int | None = None
    ) -> Iterator[Envelope]:
        """Walks a cursor-paginated route and yields whole pages (envelopes)."""
        query = dict(params or {})
        cursor = query.pop("cursor", None)
        n = 0
        while max_pages is None or n < max_pages:
            n += 1
            page = self.get_raw(path, {**query, "cursor": cursor})
            page.pagination = _page_pagination(page)
            yield page
            if not page.pagination or not page.pagination.get("has_more") or not page.pagination.get("next_cursor"):
                return
            cursor = page.pagination["next_cursor"]

    def iter_users(self, **params: Any) -> Iterator[dict[str, Any]]:
        """Every user of your instance, following ``next_cursor``. Takes the users() parameters."""
        for page in self.pages("/users", _users_query(params)):
            yield from page.data

    def iter_history(self, *, blockchain: Chain, address: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Every trade of a wallet, newest first, following ``next_cursor``."""
        _wallet(blockchain, address)
        for page in self.pages("/wallets/history", {"blockchain": blockchain, "address": address, **params}):
            yield from page.data.get("trades", [])

    def iter_leaderboard(self, *, blockchain: Chain, **params: Any) -> Iterator[dict[str, Any]]:
        """Every leaderboard entry, following ``next_cursor``."""
        _required(blockchain, "blockchain")
        _one_of(blockchain, CHAINS, "blockchain")
        for page in self.pages("/wallets/leaderboard", {"blockchain": blockchain, **params}):
            yield from page.data.get("leaderboard", [])


class AsyncCabalSpyID(_BaseClient):
    """Asynchronous Data API client.

    from cabalspy_id import AsyncCabalSpyID

    async with AsyncCabalSpyID() as csid:
        me = await csid.me()
    """

    def __init__(
        self, api_key: str | None = None, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any
    ) -> None:
        super().__init__(api_key, **kwargs)
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._owns_http = http_client is None

    async def __aenter__(self) -> AsyncCabalSpyID:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def get_raw(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Envelope:
        """Any GET, returning the full envelope (data, pagination, meta, rate limit)."""
        url, query, headers = self._prepare(path, params, auth)
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(_backoff(attempt, last))
            try:
                response = await self._http.get(url, params=query, headers=headers)
            except httpx.HTTPError as exc:
                last = self._connection_error(exc, path)
                continue
            try:
                return self._interpret(response, path)
            except CabalSpyIDError as exc:
                if is_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: GET {path}")

    async def _get(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Any:
        return (await self.get_raw(path, params, auth=auth)).data

    async def pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, max_pages: int | None = None
    ) -> AsyncIterator[Envelope]:
        """Async version of :meth:`CabalSpyID.pages`."""
        query = dict(params or {})
        cursor = query.pop("cursor", None)
        n = 0
        while max_pages is None or n < max_pages:
            n += 1
            page = await self.get_raw(path, {**query, "cursor": cursor})
            page.pagination = _page_pagination(page)
            yield page
            if not page.pagination or not page.pagination.get("has_more") or not page.pagination.get("next_cursor"):
                return
            cursor = page.pagination["next_cursor"]

    async def iter_users(self, **params: Any) -> AsyncIterator[dict[str, Any]]:
        """Every user of your instance, following ``next_cursor``."""
        async for page in self.pages("/users", _users_query(params)):
            for user in page.data:
                yield user

    async def iter_history(self, *, blockchain: Chain, address: str, **params: Any) -> AsyncIterator[dict[str, Any]]:
        """Every trade of a wallet, newest first, following ``next_cursor``."""
        _wallet(blockchain, address)
        async for page in self.pages("/wallets/history", {"blockchain": blockchain, "address": address, **params}):
            for trade in page.data.get("trades", []):
                yield trade

    async def iter_leaderboard(self, *, blockchain: Chain, **params: Any) -> AsyncIterator[dict[str, Any]]:
        """Every leaderboard entry, following ``next_cursor``."""
        _required(blockchain, "blockchain")
        _one_of(blockchain, CHAINS, "blockchain")
        async for page in self.pages("/wallets/leaderboard", {"blockchain": blockchain, **params}):
            for entry in page.data.get("leaderboard", []):
                yield entry


def _users_query(params: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"limit", "kol", "cursor", "scope"}
    unknown = set(params) - allowed
    if unknown:
        raise TypeError(f"unexpected parameter(s): {', '.join(sorted(unknown))}")
    _one_of(params.get("scope"), SCOPES, "scope")
    return {**params, "kol": "true" if params.get("kol") else None}
