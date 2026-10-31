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
import json
import os
import random
import time
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, TypeVar

import httpx

from ._constants import (
    CALLOUT_COMPETITION_METRICS,
    CALLOUT_MAX_NOTE,
    CALLOUT_SORTS,
    CALLOUT_WHO,
    CHAINS,
    COMPETITION_ENROLLMENTS,
    COMPETITION_KINDS,
    COMPETITION_METRICS,
    COMPETITION_STATUSES,
    DATA_SCOPES,
    DEFAULT_BASE_URL,
    DEFAULT_CALLOUTS_STREAM_URL,
    DEFAULT_STREAM_URL,
    DEFAULT_THESES_STREAM_URL,
    LEADERBOARD_SORTS,
    PERIODS,
    PLATFORM_IMPORT_MAX,
    PLATFORM_MAX_WALLETS_PER_REQUEST,
    SCOPES,
    THESIS_EMOJIS,
    THESIS_REPORT_REASONS,
    THESIS_SCOPES,
    USER_AGENT,
    WALLET_TRUST,
    CalloutSort,
    CalloutWho,
    Chain,
    CompetitionChain,
    CompetitionEnrollment,
    CompetitionKind,
    CompetitionMetric,
    CompetitionStatus,
    DataScope,
    LeaderboardSort,
    LeaderboardTrust,
    Period,
    Scope,
    StreamTopic,
    ThesisEmoji,
    ThesisReportReason,
    ThesisScope,
    ThesisSort,
    ThesisStance,
    WalletTrust,
)
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    CabalSpyIDError,
    InvalidResponseError,
    PlatformImportError,
    RateLimit,
    RateLimitError,
    error_from_status,
    is_retryable,
)
from ._types import PlatformBulkImportResult, PlatformUserInput, PlatformWalletInput

if TYPE_CHECKING:
    from ._callouts_stream import CalloutsStream
    from ._stream import CabalSpyIDStream
    from ._theses_stream import ThesesStream

_T = TypeVar("_T")

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


def _post_retryable(exc: CabalSpyIDError) -> bool:
    """Writes are retried only when the API's rate limit refused them before they ran."""
    return isinstance(exc, RateLimitError) and exc.code == "rate_limit_exceeded"


def _page_pagination(page: Envelope) -> dict[str, Any] | None:
    """Envelope-level pagination, or the leaderboard's inside ``data``."""
    inner = page.data.get("pagination") if isinstance(page.data, dict) else None
    return page.pagination or inner


# ── white-label helpers ──────────────────────────────────────────────────────


class _NotGiven:
    """Sentinel for "not passed", where ``None`` means "clear the value"."""

    def __repr__(self) -> str:
        return "NOT_GIVEN"

    def __bool__(self) -> bool:
        return False


NOT_GIVEN: Any = _NotGiven()

_IMPORT_PATH = "/platform-users/import"
#: Bulk imports keep each request body below this (the server takes up to 1 MB).
_IMPORT_BODY_BYTES = 900_000


def _given(**fields: Any) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if not isinstance(v, _NotGiven)}


def _who(external_id: str | None, csid_id: str | None) -> dict[str, Any]:
    """The user of a platform-users call: exactly one of external_id, csid_id."""
    if bool(external_id) == bool(csid_id):
        raise BadRequestError(
            "Pass exactly one of: external_id, csid_id.", code="missing_parameter", parameter="external_id|csid_id"
        )
    return {"external_id": external_id} if external_id else {"csid_id": csid_id}


def _wallet_items(wallets: Any, *, required: bool = True) -> list[Any]:
    if isinstance(wallets, (str, Mapping)):
        raise BadRequestError("wallets must be a list of wallets.", code="invalid_parameter", parameter="wallets")
    items = [w if isinstance(w, str) else dict(w) for w in wallets]
    if required and not items:
        raise BadRequestError(
            'Pass at least one wallet: wallets=[{"address": "..."}].', code="wallet_required", parameter="wallets"
        )
    if len(items) > PLATFORM_MAX_WALLETS_PER_REQUEST:
        raise BadRequestError(
            f"At most {PLATFORM_MAX_WALLETS_PER_REQUEST} wallets per request.",
            code="invalid_parameter",
            parameter="wallets",
        )
    return items


def _platform_leaderboard_query(
    blockchain: Any, period: Any, sort: Any, trust: Any, limit: Any, cursor: Any
) -> dict[str, Any]:
    _required(blockchain, "blockchain")
    _one_of(blockchain, CHAINS, "blockchain")
    _one_of(period, PERIODS, "period")
    _one_of(sort, LEADERBOARD_SORTS, "sort")
    _one_of(trust, ("all", "verified"), "trust")
    return {"blockchain": blockchain, "period": period, "sort": sort, "trust": trust, "limit": limit, "cursor": cursor}


_TRADING_ONLY = ("min_trades", "min_volume_usd")
_CALLOUTS_ONLY = ("min_callouts", "hit_x")


def _competition_fields(*, creating: bool, **fields: Any) -> dict[str, Any]:
    """Validated competition fields. On create the kind is known (default trading) and
    decides the chains, metrics and minimums; on update the server knows the kind."""
    out = _given(**fields)
    _one_of(out.get("kind"), COMPETITION_KINDS, "kind")
    kind = (out.get("kind") or "trading") if creating else None
    chains: tuple[str, ...] = (*CHAINS, "all") if kind in ("callouts", None) else CHAINS
    if kind == "callouts":
        metrics: tuple[str, ...] = CALLOUT_COMPETITION_METRICS
    elif kind == "trading":
        metrics = COMPETITION_METRICS
    else:
        metrics = (*COMPETITION_METRICS, *CALLOUT_COMPETITION_METRICS)
    _one_of(out.get("chain"), chains, "chain")
    _one_of(out.get("metric"), metrics, "metric")
    _one_of(out.get("wallet_trust"), WALLET_TRUST, "wallet_trust")
    _one_of(out.get("enrollment"), COMPETITION_ENROLLMENTS, "enrollment")
    wrong = _CALLOUTS_ONLY if kind == "trading" else _TRADING_ONLY if kind == "callouts" else ()
    for name in wrong:
        if name in out:
            raise BadRequestError(
                f"{name} does not apply to {kind} competitions.", code="invalid_parameter", parameter=name
            )
    if "hit_x" in out:
        _hit_x(out["hit_x"])
    if isinstance(out.get("starts_at"), datetime):
        out["starts_at"] = out["starts_at"].isoformat()
    return out


