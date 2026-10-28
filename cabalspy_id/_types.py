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

from ._constants import (
    Chain,
    CompetitionEnrollment,
    CompetitionMetric,
    CompetitionStatus,
    Currency,
    DataScope,
    LeaderboardSort,
    Period,
    PlatformImportStatus,
    PlatformWalletStatus,
    Scope,
    VerificationStatus,
    WalletTrust,
)

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
    #: https://x.com/<handle>; None for people without X.
    twitter: str | None
    #: https://t.me/<name> when Telegram is connected, else "".
    telegram: str
    #: None for people who signed in with Telegram or Google and have not connected X.
    x: XStats | None
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
    #: https://x.com/<handle>; None for people without X.
    twitter: str | None
    #: https://t.me/<name> when Telegram is connected, else "".
    telegram: str
    #: None for people who signed in with Telegram or Google and have not connected X.
    x: XStats | None
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
    #: https://x.com/<handle>; None for people without X.
    twitter: str | None
    #: https://t.me/<name> when Telegram is connected, else "".
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
    #: https://x.com/<handle>; None for people without X.
    twitter: str | None
    #: https://t.me/<name> when Telegram is connected, else "".
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
    #: X handle; without X ``tg.<telegram name>`` (Telegram) or ``id.<hex>`` (Google). X handles never contain a dot.
    preferred_username: str
    picture: str | None
    #: https://id.cabalspy.xyz/u/<username>
    profile: str
    kol_badge: bool
    #: Full X profile, userinfo only (scope profile). None without X; see has_x().
    x: XProfileClaim | None
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
    #: Carries "sub" (the user's CabalSpy ID), except for webhook.test and the
    #: instance-level competition.* events (those carry "competition_id").
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


class ThesisReactor(TypedDict):
    """Who reacted recently (newest first)."""

    emoji: str
    csid_id: str
    username: str | None
    at: str


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
    #: The latest reactions with who reacted, newest first.
    reacted_by: list[ThesisReactor]
    #: The viewer's own reactions (pass csid_id / an access token).
    my_reactions: list[str]
    #: Name of the app it was posted through.
    via: str | None
    created_at: str
    is_mine: bool
    #: Theses only (not replies).
    position: ThesisPosition
    #: Theses only: a preview of the newest replies, oldest first.
    latest_replies: list[Thesis]
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


class ThesisNotification(TypedDict):
    """A moderation notification (warning, hidden post, pause, appeal result ...).

    ``kind``: post_hidden, paused, banned, post_removed, post_restored,
    appeal_accepted, appeal_rejected, reporting_paused.
    """

    id: int
    kind: str
    #: Ready-to-show English text.
    text: str
    #: Details, e.g. thesis_id, until, note.
    data: dict[str, Any]
    created_at: str
    read: bool
    #: Can be appealed (within 30 days).
    appealable: bool
    #: pending | accepted | rejected when appealed, else None.
    appeal: str | None


class ThesisNotifications(TypedDict):
    unread: int
    items: list[ThesisNotification]


class ThesisNotices(TypedDict):
    """Unread moderation notices of the signed-in user (public API ``me()``)."""

    unread: int
    latest: str | None
    url: str


class ThesisReactions(TypedDict):
    id: str
    reactions: dict[str, int]


# ── white-label: platform users ──────────────────────────────────────────────
# A platform that keeps its own login manages its users by its own user id
# (``external_id``). Responses below come from /v1/platform-users/*.


class PlatformWalletInput(TypedDict, total=False):
    """A wallet you submit for a platform user (no payment verification).

    Plain address strings work too. Default ``chains``: solana for a Solana
    address, every enabled EVM chain for an EVM address.
    """

    address: str
    chains: list[Chain]
    #: Where the wallet comes from, e.g. "privy" (1-40 characters a-z 0-9 _ . -).
    source: str


class PlatformUserInput(TypedDict, total=False):
    """One user of an import. ``external_id`` always, ``wallets`` for new users."""

    #: Your own user id: 1-128 printable ASCII characters, no spaces.
    external_id: str
    #: 1-10 wallets (objects or plain address strings).
    wallets: list[PlatformWalletInput | str]
    #: 1-60 characters, or None to clear.
    display_name: str | None
    #: An https URL (max 500 characters), or None to clear.
    avatar_url: str | None


class PlatformWallet(TypedDict):
    address: str
    #: "solana" or "evm".
    family: str
    chains: list[Chain]
    #: Payment-verified on at least one chain.
    verified: bool
    verified_chains: list[Chain]
    status: PlatformWalletStatus
    #: Whether the wallet counts for tracking, data and leaderboards.
    counts: bool
    source: str | None
    verified_at: str | None
    added_at: str | None


class WalletAdded(TypedDict):
    """A wallet (or new chains of it) added by the platform."""

    address: str
    family: str
    chains: list[Chain]
    source: str | None


