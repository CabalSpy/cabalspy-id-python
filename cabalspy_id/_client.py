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
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

import httpx

from ._constants import (
    CHAINS,
    DEFAULT_BASE_URL,
    DEFAULT_STREAM_URL,
    DEFAULT_THESES_STREAM_URL,
    DEFAULT_TRADE_FEED_STREAM_URL,
    LEADERBOARD_SORTS,
    PERIODS,
    SCOPES,
    THESIS_EMOJIS,
    THESIS_REPORT_REASONS,
    THESIS_SCOPES,
    TRADE_FEED_FILTERS,
    USER_AGENT,
    Chain,
    LeaderboardSort,
    Period,
    Scope,
    StreamTopic,
    ThesisEmoji,
    ThesisReportReason,
    ThesisScope,
    ThesisSort,
    ThesisStance,
    TradeFeedFilter,
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
    from ._theses_stream import ThesesStream
    from ._trade_feed_stream import TradeFeedStream

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


def _token(blockchain: Any, mint: Any) -> None:
    _required(blockchain, "blockchain")
    _one_of(blockchain, CHAINS, "blockchain")
    _required(mint, "mint")


def _theses_query(
    blockchain: Any, mint: Any, sort: Any, stance: Any, limit: Any, cursor: Any, csid_id: Any, scope: Any = None
) -> dict[str, Any]:
    _token(blockchain, mint)
    _one_of(sort, ("new", "top"), "sort")
    _one_of(stance, ("bull", "bear"), "stance")
    _one_of(scope, THESIS_SCOPES, "scope")
    return {
        "scope": scope,
        "blockchain": blockchain,
        "mint": mint,
        "sort": sort,
        "stance": stance,
        "limit": limit,
        "cursor": cursor,
        "csid_id": csid_id,
    }


def _trade_feed_query(
    csid_id: str, filter: TradeFeedFilter | None, limit: int | None, cursor: str | None
) -> dict[str, Any]:
    _required(csid_id, "csid_id")
    _one_of(filter, TRADE_FEED_FILTERS, "filter")
    return {"csid_id": csid_id, "filter": filter, "limit": limit, "cursor": cursor}


def _trade_feed_page(csid_id: str, limit: int | None, cursor: str | None) -> dict[str, Any]:
    _required(csid_id, "csid_id")
    return {"csid_id": csid_id, "limit": limit, "cursor": cursor}


def _post_retryable(exc: CabalSpyIDError) -> bool:
    """Writes are retried only when the API's rate limit refused them before they ran."""
    return isinstance(exc, RateLimitError) and exc.code == "rate_limit_exceeded"


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

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:  # pragma: no cover
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

    # ── theses ───────────────────────────────────────────────────────────
    # Reading: theses are public; any key reads them, also outside its instance.

    def list_theses(
        self,
        *,
        blockchain: Chain,
        mint: str,
        sort: ThesisSort | None = None,
        stance: ThesisStance | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        csid_id: str | None = None,
        scope: ThesisScope | None = None,
    ) -> Any:
        """GET /v1/theses — theses on a token, ``new`` or ``top`` first (``limit`` 1-50).

        ``csid_id`` (a viewer) fills ``my_reactions`` and ``is_mine``. ``scope``:
        ``global`` (default, every platform) or ``instance`` (written on your instance).
        Returns a list of :class:`~cabalspy_id.Thesis`.
        """
        return self._get("/theses", _theses_query(blockchain, mint, sort, stance, limit, cursor, csid_id, scope))

    def thesis_summary(self, *, blockchain: Chain, mint: str, scope: ThesisScope | None = None) -> Any:
        """GET /v1/theses/summary — counts (theses, bull, bear, authors) and token info.

        Returns :class:`~cabalspy_id.ThesisSummary`.
        """
        _token(blockchain, mint)
        _one_of(scope, THESIS_SCOPES, "scope")
        return self._get("/theses/summary", {"blockchain": blockchain, "mint": mint, "scope": scope})

    def thesis(self, id: str, *, csid_id: str | None = None) -> Any:
        """GET /v1/theses/item — one thesis or reply. Returns :class:`~cabalspy_id.Thesis`."""
        _required(id, "id")
        return self._get("/theses/item", {"id": id, "csid_id": csid_id})

    def thesis_replies(
        self, id: str, *, limit: int | None = None, cursor: str | None = None, csid_id: str | None = None
    ) -> Any:
        """GET /v1/theses/replies — replies to a thesis (``limit`` 1-100)."""
        _required(id, "id")
        return self._get("/theses/replies", {"id": id, "limit": limit, "cursor": cursor, "csid_id": csid_id})

    def latest_theses(
        self,
        *,
        blockchain: Chain | None = None,
        users: Literal["all", "instance"] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        csid_id: str | None = None,
        scope: ThesisScope | None = None,
    ) -> Any:
        """GET /v1/theses/latest — newest theses on every token.

        ``users="instance"``: only your users' theses; ``scope="instance"``: only
        theses written on your instance.
        """
        _one_of(blockchain, CHAINS, "blockchain")
        _one_of(users, ("all", "instance"), "users")
        _one_of(scope, THESIS_SCOPES, "scope")
        return self._get(
            "/theses/latest",
            {
                "blockchain": blockchain,
                "users": users,
                "scope": scope,
                "limit": limit,
                "cursor": cursor,
                "csid_id": csid_id,
            },
        )

    def user_theses(
        self,
        *,
        csid_id: str | None = None,
        username: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/theses/user — theses of one user, by ``csid_id`` or X ``username`` (exactly one)."""
        if bool(csid_id) == bool(username):
            raise BadRequestError(
                "Pass exactly one of: csid_id, username.", code="missing_parameter", parameter="csid_id|username"
            )
        return self._get(
            "/theses/user",
            {
                "csid_id": csid_id,
                "username": username.lstrip("@") if username else None,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def thesis_eligibility(self, *, blockchain: Chain, mint: str, csid_id: str) -> Any:
        """GET /v1/theses/eligibility — may this user post (holder, not paused) and reply here
        through your app? ``reason`` says why not (consent_required, plan_user_limit, sandbox_user).

        Returns :class:`~cabalspy_id.ThesisEligibility`.
        """
        _token(blockchain, mint)
        _required(csid_id, "csid_id")
        return self._get("/theses/eligibility", {"blockchain": blockchain, "mint": mint, "csid_id": csid_id})

    # Writing happens in the name of one of your users: ``csid_id`` is the ``sub``
    # of their ID token. They must have signed in with the scope "thesis".

    def post_thesis(
        self, *, blockchain: Chain, mint: str, body: str, csid_id: str, stance: ThesisStance | None = None
    ) -> Any:
        """POST /v1/theses — posts a thesis (up to 1000 characters). Holders only (``not_a_holder``)."""
        _token(blockchain, mint)
        _required(body, "body")
        _required(csid_id, "csid_id")
        _one_of(stance, ("bull", "bear"), "stance")
        payload: dict[str, Any] = {"blockchain": blockchain, "mint": mint, "body": body, "csid_id": csid_id}
        if stance:
            payload["stance"] = stance
        return self._post("/theses", payload)

    def reply_to_thesis(self, *, thesis_id: str, body: str, csid_id: str) -> Any:
        """POST /v1/theses/replies — replies to a thesis."""
        _required(thesis_id, "thesis_id")
        _required(body, "body")
        _required(csid_id, "csid_id")
        return self._post("/theses/replies", {"thesis_id": thesis_id, "body": body, "csid_id": csid_id})

    def react_to_thesis(self, *, thesis_id: str, emoji: ThesisEmoji, csid_id: str, on: bool = True) -> Any:
        """POST /v1/theses/reactions — adds (or with ``on=False`` removes) a reaction.

        Returns ``{"id", "reactions"}`` with the new counts.
        """
        _required(thesis_id, "thesis_id")
        _one_of(emoji, THESIS_EMOJIS, "emoji")
        _required(csid_id, "csid_id")
        return self._post("/theses/reactions", {"thesis_id": thesis_id, "emoji": emoji, "on": on, "csid_id": csid_id})

    def report_thesis(
        self, *, thesis_id: str, reason: ThesisReportReason, csid_id: str, note: str | None = None
    ) -> Any:
        """POST /v1/theses/report — reports a post (hidden for review after 3 reports)."""
        _required(thesis_id, "thesis_id")
        _one_of(reason, THESIS_REPORT_REASONS, "reason")
        _required(csid_id, "csid_id")
        payload: dict[str, Any] = {"thesis_id": thesis_id, "reason": reason, "csid_id": csid_id}
        if note:
            payload["note"] = note
        return self._post("/theses/report", payload)

    def thesis_notifications(self, csid_id: str) -> Any:
        """GET /v1/theses/notifications — moderation notifications of one of your users
        (warnings, hidden posts, pauses, appeal results), with the unread count.

        Returns :class:`~cabalspy_id.ThesisNotifications`.
        """
        _required(csid_id, "csid_id")
        return self._get("/theses/notifications", {"csid_id": csid_id})

    def appeal_thesis_decision(self, csid_id: str, notification_id: int, message: str) -> Any:
        """POST /v1/theses/appeal — appeals a moderation decision in the user's name
        (an ``appealable`` notification, within 30 days; message 10-1000 characters).
        """
        _required(csid_id, "csid_id")
        _required(notification_id, "notification_id")
        _required(message, "message")
        return self._post(
            "/theses/appeal", {"csid_id": csid_id, "notification_id": notification_id, "message": message}
        )

    def delete_thesis(self, *, thesis_id: str, csid_id: str) -> Any:
        """POST /v1/theses/delete — deletes the user's own thesis or reply."""
        _required(thesis_id, "thesis_id")
        _required(csid_id, "csid_id")
        return self._post("/theses/delete", {"thesis_id": thesis_id, "csid_id": csid_id})

    # ── Trade Feed ───────────────────────────────────────────────────────
    # In the name of one of your users (csid_id, the "sub" of their ID token):
    # they must have signed in to an app of your instance with the scope
    # "trade_feed", else PermissionError "consent_required".

    def trade_feed(
        self,
        csid_id: str,
        *,
        filter: TradeFeedFilter | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/trade-feed — the user's Trade Feed: trades (labelled new / add /
        partial / close / sell, with the realized PnL of sells) and theses of the
        traders in it, newest first.

        ``filter``: all (default), buys, sells, theses; ``limit`` 1-100 (default 30).
        Returns a list of :data:`~cabalspy_id.TradeFeedItem`.
        """
        return self._get("/trade-feed", _trade_feed_query(csid_id, filter, limit, cursor))

    def trade_feed_traders(self, csid_id: str, *, limit: int | None = None, cursor: str | None = None) -> Any:
        """GET /v1/trade-feed/traders — the traders in the user's Trade Feed with their
        settings, newest first. ``limit`` 1-300 (default 100); the envelope's
        pagination (``get_raw``) carries ``total`` and ``max``.

        Returns a list of :class:`~cabalspy_id.TradeFeedEntry`.
        """
        return self._get("/trade-feed/traders", _trade_feed_page(csid_id, limit, cursor))

    def add_to_trade_feed(
        self,
        csid_id: str,
        trader: str,
        *,
        notify_buys: bool | None = None,
        notify_sells: bool | None = None,
        notify_theses: bool | None = None,
        min_sol: float | None = None,
        min_bnb: float | None = None,
        min_eth: float | None = None,
        muted: bool | None = None,
    ) -> Any:
        """POST /v1/trade-feed/traders — adds a trader (handle with or without @, or
        csid_id) to the user's Trade Feed; for a trader already there, updates the
        given settings. ``created`` tells which (HTTP 201 / 200). Omitted settings
        keep their value; a new trader starts with the person's defaults.

        Errors: trader_not_found (NotFoundError), cannot_add_self (BadRequestError),
        trading_private and consent_required (PermissionError), trade_feed_full
        (409, CabalSpyIDError), rate_limited (RateLimitError).
        Returns :class:`~cabalspy_id.TradeFeedAddResult`.
        """
        _required(csid_id, "csid_id")
        _required(trader, "trader")
        settings = {
            "notify_buys": notify_buys,
            "notify_sells": notify_sells,
            "notify_theses": notify_theses,
            "min_sol": min_sol,
            "min_bnb": min_bnb,
            "min_eth": min_eth,
            "muted": muted,
        }
        body = {k: v for k, v in settings.items() if v is not None}
        return self._post("/trade-feed/traders", {**body, "csid_id": csid_id, "trader": trader})

    def remove_from_trade_feed(self, csid_id: str, trader: str) -> Any:
        """POST /v1/trade-feed/traders/delete — removes a trader; ``removed`` is False
        when they were not there. Returns :class:`~cabalspy_id.TradeFeedRemoveResult`.
        """
        _required(csid_id, "csid_id")
        _required(trader, "trader")
        return self._post("/trade-feed/traders/delete", {"csid_id": csid_id, "trader": trader})

    def trade_feed_notifications(self, csid_id: str, *, limit: int | None = None, cursor: str | None = None) -> Any:
        """GET /v1/trade-feed/notifications — the user's recent Trade Feed events (the
        ones that passed their filters), newest first; for platforms without webhooks.
        ``limit`` 1-100 (default 50).

        Returns a list of :class:`~cabalspy_id.TradeFeedNotification`.
        """
        return self._get("/trade-feed/notifications", _trade_feed_page(csid_id, limit, cursor))


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
        theses_stream_url: str | None = None,
        trade_feed_stream_url: str | None = None,
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
        self.theses_stream_url = (theses_stream_url or DEFAULT_THESES_STREAM_URL).rstrip("/")
        self.trade_feed_stream_url = (trade_feed_stream_url or DEFAULT_TRADE_FEED_STREAM_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._extra_headers = dict(headers or {})
        #: Rate limit state from the most recent request.
        self.last_rate_limit = RateLimit()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, instance={self.instance!r})"

    # ── plumbing shared by both clients ──────────────────────────────────

    def _prepare(
        self, path: str, params: Mapping[str, Any] | None, auth: bool, json_body: bool = False
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
        if json_body:
            headers["Content-Type"] = "application/json"
        headers.update(self._extra_headers)
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        return url, query, headers

    def _interpret(self, response: httpx.Response, path: str, method: str = "GET") -> Envelope:
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
                f"HTTP {response.status_code} on {method} {path}",
            )
        if not isinstance(parsed, dict) or "data" not in parsed:
            raise InvalidResponseError(
                f"Unexpected response shape on {method} {path}: no data field",
                status=response.status_code,
                code="invalid_response",
                rate_limit=rate_limit,
            )
        return Envelope(
            parsed["data"], parsed.get("pagination"), parsed.get("meta") or {}, rate_limit, response.status_code
        )

    def _connection_error(self, exc: Exception, path: str, method: str = "GET") -> APIConnectionError:
        if isinstance(exc, httpx.TimeoutException):
            return APIConnectionError(f"Request timed out after {self.timeout}s: {method} {path}", code="timeout")
        return APIConnectionError(f"Network error: {exc}", code="connection_error")

    def stream(
        self,
        *,
        events: Sequence[StreamTopic] | None = None,
        blockchain: Chain | None = None,
        mint: str | None = None,
        scope: Scope | None = None,
        **kwargs: Any,
    ) -> CabalSpyIDStream:
        """Live trades of your users and/or live theses over WebSocket (Pro plan and up). Async only.

        ``events``: ``["trades"]`` (default), ``["theses"]`` or both; ``mint``
        limits theses to one token (needs ``blockchain``).

        Needs the ``stream`` extra: ``pip install "cabalspy-id[stream]"``.
        """
        if not self._api_key:
            raise AuthenticationError("The stream needs an API key.", status=401, code="missing_api_key")
        from ._stream import CabalSpyIDStream

        return CabalSpyIDStream(
            self.stream_url,
            self._api_key,
            events=events,
            blockchain=blockchain,
            mint=mint,
            scope=scope,
            instance=self.instance,
            **kwargs,
        )

    def theses_stream(self, *, scope: ThesisScope | None = None, **kwargs: Any) -> ThesesStream:
        """Live theses for the tokens you subscribe to (every plan). Async only.

        Needs the ``stream`` extra: ``pip install "cabalspy-id[stream]"``.
        """
        if not self._api_key:
            raise AuthenticationError("The theses stream needs an API key.", status=401, code="missing_api_key")
        from ._theses_stream import ThesesStream

        return ThesesStream(self.theses_stream_url, self._api_key, scope=scope, instance=self.instance, **kwargs)

    def trade_feed_stream(self, **kwargs: Any) -> TradeFeedStream:
        """Live Trade Feed events of your users (every plan): ``trade_feed.trade`` and
        ``trade_feed.thesis`` with ``data["recipients"]``, like the webhooks. Async only.

        Needs the ``stream`` extra: ``pip install "cabalspy-id[stream]"``.
        """
        if not self._api_key:
            raise AuthenticationError("The Trade Feed stream needs an API key.", status=401, code="missing_api_key")
        from ._trade_feed_stream import TradeFeedStream

        return TradeFeedStream(self.trade_feed_stream_url, self._api_key, instance=self.instance, **kwargs)


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

    def post_raw(self, path: str, body: Mapping[str, Any]) -> Envelope:
        """Any POST with a JSON body, returning the full envelope.

        Not retried after a server or network error (the write may have happened);
        only the API's own rate limit (429 rate_limit_exceeded) is retried.
        """
        url, query, headers = self._prepare(path, None, True, json_body=True)
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(_backoff(attempt, last))
            try:
                response = self._http.post(url, params=query, headers=headers, json=dict(body))
            except httpx.HTTPError as exc:
                raise self._connection_error(exc, path, "POST") from exc
            try:
                return self._interpret(response, path, "POST")
            except CabalSpyIDError as exc:
                if _post_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: POST {path}")

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self.post_raw(path, body).data

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

    def iter_theses(
        self,
        *,
        blockchain: Chain,
        mint: str,
        sort: ThesisSort | None = None,
        stance: ThesisStance | None = None,
        limit: int | None = None,
        csid_id: str | None = None,
        scope: ThesisScope | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every thesis on a token, following ``next_cursor``."""
        query = _theses_query(blockchain, mint, sort, stance, limit, None, csid_id, scope)
        for page in self.pages("/theses", query):
            yield from page.data

    def iter_thesis_replies(
        self, id: str, *, limit: int | None = None, csid_id: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every reply of a thesis, following ``next_cursor``."""
        _required(id, "id")
        for page in self.pages("/theses/replies", {"id": id, "limit": limit, "csid_id": csid_id}):
            yield from page.data

    def iter_trade_feed(
        self, csid_id: str, *, filter: TradeFeedFilter | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """The whole Trade Feed of a user, newest first, following ``next_cursor``."""
        for page in self.pages("/trade-feed", _trade_feed_query(csid_id, filter, limit, None)):
            yield from page.data

    def iter_trade_feed_traders(self, csid_id: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Every trader in the user's Trade Feed."""
        for page in self.pages("/trade-feed/traders", _trade_feed_page(csid_id, limit, None)):
            yield from page.data

    def iter_trade_feed_notifications(self, csid_id: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """The user's Trade Feed notifications, newest first."""
        for page in self.pages("/trade-feed/notifications", _trade_feed_page(csid_id, limit, None)):
            yield from page.data


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

    async def post_raw(self, path: str, body: Mapping[str, Any]) -> Envelope:
        """Async version of :meth:`CabalSpyID.post_raw`."""
        url, query, headers = self._prepare(path, None, True, json_body=True)
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(_backoff(attempt, last))
            try:
                response = await self._http.post(url, params=query, headers=headers, json=dict(body))
            except httpx.HTTPError as exc:
                raise self._connection_error(exc, path, "POST") from exc
            try:
                return self._interpret(response, path, "POST")
            except CabalSpyIDError as exc:
                if _post_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: POST {path}")

    async def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        return (await self.post_raw(path, body)).data

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

    async def iter_theses(
        self,
        *,
        blockchain: Chain,
        mint: str,
        sort: ThesisSort | None = None,
        stance: ThesisStance | None = None,
        limit: int | None = None,
        csid_id: str | None = None,
        scope: ThesisScope | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Every thesis on a token, following ``next_cursor``."""
        query = _theses_query(blockchain, mint, sort, stance, limit, None, csid_id, scope)
        async for page in self.pages("/theses", query):
            for item in page.data:
                yield item

    async def iter_thesis_replies(
        self, id: str, *, limit: int | None = None, csid_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Every reply of a thesis, following ``next_cursor``."""
        _required(id, "id")
        async for page in self.pages("/theses/replies", {"id": id, "limit": limit, "csid_id": csid_id}):
            for item in page.data:
                yield item

    async def iter_trade_feed(
        self, csid_id: str, *, filter: TradeFeedFilter | None = None, limit: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """The whole Trade Feed of a user, newest first, following ``next_cursor``."""
        async for page in self.pages("/trade-feed", _trade_feed_query(csid_id, filter, limit, None)):
            for item in page.data:
                yield item

    async def iter_trade_feed_traders(self, csid_id: str, *, limit: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Every trader in the user's Trade Feed."""
        async for page in self.pages("/trade-feed/traders", _trade_feed_page(csid_id, limit, None)):
            for item in page.data:
                yield item

    async def iter_trade_feed_notifications(
        self, csid_id: str, *, limit: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """The user's Trade Feed notifications, newest first."""
        async for page in self.pages("/trade-feed/notifications", _trade_feed_page(csid_id, limit, None)):
            for item in page.data:
                yield item


def _users_query(params: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"limit", "kol", "cursor", "scope"}
    unknown = set(params) - allowed
    if unknown:
        raise TypeError(f"unexpected parameter(s): {', '.join(sorted(unknown))}")
    _one_of(params.get("scope"), SCOPES, "scope")
    return {**params, "kol": "true" if params.get("kol") else None}