def _hit_x(value: Any) -> None:
    """hit_x: a number above 1 and at most 1000 (None = the server's default, 2)."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 < value <= 1000:
        raise BadRequestError(
            "hit_x must be a number above 1 and at most 1000.", code="invalid_parameter", parameter="hit_x"
        )


def _time_param(value: str | datetime | None) -> str | None:
    """A datetime as ISO 8601 UTC (naive = UTC, like the server); strings pass through."""
    if not isinstance(value, datetime):
        return value
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _callouts_query(
    chain: Any, mint: Any, external_id: Any, csid_id: Any, since: Any, until: Any, limit: Any, cursor: Any
) -> dict[str, Any]:
    _one_of(chain, CHAINS, "chain")
    if mint and not chain:
        raise BadRequestError("Pass chain together with mint.", code="missing_parameter", parameter="chain")
    if external_id and csid_id:
        raise BadRequestError(
            "Pass at most one of: external_id, csid_id.", code="invalid_parameter", parameter="external_id|csid_id"
        )
    return {
        "chain": chain,
        "mint": mint,
        "external_id": external_id,
        "csid_id": csid_id,
        "since": _time_param(since),
        "until": _time_param(until),
        "limit": limit,
        "cursor": cursor,
    }


def _callout_leaderboard_query(
    period: Any, chain: Any, sort: Any, min_callouts: Any, hit_x: Any, limit: Any, cursor: Any
) -> dict[str, Any]:
    _one_of(period, PERIODS, "period")
    _one_of(chain, CHAINS, "chain")
    _one_of(sort, CALLOUT_SORTS, "sort")
    if min_callouts is not None and (
        isinstance(min_callouts, bool) or not isinstance(min_callouts, int) or not 1 <= min_callouts <= 1000
    ):
        raise BadRequestError(
            "min_callouts must be a whole number from 1 to 1000.", code="invalid_parameter", parameter="min_callouts"
        )
    _hit_x(hit_x)
    return {
        "period": period,
        "chain": chain,
        "sort": sort,
        "min_callouts": min_callouts,
        "hit_x": hit_x,
        "limit": limit,
        "cursor": cursor,
    }


def _import_items(users: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(users, (str, Mapping)):
        raise BadRequestError("users must be a list of users.", code="invalid_parameter", parameter="users")
    return [dict(u) for u in users]


def _import_wait() -> float:
    """Seconds until the server's per-minute window for new users resets (UTC minutes), plus 1."""
    return 61.0 - time.time() % 60.0


class _ImportRun:
    """State of one bulk import: the users, their chunks and the results so far."""

    def __init__(self, users: Iterable[Mapping[str, Any]], chunk_size: int, max_body_bytes: int, attempts: int):
        if not 1 <= chunk_size <= PLATFORM_IMPORT_MAX:
            raise ValueError(f"chunk_size must be 1-{PLATFORM_IMPORT_MAX}")
        if attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.items = _import_items(users)
        self.results: list[dict[str, Any] | None] = [None] * len(self.items)
        self.requests = 0
        self.chunks: list[list[int]] = []
        current: list[int] = []
        size = len('{"users": []}')
        for i, item in enumerate(self.items):
            # json.dumps' defaults (ASCII escapes, spaced separators) never encode smaller than httpx
            n = len(json.dumps(item).encode()) + 2
            if current and (len(current) >= chunk_size or size + n > max_body_bytes):
                self.chunks.append(current)
                current, size = [], len('{"users": []}')
            current.append(i)
            size += n
        if current:
            self.chunks.append(current)

    def body(self, pending: list[int]) -> dict[str, Any]:
        self.requests += 1
        return {"users": [self.items[i] for i in pending]}

    def record(self, sent: list[int], data: Any) -> list[int]:
        """Stores the results of one call; returns the users rejected with rate_limited."""
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or len(results) != len(sent):
            raise InvalidResponseError(
                f"Unexpected import response: {len(sent)} users sent, results do not match",
                code="invalid_response",
            )
        retry: list[int] = []
        for index, res in zip(sent, results, strict=True):
            self.results[index] = res
            error = res.get("error") if isinstance(res, dict) else None
            if isinstance(error, dict) and error.get("code") == "rate_limited":
                retry.append(index)
        return retry

    def result(self, skip: Iterable[int] = ()) -> dict[str, Any]:
        skipped = set(skip)
        results = [r for i, r in enumerate(self.results) if r is not None and i not in skipped]
        summary = {"created": 0, "updated": 0, "unchanged": 0, "rejected": 0}
        for r in results:
            status = r.get("status")
            if status in summary:
                summary[status] += 1
        return {"summary": summary, "results": results, "requests": self.requests}

    def failed(self, exc: CabalSpyIDError, chunk_no: int, pending: list[int]) -> PlatformImportError:
        left = pending + [i for chunk in self.chunks[chunk_no + 1 :] for i in chunk]
        return PlatformImportError(
            f"Import stopped, {len(left)} of {len(self.items)} users not imported: {exc}",
            result=self.result(left),
            remaining=[self.items[i] for i in left],
            status=exc.status,
            code=exc.code,
            request_id=exc.request_id,
            docs=exc.docs,
            parameter=exc.parameter,
            allowed=exc.allowed,
            rate_limit=exc.rate_limit,
            body=exc.body,
        )


# ═══════════════════════════════════════════════════════════════════════════
#  ENDPOINTS  (shared between the sync and async clients)
# ═══════════════════════════════════════════════════════════════════════════