class WalletVerification(TypedDict):
    """A payment verification of a wallet, started by the platform."""

    verification_id: str
    status: VerificationStatus
    chain: Chain
    chain_name: str
    address: str
    #: Amount to send, formatted in the chain's currency.
    amount: str
    #: Amount in base units (lamports / wei), as a string.
    amount_base: str
    currency: str
    decimals: int
    receiver: str
    expires_at: str
    seconds_left: int
    #: solana:... or ethereum:...@chainId URI for wallets and QR codes.
    payment_uri: str
    evm_chain_id: int | None
    instructions: str
    tx_hash: str | None
    explorer_url: str | None
    created_at: str | None


class PlatformWalletVerification(WalletVerification):
    """The verification endpoints' answer: the verification plus whose it is."""

    external_id: str


class PlatformUserX(TypedDict):
    id: str
    username: str
    name: str | None
    avatar_url: str | None
    followers: int | None
    following: int | None
    verified: bool | None
    verified_type: str | None
    created_at: str | None
    url: str


class PlatformUserTelegram(TypedDict):
    username: str | None
    name: str | None
    linked_at: str | None


class PlatformUser(TypedDict):
    """One platform user (no trading data; see :class:`PlatformUserProfile`)."""

    csid_id: str
    external_id: str
    #: True once the person took the account into their own CabalSpy ID (claim link).
    claimed: bool
    claimed_at: str | None
    managed: bool
    display_name: str | None
    avatar_url: str | None
    #: Beyond the plan's user limit: no data until the platform upgrades.
    limited: bool
    x: PlatformUserX | None
    telegram: PlatformUserTelegram | None
    kol: KolBadge
    wallets: list[PlatformWallet]
    pending_verifications: list[WalletVerification]
    created_at: str | None


class PlatformUserUpsert(PlatformUser):
    """POST /v1/platform-users: the user plus what this call changed."""

    created: bool
    wallets_added: list[WalletAdded]


class PlatformWalletsResponse(TypedDict):
    external_id: str
    wallets_added: list[WalletAdded]
    wallets: list[PlatformWallet]


class PlatformItemError(TypedDict):
    code: str
    message: str


class PlatformImportItem(TypedDict, total=False):
    external_id: str | None
    #: Absent for rejected items.
    csid_id: str
    status: PlatformImportStatus
    wallets_added: list[WalletAdded]
    #: Only for rejected items (plan_user_limit, wallet_required, rate_limited, ...).
    error: PlatformItemError


class PlatformImportSummary(TypedDict):
    created: int
    updated: int
    unchanged: int
    rejected: int


class PlatformImportResult(TypedDict):
    summary: PlatformImportSummary
    #: One result per submitted user, in the same order.
    results: list[PlatformImportItem]


class PlatformBulkImportResult(PlatformImportResult):
    """The aggregated result of ``bulk_import_platform_users``."""

    #: Import calls made (chunks plus retries).
    requests: int


class PlatformUserDeleted(TypedDict):
    external_id: str
    #: False for claimed users: only the link to your platform goes.
    deleted: bool
    unlinked: bool


class PlatformWalletRemoved(TypedDict):
    external_id: str
    address: str
    removed: bool


class PlatformInbound(TypedDict):
    enabled: bool
    last_event_at: str | None


class PlatformInboundStatus(PlatformInbound):
    #: Payload formats the inbound URL understands (csid, privy, dynamic, generic).
    formats: list[str]


class PlatformInboundEnabled(TypedDict):
    enabled: bool
    #: The secret inbound URL. Shown once; enabling again replaces it.
    url: str
    note: str


class PlatformSettings(TypedDict):
    name: str
    white_label: bool | None
    data_scope: DataScope
    #: The same as data_scope == "csid".
    network_sharing: bool
    wallet_trust: WalletTrust
    leaderboard_trust: WalletTrust
    claim_links: bool | None
    telegram_alerts: bool | None
    inbound: PlatformInbound


class PlatformSession(TypedDict):
    external_id: str
    client_id: str
    #: pvs_... token for the embeddable verify widget.
    session: str
    expires_at: str
    expires_in: int


class PlatformClaimLink(TypedDict):
    external_id: str
    url: str
    expires_at: str


class PlatformXConnect(TypedDict):
    external_id: str
    #: Send the user here to connect X; they come back to ``return_url``.
    authorize_url: str
    expires_at: str


class PlatformXDisconnect(TypedDict):
    external_id: str
    disconnected: bool


class PlatformTelegramLink(TypedDict):
    external_id: str
    code: str
    #: t.me deep link that links the user's Telegram.
    deep_link: str
    expires_at: str | None


class PlatformTelegramStatus(TypedDict):
    external_id: str
    linked: bool
    username: str | None
    linked_at: str | None


class KolApplicationStatus(TypedDict):
    status: str
    applied_at: str | None
    reviewed_at: str | None


class PlatformKolStatus(TypedDict):
    external_id: str
    badge: bool
    eligible: bool
    criteria: list[dict[str, Any]]
    volume_7d_usd: float | None
    volume_check_next_at: str | None
    application: KolApplicationStatus | None


