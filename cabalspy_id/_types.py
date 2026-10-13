"""Response shapes of the CabalSpy ID Data API and the login endpoints.

These are :class:`TypedDict` definitions, derived from the server source: they
cost nothing at runtime and give editors and type checkers something to work
with. Responses stay plain dicts, so fields the server adds later are never
dropped.

Timestamps are ISO 8601 UTC strings ("2026-10-12T08:00:00Z"), except
``PnlCalendarDay["date"]``, which is "DD-MM-YY" like the CabalSpy API.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from ._constants import Chain, Currency, LeaderboardSort, Period, Scope

# ── envelope ─────────────────────────────────────────────────────────────────


class ResponseMeta(TypedDict):
    request_id: str
    cached: bool
    cache_age_seconds: int
    version: str
    timestamp: str


class Pagination(TypedDict, total=False):
    limit: int
    #: Absent on /wallets/history, None on /transactions/latest.
    total: int | None
    has_more: bool
    next_cursor: str | None


# ── account ──────────────────────────────────────────────────────────────────


class HealthResponse(TypedDict):
    status: Literal["ok", "degraded"]
    trade_sync_age_seconds: int | None


class MeResponse(TypedDict):
    #: The registrable domain of a live instance, else the client_id.
    instance: str
    client_id: str
    mode: Literal["sandbox", "development", "live"]
    #: free | starter | pro | business | enterprise, or "development" for non-live apps.
    plan: str
    #: Requests per second; None = unlimited.
    rate_limit_rps: int | None
    #: Whether the key may open the live stream (Pro plan and up).
    websockets: bool
    #: Whether scope="global" is available (Enterprise).
    global_scope: bool
    users_with_data: int


# ── users ────────────────────────────────────────────────────────────────────


class VerifiedWallet(TypedDict):
    address: str
    #: "solana" or "evm".
    family: str
    chains: list[Chain]
    verified_at: str | None


class XStats(TypedDict):
    id: str
    followers: int | None
    following: int | None
    verified: bool | None
    verified_type: str | None


class KolBadge(TypedDict):
    badge: bool
    since: str | None


class Profile(TypedDict):
    #: The user's id: the ``sub`` of their ID token.
    csid_id: str
    username: str
    name: str | None
    image_url: str | None
    bio: str | None
    twitter: str
    x: XStats
    kol: KolBadge
    profile_url: str
    wallets: list[VerifiedWallet]
    joined_at: str | None


class WalletOwner(TypedDict):
    csid_id: str
    username: str
    name: str | None
    image_url: str | None
    bio: str | None
    twitter: str
    x: XStats
    kol: KolBadge
    profile_url: str
    joined_at: str | None


class WalletLookupResponse(TypedDict):
    address: str
    verified: bool
    wallet: VerifiedWallet | None
    owner: WalletOwner


# ── trading ──────────────────────────────────────────────────────────────────


class TraderProfile(TypedDict, total=False):
    csid_id: str
    username: str
    name: str | None
    image_url: str | None
    twitter: str
    telegram: str
    blockchain: Chain
    currency: Currency
    type: Literal["csid"]
    kol: bool
    #: e.g. "13:00-22:00 UTC"; empty without trades in 30 days.
    active_hours: str
    profile_url: str
    wallet_address: str


class PeriodStats(TypedDict):
    period: Period
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    volume: float
    volume_usd: float
    #: Cash flow inside the window: sells minus buys.
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    buy_txn: int
    sell_txn: int
    largest_buy: float
    best_trade_pnl: float
    worst_trade_pnl: float
    win_count: int
    loss_count: int
    avg_hold_time_minutes: float


class WinRateBuckets(TypedDict):
    above_500: int
    above_100_to_500: int
    above_zero_to_100: int
    below_zero: int


class WinRateDistribution(WinRateBuckets):
    win_count: int
    closed_count: int
    win_rate_percentage: float


class ActiveTokens(TypedDict):
    active_tokens_count: int
    avg_position_size: float
    still_holding_count: int


class HistoryToken(TypedDict):
    mint: str
    token_name: str | None
    token_symbol: str | None
    token_logo: str | None
    buy_value: float
    buy_value_usd: float
    sell_value: float
    sell_value_usd: float
    buy_tokens: float
    sell_tokens: float
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    currency: Currency
    remaining_tokens: float


class PnlChartPoint(TypedDict):
    timestamp: str
    realized_pnl: float
    realized_pnl_usd: float


class TrackerTrade(TypedDict, total=False):
    mint: str
    token_name: str | None
    token_logo: str | None
    transaction_type: Literal["buy", "sell"]
    buy_token: None
    sell_token: None
    buy_value: float
    buy_value_usd: float
    sell_value: float
    sell_value_usd: float
    token_amount: float | None
    created_at: str
    tx_signature: str


class TrackerResponse(TypedDict):
    wallet: str
    profile: TraderProfile
    period_stats: PeriodStats
    period_win_rate_distribution: WinRateDistribution
    period_active_tokens: ActiveTokens
    period_history_tokens: list[HistoryToken]
    #: Cumulative realized PnL, starts at 0, one point every 15 minutes.
    period_realized_pnl_chart: list[PnlChartPoint]
    period_trades: list[TrackerTrade]


class LifetimeStats(TypedDict):
    buy: float
    sell: float
    realized_pnl: float
    realized_pnl_percentage: float
    buy_txn: int
    sell_txn: int
    total_tx_count: int
    win_count: int
    total_sold: int
    win_rate: float
    active_tokens_count: int
    largest_buy: float
    best_trade_pnl: float
    worst_trade_pnl: float
    still_holding_count: int


class TokenOverview(TypedDict):
    mint: str
    token_name: str | None
    token_logo: str | None
    invested: float
    sold: float
    realized_pnl: float
    realized_pnl_percentage: float
    currency: Currency
    buy_txn: int
    sell_txn: int
    first_seen: str
    last_seen: str
    still_holding: bool


class HistoryTrade(TypedDict):
    tx_signature: str
    mint: str
    token_name: str | None
    token_logo: str | None
    transaction_type: Literal["buy", "sell"]
    value: float
    value_usd: float
    currency: Currency
    created_at: str


class HistoryResponse(TypedDict):
    lifetime_stats: LifetimeStats
    win_rate_distribution: WinRateBuckets
    token_overview: list[TokenOverview]
    #: One page of trades, newest first.
    trades: list[HistoryTrade]
    profile: TraderProfile


class HoldingToken(TypedDict, total=False):
    token_address: str | None
    token_name: str | None
    symbol: str | None
    logo: str | None
    amount: str
    amount_formatted: str
    decimals: int | None
    price_usd: float
    value_usd: float
    verified_contract: bool | None
    avg_buy_price_usd: float | None
    unrealized_pnl_usd: float | None


class ActiveHoldings(TypedDict):
    tokens: list[HoldingToken]
    count: int
    total_value_usd: float
    last_updated: str
    stale: bool
    loading: bool


class HoldingsResponse(TypedDict):
    wallet: str
    blockchain: Chain
    profile: TraderProfile
    active_holdings: ActiveHoldings


class PnlCalendarDay(TypedDict):
    #: "DD-MM-YY"
    date: str
    realized_pnl: float
    realized_pnl_usd: float
    buy_txn: int
    sell_txn: int
    txn_total: int
    tokens_traded: int
    volume: float
    total_buy: float
    total_sell: float
    total_buy_usd: float
    total_sell_usd: float


class PnlCalendarMonth(TypedDict, total=False):
    month: int
    year: int
    dates: list[PnlCalendarDay]
    realized_pnl: float
    realized_pnl_usd: float
    volume: float
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    buy_txn: int
    sell_txn: int
    txn_total: int
    tokens_traded: int
    positive_streak: int
    negative_streak: int
    #: Only on the current month.
    current_positive_streak: int
    current_negative_streak: int


class PnlCalendarResponse(TypedDict):
    wallet: str
    profile: TraderProfile
    #: Oldest first.
    months: list[PnlCalendarMonth]
    #: Days of the current month.
    dates: list[PnlCalendarDay]
    month: PnlCalendarMonth | None


class LeaderboardProfile(TypedDict):
    csid_id: str
    username: str
    name: str | None
    image_url: str | None
    twitter: str
    telegram: str
    blockchain: Chain
    currency: Currency
    wallet_type: Literal["csid"]
    kol: bool
    public_trading: bool


class LeaderboardPeriodStats(TypedDict):
    period: Period
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    total_volume: float
    total_volume_usd: float
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    avg_hold_time_minutes: float
    total_txn: int
    buy_txn: int
    sell_txn: int


class LeaderboardWinRate(TypedDict):
    win_count: int
    closed_count: int
    win_rate_percentage: float


class LeaderboardTokens(TypedDict):
    total_tokens: int


class LeaderboardEntry(TypedDict):
    rank: int
    wallet: str
    profile: LeaderboardProfile
    period_stats: LeaderboardPeriodStats
    period_win_rate_distribution: LeaderboardWinRate
    period_history_tokens: LeaderboardTokens


class LeaderboardResponse(TypedDict):
    blockchain: Chain
    type: Literal["csid"]
    scope: Scope
    period: Period
    sort: LeaderboardSort
    currency: Currency
    #: The leaderboard paginates inside ``data``.
    pagination: Pagination
    leaderboard: list[LeaderboardEntry]


class TradeOwner(TypedDict):
    csid_id: str
    username: str
    name: str | None
    image_url: str | None
    kol: bool


class Trade(TypedDict):
    """One trade, from /transactions/latest and the live stream."""

    signature: str
    blockchain: Chain
    wallet: str
    mint: str
    transaction_type: Literal["buy", "sell"]
    token_symbol: str | None
    token_name: str | None
    token_logo: str | None
    token_amount: float | None
    value: float
    value_usd: float
    currency: Currency
    timestamp: str
    trader: TradeOwner | None


# ── OpenID Connect ───────────────────────────────────────────────────────────


class XProfileClaim(TypedDict, total=False):
    id: str
    username: str
    followers: int | None
    following: int | None
    posts: int | None
    listed: int | None
    verified: bool | None
    verified_type: str | None
    created_at: str | None
    fetched_at: str


class WalletClaim(TypedDict):
    address: str
    family: str
    chains: list[Chain]
    verified_at: str | None


class OnchainClaim(TypedDict):
    volume_7d_usd: float
    checked_at: str


class CabalSpyIDClaims(TypedDict, total=False):
    """Claims of an ID token or a userinfo response.

    When the platform is over its plan's user limit, ``sub`` is an anonymous
    ``anon_...`` id, ``limited`` is True and no profile or wallet data is included.
    """

    sub: str
    iss: str
    aud: str
    azp: str
    exp: int
    iat: int
    auth_time: int
    nonce: str
    name: str | None
    preferred_username: str
    picture: str | None
    #: https://id.cabalspy.xyz/u/<username>
    profile: str
    kol_badge: bool
    #: Full X profile, userinfo only (scope profile).
    x: XProfileClaim
    #: Verified wallets, userinfo only (scope wallets).
    wallets: list[WalletClaim]
    #: Latest 7-day on-chain volume, userinfo only (scope onchain).
    onchain: OnchainClaim | None
    #: A made-up sandbox identity; never trust it in production.
    sandbox: bool
    limited: bool
    reason: str
    message: str


class TokenResponse(TypedDict, total=False):
    access_token: str
    token_type: str
    #: Seconds. Access and ID tokens live 15 minutes.
    expires_in: int
    id_token: str
    scope: str
    #: Only with the offline_access scope. Rotates on every refresh.
    refresh_token: str


class DiscoveryDocument(TypedDict, total=False):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    revocation_endpoint: str
    scopes_supported: list[str]
    response_types_supported: list[str]
    grant_types_supported: list[str]
    id_token_signing_alg_values_supported: list[str]
    token_endpoint_auth_methods_supported: list[str]
    code_challenge_methods_supported: list[str]
    claims_supported: list[str]


# ── webhooks ─────────────────────────────────────────────────────────────────


class WebhookEvent(TypedDict):
    #: Event id; the same on every retry. Dedupe on it.
    id: str
    type: str
    created_at: str
    sandbox: bool
    #: Always carries "sub" (the user's CabalSpy ID), except for webhook.test.
    data: dict[str, Any]


# ── token theses ─────────────────────────────────────────────────────────────


class ThesisAuthor(TypedDict):
    csid_id: str
    username: str | None
    name: str | None
    image_url: str | None
    kol_badge: bool
    profile_url: str | None


class ThesisPnl(TypedDict, total=False):
    invested_usd: float
    realized_usd: float
    holding_value_usd: float | None
    pnl_usd: float | None
    pnl_percent: float | None
    tokens_held: float | None
    #: at_post only
    first_buy: str | None
    #: now only: "holding" or "sold"
    status: Literal["holding", "sold"]


class ThesisPosition(TypedDict, total=False):
    """The author's real position. ``{"private": True}`` when they keep trading private."""

    #: What was bought and sold when the thesis was posted.
    at_post: ThesisPnl
    #: Live PnL now, and whether the author still holds or sold.
    now: ThesisPnl | None
    private: bool