class _Endpoints:
    def _get(self, path: str, params: Mapping[str, Any] | None = None, *, auth: bool = True) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _get_text(self, path: str, params: Mapping[str, Any] | None = None) -> Any:  # pragma: no cover
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

    # ── white-label: platform users ──────────────────────────────────────
    # Your platform keeps its own login and addresses its users by its own user
    # id (``external_id``). Every method that takes a user accepts either
    # ``external_id`` (positional) or ``csid_id=`` — exactly one.

    def upsert_platform_user(
        self,
        external_id: str,
        *,
        wallets: Sequence[PlatformWalletInput | str] | None = None,
        display_name: str | _NotGiven | None = NOT_GIVEN,
        avatar_url: str | _NotGiven | None = NOT_GIVEN,
    ) -> Any:
        """POST /v1/platform-users — creates the user or updates an existing one.

        A new user needs 1-10 ``wallets`` (objects or plain addresses) and a free
        place in your plan (else :class:`~cabalspy_id.PlanUserLimitError`). For an
        existing user, wallets are added and the profile fields you pass are set
        (``None`` clears them). Returns :class:`~cabalspy_id.PlatformUserUpsert`
        (``created`` says which happened).
        """
        _required(external_id, "external_id")
        body: dict[str, Any] = {"external_id": external_id}
        if wallets is not None:
            body["wallets"] = _wallet_items(wallets, required=False)
        body.update(_given(display_name=display_name, avatar_url=avatar_url))
        return self._post("/platform-users", body)

    def import_platform_users(self, users: Iterable[PlatformUserInput]) -> Any:
        """POST /v1/platform-users/import — creates or updates up to 1,000 users in one call.

        Each user is handled on its own: a bad item or the plan limit never undoes
        the others. Returns :class:`~cabalspy_id.PlatformImportResult` (one result
        per user, in order). For more users, or automatic retries, use
        ``bulk_import_platform_users``.
        """
        items = _import_items(users)
        if not items:
            raise BadRequestError("Pass at least one user.", code="missing_parameter", parameter="users")
        if len(items) > PLATFORM_IMPORT_MAX:
            raise BadRequestError(
                f"At most {PLATFORM_IMPORT_MAX} users per import call; use bulk_import_platform_users().",
                code="invalid_parameter",
                parameter="users",
            )
        return self._post(_IMPORT_PATH, {"users": items})

    def platform_user(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """GET /v1/platform-users — one of your users. Returns :class:`~cabalspy_id.PlatformUser`."""
        return self._get("/platform-users", _who(external_id, csid_id))

    def update_platform_user(
        self,
        external_id: str | None = None,
        *,
        csid_id: str | None = None,
        display_name: str | _NotGiven | None = NOT_GIVEN,
        avatar_url: str | _NotGiven | None = NOT_GIVEN,
    ) -> Any:
        """POST /v1/platform-users/update — sets ``display_name`` and/or ``avatar_url`` (``None`` clears).

        Returns :class:`~cabalspy_id.PlatformUser`.
        """
        fields = _given(display_name=display_name, avatar_url=avatar_url)
        if not fields:
            raise BadRequestError(
                "Pass display_name and/or avatar_url.", code="missing_parameter", parameter="display_name"
            )
        return self._post("/platform-users/update", {**_who(external_id, csid_id), **fields})

    def platform_users(self, *, limit: int | None = None, cursor: str | None = None) -> Any:
        """GET /v1/platform-users/list — your users, newest first (``limit`` 1-100, default 50).

        Returns a list of :class:`~cabalspy_id.PlatformUser`; see ``iter_platform_users``.
        """
        return self._get("/platform-users/list", {"limit": limit, "cursor": cursor})

    def delete_platform_user(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/delete — deletes the user and their data.

        A claimed user keeps their CabalSpy ID: only the link to your platform goes
        (``deleted`` False, ``unlinked`` True). Returns :class:`~cabalspy_id.PlatformUserDeleted`.
        """
        return self._post("/platform-users/delete", _who(external_id, csid_id))

    def add_platform_user_wallets(
        self,
        external_id: str | None = None,
        *,
        wallets: Sequence[PlatformWalletInput | str],
        csid_id: str | None = None,
    ) -> Any:
        """POST /v1/platform-users/wallets/add — adds 1-10 existing wallets (no payment verification).

        Returns :class:`~cabalspy_id.PlatformWalletsResponse`.
        """
        return self._post(
            "/platform-users/wallets/add", {**_who(external_id, csid_id), "wallets": _wallet_items(wallets)}
        )

    def delete_platform_user_wallet(
        self, external_id: str | None = None, *, address: str, csid_id: str | None = None
    ) -> Any:
        """POST /v1/platform-users/wallets/delete — removes a wallet. The last one cannot go
        (:class:`~cabalspy_id.ConflictError` ``last_wallet``). Returns :class:`~cabalspy_id.PlatformWalletRemoved`.
        """
        _required(address, "address")
        return self._post("/platform-users/wallets/delete", {**_who(external_id, csid_id), "address": address})

    def start_wallet_verification(
        self, external_id: str | None = None, *, chain: Chain, address: str, csid_id: str | None = None
    ) -> Any:
        """POST /v1/platform-users/wallets/verify — starts the payment verification of a wallet.

        The user sends the exact ``amount`` from that wallet to ``receiver`` before
        ``expires_at`` (``payment_uri`` for wallets and QR codes). Returns
        :class:`~cabalspy_id.PlatformWalletVerification`.
        """
        _required(chain, "chain")
        _one_of(chain, CHAINS, "chain")
        _required(address, "address")
        return self._post(
            "/platform-users/wallets/verify", {**_who(external_id, csid_id), "chain": chain, "address": address}
        )

    def wallet_verification(self, id: str) -> Any:
        """GET /v1/platform-users/wallets/verification — status of a verification
        (pending, verified, cancelled, expired). Returns :class:`~cabalspy_id.PlatformWalletVerification`.
        """
        _required(id, "id")
        return self._get("/platform-users/wallets/verification", {"id": id})

    def wallet_verification_qr(self, id: str) -> Any:
        """GET /v1/platform-users/wallets/verification/qr — the payment URI as a QR code (SVG text)."""
        _required(id, "id")
        return self._get_text("/platform-users/wallets/verification/qr", {"id": id})

    def cancel_wallet_verification(self, id: str) -> Any:
        """POST /v1/platform-users/wallets/verification/cancel.

        Returns :class:`~cabalspy_id.PlatformWalletVerification`.
        """
        _required(id, "id")
        return self._post("/platform-users/wallets/verification/cancel", {"id": id})

    def platform_user_profile(
        self, external_id: str | None = None, *, csid_id: str | None = None, period: Period | None = None
    ) -> Any:
        """GET /v1/platform-users/profile — everything for a profile page in one call: the user,
        trading per chain (default period 7d), recent trades, theses, Trade Feed and KOL status.

        Returns :class:`~cabalspy_id.PlatformUserProfile`.
        """
        _one_of(period, PERIODS, "period")
        return self._get("/platform-users/profile", {**_who(external_id, csid_id), "period": period})

    def platform_leaderboard(
        self,
        *,
        blockchain: Chain,
        period: Period | None = None,
        sort: LeaderboardSort | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        trust: LeaderboardTrust | None = None,
    ) -> Any:
        """GET /v1/platform-users/leaderboard — your platform users ranked (default 7d, pnl_usd;
        ``limit`` 1-500, default 100), each entry with ``external_id`` and ``verified``.

        ``trust="verified"`` ranks only payment-verified wallets; it can only narrow the
        instance's ``leaderboard_trust``. Returns :class:`~cabalspy_id.PlatformLeaderboardResponse`;
        see ``iter_platform_leaderboard``.
        """
        return self._get(
            "/platform-users/leaderboard", _platform_leaderboard_query(blockchain, period, sort, trust, limit, cursor)
        )

    def platform_settings(self) -> Any:
        """GET /v1/platform-users/settings. Returns :class:`~cabalspy_id.PlatformSettings`."""
        return self._get("/platform-users/settings")

    def update_platform_settings(
        self,
        *,
        white_label: bool | None = None,
        data_scope: DataScope | None = None,
        wallet_trust: WalletTrust | None = None,
        leaderboard_trust: WalletTrust | None = None,
        claim_links: bool | None = None,
        telegram_alerts: bool | None = None,
    ) -> Any:
        """POST /v1/platform-users/settings — changes the settings you pass (None = unchanged).

        ``data_scope``: ``csid`` (part of the CabalSpy ID network) or ``platform`` (only you
        see your users). ``wallet_trust`` / ``leaderboard_trust``: ``all`` or ``verified_only``.
        Returns :class:`~cabalspy_id.PlatformSettings`.
        """
        _one_of(data_scope, DATA_SCOPES, "data_scope")
        _one_of(wallet_trust, WALLET_TRUST, "wallet_trust")
        _one_of(leaderboard_trust, WALLET_TRUST, "leaderboard_trust")
        changes = {
            k: v
            for k, v in {
                "white_label": white_label,
                "data_scope": data_scope,
                "wallet_trust": wallet_trust,
                "leaderboard_trust": leaderboard_trust,
                "claim_links": claim_links,
                "telegram_alerts": telegram_alerts,
            }.items()
            if v is not None
        }
        if not changes:
            raise BadRequestError("Pass at least one setting.", code="missing_parameter", parameter="settings")
        return self._post("/platform-users/settings", changes)

    def platform_inbound(self) -> Any:
        """GET /v1/platform-users/inbound — whether the inbound URL is on, its last event and
        the payload formats it understands. Returns :class:`~cabalspy_id.PlatformInboundStatus`.
        """
        return self._get("/platform-users/inbound")

    def enable_platform_inbound(self) -> Any:
        """POST /v1/platform-users/inbound/enable — a new secret inbound URL for sign-up events
        from your platform or its auth provider (Privy, Dynamic, ...). Shown once; calling
        again replaces it. Returns :class:`~cabalspy_id.PlatformInboundEnabled`.
        """
        return self._post("/platform-users/inbound/enable", {})

    def disable_platform_inbound(self) -> Any:
        """POST /v1/platform-users/inbound/disable. Returns ``{"enabled": False}``."""
        return self._post("/platform-users/inbound/disable", {})

    def platform_user_session(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/session — a 15-minute token for the embeddable verify widget.

        Returns :class:`~cabalspy_id.PlatformSession`.
        """
        return self._post("/platform-users/session", _who(external_id, csid_id))

    def platform_user_claim_link(
        self, external_id: str | None = None, *, return_url: str | None = None, csid_id: str | None = None
    ) -> Any:
        """POST /v1/platform-users/claim-link — a 24-hour link that lets the person take the account
        into their own CabalSpy ID. ``return_url`` must be on your verified domains or registered
        origins. Off with ``white_label`` unless ``claim_links`` is on (``claim_disabled``).

        Returns :class:`~cabalspy_id.PlatformClaimLink`.
        """
        body = _who(external_id, csid_id)
        if return_url:
            body["return_url"] = return_url
        return self._post("/platform-users/claim-link", body)

    def connect_platform_user_x(
        self, external_id: str | None = None, *, return_url: str, csid_id: str | None = None
    ) -> Any:
        """POST /v1/platform-users/x/connect — a 10-minute ``authorize_url`` that connects the
        user's X account, then returns to ``return_url``. Returns :class:`~cabalspy_id.PlatformXConnect`.
        """
        _required(return_url, "return_url")
        return self._post("/platform-users/x/connect", {**_who(external_id, csid_id), "return_url": return_url})

    def disconnect_platform_user_x(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/x/disconnect. Not possible with the KOL badge (``kol_badge``).

        Returns :class:`~cabalspy_id.PlatformXDisconnect`.
        """
        return self._post("/platform-users/x/disconnect", _who(external_id, csid_id))

    def link_platform_user_telegram(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/telegram/link — a t.me ``deep_link`` that links the user's Telegram.

        Returns :class:`~cabalspy_id.PlatformTelegramLink`.
        """
        return self._post("/platform-users/telegram/link", _who(external_id, csid_id))

    def platform_user_telegram(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """GET /v1/platform-users/telegram. Returns :class:`~cabalspy_id.PlatformTelegramStatus`."""
        return self._get("/platform-users/telegram", _who(external_id, csid_id))

    def unlink_platform_user_telegram(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/telegram/unlink. Returns ``{"external_id", "linked": False}``."""
        return self._post("/platform-users/telegram/unlink", _who(external_id, csid_id))

    def platform_user_kol(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """GET /v1/platform-users/kol — badge, eligibility criteria, 7-day volume and application.

        Returns :class:`~cabalspy_id.PlatformKolStatus`.
        """
        return self._get("/platform-users/kol", _who(external_id, csid_id))

    def request_platform_user_volume_check(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/kol/volume-check — queues an on-chain volume check (202).

        Returns :class:`~cabalspy_id.PlatformKolVolumeCheck`.
        """
        return self._post("/platform-users/kol/volume-check", _who(external_id, csid_id))

    def apply_platform_user_kol(self, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/platform-users/kol/apply — applies for the KOL badge (needs X: ``x_required``;
        ``kol_not_eligible`` lists the criteria in ``body``). Returns :class:`~cabalspy_id.PlatformKolApply`.
        """
        return self._post("/platform-users/kol/apply", _who(external_id, csid_id))

    # ── trading competitions ─────────────────────────────────────────────
    # Between your platform users; at most 5 scheduled + running at a time per account.

    def create_competition(
        self,
        *,
        name: str,
        chain: CompetitionChain,
        metric: CompetitionMetric,
        duration_hours: float,
        kind: CompetitionKind | _NotGiven = NOT_GIVEN,
        starts_at: str | datetime | _NotGiven | None = NOT_GIVEN,
        min_participants: int | _NotGiven = NOT_GIVEN,
        max_participants: int | _NotGiven | None = NOT_GIVEN,
        min_trades: int | _NotGiven = NOT_GIVEN,
        min_volume_usd: float | _NotGiven = NOT_GIVEN,
        min_callouts: int | _NotGiven = NOT_GIVEN,
        hit_x: float | _NotGiven = NOT_GIVEN,
        wallet_trust: WalletTrust | _NotGiven = NOT_GIVEN,
        enrollment: CompetitionEnrollment | _NotGiven = NOT_GIVEN,
        late_join: bool | _NotGiven = NOT_GIVEN,
        prizes: Any = NOT_GIVEN,
        description: str | _NotGiven | None = NOT_GIVEN,
    ) -> Any:
        """POST /v1/competitions — a competition between your platform users.

        It starts at ``starts_at`` (or at once) once ``min_participants`` joined, then runs
        ``duration_hours`` (1-8760). ``enrollment="all_users"`` enters every platform user.

        ``kind="trading"`` (default): ranked on trades; traders below ``min_trades`` /
        ``min_volume_usd`` are listed but not ranked. ``kind="callouts"`` (needs the
        callouts extra, else ``feature_not_enabled``): ranked on the callouts made during
        the competition by ``avg_peak_x``, ``best_peak_x``, ``sum_peak_x``, ``hit_rate`` or
        ``callouts``; ``min_callouts`` to be ranked, ``hit_x`` the multiple that counts as
        a hit (default 2), ``chain="all"`` counts every chain. The kind cannot change later.
        Returns :class:`~cabalspy_id.CompetitionDetail`.
        """
        _required(name, "name")
        _required(chain, "chain")
        _required(metric, "metric")
        _required(duration_hours, "duration_hours")
        body = _competition_fields(
            creating=True,
            name=name,
            kind=kind,
            chain=chain,
            metric=metric,
            duration_hours=duration_hours,
            starts_at=starts_at,
            min_participants=min_participants,
            max_participants=max_participants,
            min_trades=min_trades,
            min_volume_usd=min_volume_usd,
            min_callouts=min_callouts,
            hit_x=hit_x,
            wallet_trust=wallet_trust,
            enrollment=enrollment,
            late_join=late_join,
            prizes=prizes,
            description=description,
        )
        return self._post("/competitions", body)

    def competitions(
        self, *, status: CompetitionStatus | None = None, limit: int | None = None, offset: int | None = None
    ) -> Any:
        """GET /v1/competitions — your competitions, newest first (``limit`` 1-500, default 50).

        Returns a list of :class:`~cabalspy_id.Competition`; see ``iter_competitions``.
        """
        _one_of(status, COMPETITION_STATUSES, "status")
        return self._get("/competitions", {"status": status, "limit": limit, "offset": offset})

    def competition(self, id: str) -> Any:
        """GET /v1/competitions/detail — one competition with every rule change.

        Returns :class:`~cabalspy_id.CompetitionDetail`.
        """
        _required(id, "id")
        return self._get("/competitions/detail", {"id": id})

    def update_competition(
        self,
        id: str,
        *,
        note: str | None = None,
        name: str | _NotGiven = NOT_GIVEN,
        chain: CompetitionChain | _NotGiven = NOT_GIVEN,
        metric: CompetitionMetric | _NotGiven = NOT_GIVEN,
        duration_hours: float | _NotGiven = NOT_GIVEN,
        starts_at: str | datetime | _NotGiven | None = NOT_GIVEN,
        min_participants: int | _NotGiven = NOT_GIVEN,
        max_participants: int | _NotGiven | None = NOT_GIVEN,
        min_trades: int | _NotGiven = NOT_GIVEN,
        min_volume_usd: float | _NotGiven = NOT_GIVEN,
        min_callouts: int | _NotGiven = NOT_GIVEN,
        hit_x: float | _NotGiven = NOT_GIVEN,
        wallet_trust: WalletTrust | _NotGiven = NOT_GIVEN,
        enrollment: CompetitionEnrollment | _NotGiven = NOT_GIVEN,
        late_join: bool | _NotGiven = NOT_GIVEN,
        prizes: Any = NOT_GIVEN,
        description: str | _NotGiven | None = NOT_GIVEN,
    ) -> Any:
        """POST /v1/competitions/update — changes any rule, at any time (also while running).

        Every change is recorded (``changes``, ``rules_version``) and sent as the webhook
        ``competition.updated``; ``note`` (max 500 characters) explains it. Pass ``None`` to
        clear ``starts_at``, ``max_participants``, ``prizes`` or ``description``.
        ``min_callouts`` / ``hit_x`` apply to callout competitions, ``min_trades`` /
        ``min_volume_usd`` to trading ones; the kind itself cannot change.
        Returns :class:`~cabalspy_id.CompetitionDetail`.
        """
        _required(id, "id")
        fields = _competition_fields(
            creating=False,
            name=name,
            chain=chain,
            metric=metric,
            duration_hours=duration_hours,
            starts_at=starts_at,
            min_participants=min_participants,
            max_participants=max_participants,
            min_trades=min_trades,
            min_volume_usd=min_volume_usd,
            min_callouts=min_callouts,
            hit_x=hit_x,
            wallet_trust=wallet_trust,
            enrollment=enrollment,
            late_join=late_join,
            prizes=prizes,
            description=description,
        )
        if not fields:
            raise BadRequestError("Pass at least one field to change.", code="missing_parameter", parameter="fields")
        body: dict[str, Any] = {"id": id, **fields}
        if note is not None:
            body["note"] = note
        return self._post("/competitions/update", body)

    def cancel_competition(self, id: str) -> Any:
        """POST /v1/competitions/cancel. Returns :class:`~cabalspy_id.CompetitionDetail`."""
        _required(id, "id")
        return self._post("/competitions/cancel", {"id": id})

    def join_competition(self, id: str, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/competitions/join — enters one of your users (``already`` True if they were in).

        Returns :class:`~cabalspy_id.CompetitionMembership`.
        """
        _required(id, "id")
        return self._post("/competitions/join", {"id": id, **_who(external_id, csid_id)})

    def leave_competition(self, id: str, external_id: str | None = None, *, csid_id: str | None = None) -> Any:
        """POST /v1/competitions/leave — removes one of your users (``left`` False if they were not in).

        Returns :class:`~cabalspy_id.CompetitionMembership`.
        """
        _required(id, "id")
        return self._post("/competitions/leave", {"id": id, **_who(external_id, csid_id)})

    def competition_participants(self, id: str, *, limit: int | None = None, offset: int | None = None) -> Any:
        """GET /v1/competitions/participants — in join order (``limit`` 1-1000, default 100).

        Returns a list of :class:`~cabalspy_id.CompetitionParticipant`.
        """
        _required(id, "id")
        return self._get("/competitions/participants", {"id": id, "limit": limit, "offset": offset})

    def competition_standings(self, id: str, *, limit: int | None = None, offset: int | None = None) -> Any:
        """GET /v1/competitions/standings — ranked traders first, then the unranked (below the
        minimums). Updated every 5 minutes; ``final`` once the competition ended.

        Returns :class:`~cabalspy_id.CompetitionStandings`.
        """
        _required(id, "id")
        return self._get("/competitions/standings", {"id": id, "limit": limit, "offset": offset})

    # ── callouts (an extra, switched on per instance on request) ─────────
    # A user calls a token; its price and market cap are stamped and tracked: every
    # minute for the first 24 hours (then the day is scored on candles), after that
    # every 5 minutes while the token is active. Tracking stops after 24 hours in a
    # row below a $10k market cap. Without the extra every call raises
    # PermissionError (feature_not_enabled); ``me()["features"]`` shows it.

    def create_callout(
        self,
        external_id: str | None = None,
        *,
        chain: Chain,
        mint: str,
        note: str | None = None,
        csid_id: str | None = None,
    ) -> Any:
        """POST /v1/callouts — one of your users calls a token (``note`` up to 280 characters).

        The instance's settings apply: ``kol_only`` (PermissionError), holders only
        (``not_a_holder``), one call per token and 24 hours (ConflictError ``already_called``)
        and the cooldown between two callouts (RateLimitError ``callout_cooldown`` with
        ``retry_after``; never retried automatically, the wait can be hours). A token without
        a market price raises BadRequestError ``no_price`` (422).
        Returns :class:`~cabalspy_id.Callout`.
        """
        who = _who(external_id, csid_id)
        _required(chain, "chain")
        _one_of(chain, CHAINS, "chain")
        _required(mint, "mint")
        if note is not None and len(note) > CALLOUT_MAX_NOTE:
            raise BadRequestError(
                f"note must be at most {CALLOUT_MAX_NOTE} characters.", code="invalid_parameter", parameter="note"
            )
        body: dict[str, Any] = {**who, "chain": chain, "mint": mint}
        if note:
            body["note"] = note
        return self._post("/callouts", body)

    def remove_callout(self, id: str, *, reason: str | None = None) -> Any:
        """POST /v1/callouts/remove — takes a callout down (moderation, ``reason`` up to 200
        characters); it leaves every list and statistic. Returns :class:`~cabalspy_id.CalloutRemoved`.
        """
        _required(id, "id")
        body: dict[str, Any] = {"id": id}
        if reason:
            body["reason"] = reason
        return self._post("/callouts/remove", body)

    def callouts(
        self,
        *,
        chain: Chain | None = None,
        mint: str | None = None,
        external_id: str | None = None,
        csid_id: str | None = None,
        since: str | datetime | None = None,
        until: str | datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/callouts — your instance's callouts, newest first (``limit`` 1-200, default 50),
        e.g. as chart markers. ``mint`` needs ``chain``; ``external_id`` / ``csid_id`` one user's;
        ``since`` / ``until`` bound ``called_at`` (datetimes or ISO 8601).

        Returns a list of :class:`~cabalspy_id.Callout`; see ``iter_callouts``.
        """
        return self._get("/callouts", _callouts_query(chain, mint, external_id, csid_id, since, until, limit, cursor))

    def callout(self, id: str) -> Any:
        """GET /v1/callouts/item — one callout. Returns :class:`~cabalspy_id.Callout`."""
        _required(id, "id")
        return self._get("/callouts/item", {"id": id})

    def callout_stats(
        self, external_id: str | None = None, *, csid_id: str | None = None, hit_x: float | None = None
    ) -> Any:
        """GET /v1/callouts/stats — one user's callouts per period (6h, 1d, 7d, 30d = callouts
        made in that period): count, average / median / best peak multiple, hit rate (percent
        reaching ``hit_x``, default 2) and the average multiple now.

        Returns :class:`~cabalspy_id.CalloutStats`.
        """
        who = _who(external_id, csid_id)
        _hit_x(hit_x)
        return self._get("/callouts/stats", {**who, "hit_x": hit_x})

    def callout_leaderboard(
        self,
        *,
        period: Period | None = None,
        chain: Chain | None = None,
        sort: CalloutSort | None = None,
        min_callouts: int | None = None,
        hit_x: float | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/callouts/leaderboard — your callers ranked (default 7d by ``avg_peak_x``;
        ``limit`` 1-500, default 100). ``min_callouts`` 1-1000 to be listed.

        Returns :class:`~cabalspy_id.CalloutLeaderboardResponse`; see ``iter_callout_leaderboard``.
        """
        return self._get(
            "/callouts/leaderboard",
            _callout_leaderboard_query(period, chain, sort, min_callouts, hit_x, limit, cursor),
        )

    def callout_settings(self) -> Any:
        """GET /v1/callouts/settings. Returns :class:`~cabalspy_id.CalloutSettings`."""
        return self._get("/callouts/settings")

    def update_callout_settings(
        self,
        *,
        who: CalloutWho | None = None,
        require_holding: bool | None = None,
        cooldown_minutes: int | None = None,
    ) -> Any:
        """POST /v1/callouts/settings — changes the settings you pass (None = unchanged).

        ``who``: ``all`` or ``kol_only``; ``require_holding``: holders only;
        ``cooldown_minutes``: 0-10080 between two callouts of one user.
        Returns :class:`~cabalspy_id.CalloutSettings`.
        """
        _one_of(who, CALLOUT_WHO, "who")
        if cooldown_minutes is not None and (
            isinstance(cooldown_minutes, bool)
            or not isinstance(cooldown_minutes, int)
            or not 0 <= cooldown_minutes <= 10080
        ):
            raise BadRequestError(
                "cooldown_minutes must be a whole number from 0 to 10080 (7 days).",
                code="invalid_parameter",
                parameter="cooldown_minutes",
            )
        changes = {
            k: v
            for k, v in {"who": who, "require_holding": require_holding, "cooldown_minutes": cooldown_minutes}.items()
            if v is not None
        }
        if not changes:
            raise BadRequestError("Pass at least one setting.", code="missing_parameter", parameter="settings")
        return self._post("/callouts/settings", changes)


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
        callouts_stream_url: str | None = None,
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
        self.callouts_stream_url = (callouts_stream_url or DEFAULT_CALLOUTS_STREAM_URL).rstrip("/")
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

    def _rate_limit(self, response: httpx.Response) -> RateLimit:
        self.last_rate_limit = RateLimit(
            _int_header(response.headers, "X-RateLimit-Limit"),
            _int_header(response.headers, "X-RateLimit-Remaining"),
            _int_header(response.headers, "X-RateLimit-Reset"),
        )
        return self.last_rate_limit

    def _interpret_text(self, response: httpx.Response, path: str) -> str:
        """The body of a non-JSON answer (an SVG), or raises the API's error."""
        if response.status_code >= 400:
            self._interpret(response, path)
        self._rate_limit(response)
        return response.text

    def _interpret(self, response: httpx.Response, path: str, method: str = "GET") -> Envelope:
        """Turns an HTTP response into an Envelope, or raises the right error."""
        rate_limit = self._rate_limit(response)
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

    def callouts_stream(self, *, chain: Chain | None = None, mint: str | None = None, **kwargs: Any) -> CalloutsStream:
        """Every callout event of your instance, live (callouts extra). Async only.

        ``chain`` / ``mint`` narrow it to one chain or token (``mint`` needs ``chain``).
        Needs the ``stream`` extra: ``pip install "cabalspy-id[stream]"``.
        """
        if not self._api_key:
            raise AuthenticationError("The callouts stream needs an API key.", status=401, code="missing_api_key")
        from ._callouts_stream import CalloutsStream

        return CalloutsStream(
            self.callouts_stream_url, self._api_key, chain=chain, mint=mint, instance=self.instance, **kwargs
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
        return self._send_get(path, params, auth, self._interpret)

    def get_text(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        """Any GET whose answer is not JSON (the verification QR code), as text."""
        return self._send_get(path, params, True, self._interpret_text)

    def _get_text(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.get_text(path, params)

    def _send_get(
        self, path: str, params: Mapping[str, Any] | None, auth: bool, parse: Callable[[httpx.Response, str], _T]
    ) -> _T:
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
                return parse(response, path)
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

    # ── white-label ──────────────────────────────────────────────────────

    def bulk_import_platform_users(
        self,
        users: Iterable[PlatformUserInput],
        *,
        chunk_size: int = PLATFORM_IMPORT_MAX,
        max_attempts: int = 5,
        max_body_bytes: int = _IMPORT_BODY_BYTES,
    ) -> PlatformBulkImportResult:
        """Imports any number of users in chunks of at most ``chunk_size`` (1,000) users and
        ``max_body_bytes``, and returns the aggregated results in input order.

        A chunk refused with 429 is sent again after a backoff (``Retry-After`` wins).
        Users the server rejected with ``rate_limited`` (too many new users per minute)
        are sent again on their own once the minute is over. A chunk that succeeded is
        never sent again. Each chunk gets ``max_attempts`` rounds (on top of the client's
        own ``max_retries`` for ``rate_limit_exceeded``); users still rate limited after
        that stay ``rejected`` in the results.

        Any other error raises :class:`~cabalspy_id.PlatformImportError` with ``result``
        (what was imported) and ``remaining`` (the users to pass again to resume).
        """
        run = _ImportRun(users, chunk_size, max_body_bytes, max_attempts)
        for chunk_no, chunk in enumerate(run.chunks):
            pending, attempt = chunk, 0
            while pending:
                attempt += 1
                try:
                    data = self._post(_IMPORT_PATH, run.body(pending))
                except RateLimitError as exc:
                    if attempt >= max_attempts:
                        raise run.failed(exc, chunk_no, pending) from exc
                    time.sleep(_backoff(attempt, exc))
                    continue
                except CabalSpyIDError as exc:
                    raise run.failed(exc, chunk_no, pending) from exc
                pending = run.record(pending, data)
                if pending and attempt >= max_attempts:
                    break
                if pending:
                    time.sleep(_import_wait())
        return run.result()  # type: ignore[return-value]

    def iter_platform_users(self, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Every platform user of your instance, newest first, following ``next_cursor``."""
        for page in self.pages("/platform-users/list", {"limit": limit}):
            yield from page.data

    def iter_platform_leaderboard(
        self,
        *,
        blockchain: Chain,
        period: Period | None = None,
        sort: LeaderboardSort | None = None,
        limit: int | None = None,
        trust: LeaderboardTrust | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every entry of the platform leaderboard, following ``next_cursor``."""
        query = _platform_leaderboard_query(blockchain, period, sort, trust, limit, None)
        for page in self.pages("/platform-users/leaderboard", query):
            yield from page.data.get("leaderboard", [])

    def offset_items(
        self, path: str, params: Mapping[str, Any] | None = None, *, key: str | None = None
    ) -> Iterator[Any]:
        """Walks an offset-paginated route (competitions) until ``pagination.total`` is reached.

        ``key``: the list inside ``data`` (e.g. ``"standings"``); None when ``data`` is the list.
        """
        query = dict(params or {})
        offset = int(query.pop("offset", None) or 0)
        while True:
            page = self.get_raw(path, {**query, "offset": offset or None})
            items = page.data if key is None else page.data.get(key, [])
            yield from items
            offset += len(items)
            total = (page.pagination or {}).get("total")
            if not items or total is None or offset >= total:
                return

    def iter_competitions(
        self, *, status: CompetitionStatus | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every competition of your instance, newest first."""
        _one_of(status, COMPETITION_STATUSES, "status")
        yield from self.offset_items("/competitions", {"status": status, "limit": limit})

    def iter_competition_participants(self, id: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Every participant of a competition, in join order."""
        _required(id, "id")
        yield from self.offset_items("/competitions/participants", {"id": id, "limit": limit})

    def iter_competition_standings(self, id: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Every trader of a competition's standings: ranked first, then the unranked."""
        _required(id, "id")
        yield from self.offset_items("/competitions/standings", {"id": id, "limit": limit}, key="standings")

    # ── callouts ─────────────────────────────────────────────────────────

    def iter_callouts(
        self,
        *,
        chain: Chain | None = None,
        mint: str | None = None,
        external_id: str | None = None,
        csid_id: str | None = None,
        since: str | datetime | None = None,
        until: str | datetime | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every callout matching the filters, newest first, following ``next_cursor``."""
        query = _callouts_query(chain, mint, external_id, csid_id, since, until, limit, None)
        for page in self.pages("/callouts", query):
            yield from page.data

    def iter_callout_leaderboard(
        self,
        *,
        period: Period | None = None,
        chain: Chain | None = None,
        sort: CalloutSort | None = None,
        min_callouts: int | None = None,
        hit_x: float | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every entry of the callers leaderboard, following ``next_cursor``."""
        query = _callout_leaderboard_query(period, chain, sort, min_callouts, hit_x, limit, None)
        for page in self.pages("/callouts/leaderboard", query):
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
        return await self._send_get(path, params, auth, self._interpret)

    async def get_text(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        """Async version of :meth:`CabalSpyID.get_text`."""
        return await self._send_get(path, params, True, self._interpret_text)

    async def _get_text(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return await self.get_text(path, params)

    async def _send_get(
        self, path: str, params: Mapping[str, Any] | None, auth: bool, parse: Callable[[httpx.Response, str], _T]
    ) -> _T:
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
                return parse(response, path)
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

    # ── white-label ──────────────────────────────────────────────────────

    async def bulk_import_platform_users(
        self,
        users: Iterable[PlatformUserInput],
        *,
        chunk_size: int = PLATFORM_IMPORT_MAX,
        max_attempts: int = 5,
        max_body_bytes: int = _IMPORT_BODY_BYTES,
    ) -> PlatformBulkImportResult:
        """Async version of :meth:`CabalSpyID.bulk_import_platform_users`."""
        run = _ImportRun(users, chunk_size, max_body_bytes, max_attempts)
        for chunk_no, chunk in enumerate(run.chunks):
            pending, attempt = chunk, 0
            while pending:
                attempt += 1
                try:
                    data = await self._post(_IMPORT_PATH, run.body(pending))
                except RateLimitError as exc:
                    if attempt >= max_attempts:
                        raise run.failed(exc, chunk_no, pending) from exc
                    await asyncio.sleep(_backoff(attempt, exc))
                    continue
                except CabalSpyIDError as exc:
                    raise run.failed(exc, chunk_no, pending) from exc
                pending = run.record(pending, data)
                if pending and attempt >= max_attempts:
                    break
                if pending:
                    await asyncio.sleep(_import_wait())
        return run.result()  # type: ignore[return-value]

    async def iter_platform_users(self, *, limit: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Every platform user of your instance, newest first, following ``next_cursor``."""
        async for page in self.pages("/platform-users/list", {"limit": limit}):
            for user in page.data:
                yield user

    async def iter_platform_leaderboard(
        self,
        *,
        blockchain: Chain,
        period: Period | None = None,
        sort: LeaderboardSort | None = None,
        limit: int | None = None,
        trust: LeaderboardTrust | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Every entry of the platform leaderboard, following ``next_cursor``."""
        query = _platform_leaderboard_query(blockchain, period, sort, trust, limit, None)
        async for page in self.pages("/platform-users/leaderboard", query):
            for entry in page.data.get("leaderboard", []):
                yield entry

    async def offset_items(
        self, path: str, params: Mapping[str, Any] | None = None, *, key: str | None = None
    ) -> AsyncIterator[Any]:
        """Async version of :meth:`CabalSpyID.offset_items`."""
        query = dict(params or {})
        offset = int(query.pop("offset", None) or 0)
        while True:
            page = await self.get_raw(path, {**query, "offset": offset or None})
            items = page.data if key is None else page.data.get(key, [])
            for item in items:
                yield item
            offset += len(items)
            total = (page.pagination or {}).get("total")
            if not items or total is None or offset >= total:
                return

    async def iter_competitions(
        self, *, status: CompetitionStatus | None = None, limit: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Every competition of your instance, newest first."""
        _one_of(status, COMPETITION_STATUSES, "status")
        async for item in self.offset_items("/competitions", {"status": status, "limit": limit}):
            yield item

    async def iter_competition_participants(
        self, id: str, *, limit: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Every participant of a competition, in join order."""
        _required(id, "id")
        async for item in self.offset_items("/competitions/participants", {"id": id, "limit": limit}):
            yield item

    async def iter_competition_standings(self, id: str, *, limit: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Every trader of a competition's standings: ranked first, then the unranked."""
        _required(id, "id")
        async for item in self.offset_items("/competitions/standings", {"id": id, "limit": limit}, key="standings"):
            yield item

    # ── callouts ─────────────────────────────────────────────────────────

    async def iter_callouts(
        self,
        *,
        chain: Chain | None = None,
        mint: str | None = None,
        external_id: str | None = None,
        csid_id: str | None = None,
        since: str | datetime | None = None,
        until: str | datetime | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Every callout matching the filters, newest first, following ``next_cursor``."""
        query = _callouts_query(chain, mint, external_id, csid_id, since, until, limit, None)
        async for page in self.pages("/callouts", query):
            for item in page.data:
                yield item

    async def iter_callout_leaderboard(
        self,
        *,
        period: Period | None = None,
        chain: Chain | None = None,
        sort: CalloutSort | None = None,
        min_callouts: int | None = None,
        hit_x: float | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Every entry of the callers leaderboard, following ``next_cursor``."""
        query = _callout_leaderboard_query(period, chain, sort, min_callouts, hit_x, limit, None)
        async for page in self.pages("/callouts/leaderboard", query):
            for entry in page.data.get("leaderboard", []):
                yield entry


def _users_query(params: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"limit", "kol", "cursor", "scope"}
    unknown = set(params) - allowed
    if unknown:
        raise TypeError(f"unexpected parameter(s): {', '.join(sorted(unknown))}")
    _one_of(params.get("scope"), SCOPES, "scope")
    return {**params, "kol": "true" if params.get("kol") else None}