class PlatformKolVolumeCheck(TypedDict):
    external_id: str
    queued: bool


class PlatformKolApply(TypedDict):
    external_id: str
    application: Literal["pending"]


class PlatformTradingWallet(TypedDict, total=False):
    """Period stats of one wallet (the leaderboard ``period_stats`` fields plus these)."""

    address: str
    verified: bool
    win_rate_percentage: float
    total_volume_usd: float
    realized_pnl_usd: float
    total_txn: int


class PlatformTrading(TypedDict):
    """A user's trading on one chain, summed over their wallets that count."""

    blockchain: Chain
    currency: Currency
    period: Period
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    total_volume: float
    total_volume_usd: float
    realized_pnl: float
    realized_pnl_usd: float
    total_txn: int
    buy_txn: int
    sell_txn: int
    win_count: int
    closed_count: int
    win_rate_percentage: float
    tokens: int
    wallets: list[PlatformTradingWallet]


class PlatformProfileLinks(TypedDict):
    blockchain: Chain
    address: str
    tracker: str
    history: str
    holdings: str
    pnl_calendar: str


class PlatformUserProfile(PlatformUser):
    """GET /v1/platform-users/profile: everything for a profile page in one call.

    ``kol`` additionally carries ``application`` ({status, applied_at, note} or None).
    """

    period: Period
    trading: list[PlatformTrading]
    #: Newest 20 trades (the :class:`Trade` fields without ``trader``).
    recent_trades: list[dict[str, Any]]
    #: {"total": int, "latest": [Thesis, ...]}
    theses: dict[str, Any]
    #: {"traders": int, "in_trade_feeds": int}
    trade_feed: dict[str, int]
    links: list[PlatformProfileLinks]


class PlatformLeaderboardEntry(LeaderboardEntry):
    external_id: str | None
    #: The wallet is payment-verified on this chain.
    verified: bool


class PlatformLeaderboardResponse(TypedDict):
    """GET /v1/platform-users/leaderboard. Pagination is in the envelope."""

    blockchain: Chain
    period: Period
    sort: LeaderboardSort
    currency: Currency
    #: "verified" when only payment-verified wallets are ranked.
    trust: Literal["all", "verified"]
    leaderboard: list[PlatformLeaderboardEntry]


class InboundEventResult(TypedDict, total=False):
    """What the inbound URL answers to a sign-up event."""

    accepted: bool
    #: created | updated | deleted | unknown_user | waiting_for_wallet
    result: str
    external_id: str
    csid_id: str
    wallets_added: list[WalletAdded]
    error: PlatformItemError


# ── trading competitions ─────────────────────────────────────────────────────


class CompetitionChange(TypedDict):
    rules_version: int
    changed_at: str | None
    #: The phase the change happened in (scheduled, running).
    during: str
    #: {field: {"from": old, "to": new}}
    changes: dict[str, dict[str, Any]]
    note: str | None


class Competition(TypedDict):
    """A competition as listed (GET /v1/competitions)."""

    id: str
    name: str
    description: str | None
    chain: Chain
    chain_name: str
    metric: CompetitionMetric
    wallet_trust: WalletTrust
    enrollment: CompetitionEnrollment
    status: CompetitionStatus
    starts_at: str | None
    duration_hours: float
    started_at: str | None
    ends_at: str | None
    ended_at: str | None
    min_participants: int
    max_participants: int | None
    participants: int
    min_trades: int
    min_volume_usd: float
    late_join: bool
    prizes: Any
    rules_version: int
    standings_updated_at: str | None
    created_at: str | None
    updated_at: str | None


class CompetitionDetail(Competition):
    """Create, detail and update: the competition plus every rule change."""

    changes: list[CompetitionChange]
    changed_while_running: bool


class CompetitionParticipant(TypedDict):
    external_id: str | None
    csid_id: str
    joined_at: str | None


class CompetitionStanding(TypedDict, total=False):
    """One trader. Unranked traders (below the minimums) have ``rank`` None."""

    rank: int | None
    ranked: bool
    external_id: str | None
    csid_id: str
    #: The value of the competition's metric.
    score: float
    pnl: float
    pnl_usd: float
    volume: float
    volume_usd: float
    trades: int
    buys: int
    sells: int
    win_count: int
    closed_count: int
    win_rate: float
    tokens: int
    wallets: int


class CompetitionStandings(TypedDict):
    competition_id: str
    status: CompetitionStatus
    metric: CompetitionMetric
    rules_version: int
    updated_at: str | None
    #: True once the competition ended: these are the results.
    final: bool
    standings: list[CompetitionStanding]


class CompetitionMembership(TypedDict, total=False):
    competition_id: str
    external_id: str
    #: join: True; ``already`` says whether the user was in before.
    joined: bool
    already: bool
    #: leave: whether the user was a participant.
    left: bool