class Thesis(TypedDict, total=False):
    """A thesis (``kind == "thesis"``) or a reply to one (``kind == "reply"``)."""

    id: str
    chain: Chain
    mint: str
    kind: Literal["thesis", "reply"]
    parent_id: str | None
    body: str
    stance: Literal["bull", "bear"] | None
    author: ThesisAuthor
    likes: int
    replies: int
    #: Count per reaction, e.g. {"like": 3, "🚀": 1}.
    reactions: dict[str, int]
    #: The viewer's own reactions (pass csid_id / an access token).
    my_reactions: list[str]
    #: Name of the app it was posted through.
    via: str | None
    created_at: str
    is_mine: bool
    #: Theses only (not replies).
    position: ThesisPosition
    #: Stream payloads only.
    blockchain: Chain


class ThesisToken(TypedDict):
    chain: Chain
    mint: str
    name: str | None
    symbol: str | None
    logo: str | None
    price_usd: float | None


class ThesisSummary(TypedDict):
    theses: int
    bull: int
    bear: int
    authors: int
    token: ThesisToken


class ThesisEligibility(TypedDict, total=False):
    #: Holders only: one of the user's verified wallets bought and still holds the token.
    can_post: bool
    can_reply: bool
    holder: bool | None
    #: Posting paused after several hidden posts.
    paused: bool
    #: Data API: why the user can't write through your app.
    reason: str


class ThesisReactions(TypedDict):
    id: str
    reactions: dict[str, int]
