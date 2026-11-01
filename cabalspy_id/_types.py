"""Response shapes of the CabalSpy ID Data API and the login endpoints.

These are :class:`TypedDict` definitions, derived from the server source: they
cost nothing at runtime and give editors and type checkers something to work
with. Responses stay plain dicts, so fields the server adds later are never
dropped.

Timestamps are ISO 8601 UTC strings ("2026-10-12T08:00:00Z"), except
``PnlCalendarDay["date"]``, which is "DD-MM-YY" like the CabalSpy API.
"""

from __future__ import annotations

from typing import Any, Literal, TypeAlias, TypedDict

from ._constants import (
    CalloutFirstDayKind,
    CalloutPhase,
    CalloutSort,
    CalloutStatus,
    CalloutWho,
    Chain,
    CompetitionChain,
    CompetitionEnrollment,
    CompetitionKind,
    CompetitionMetric,
    CompetitionStatus,
    CopyInstructionStatus,
    CopyMode,
    CopySide,
    CopySides,
    Currency,
    DataScope,
    LeaderboardSort,
    Period,
    PlatformImportStatus,
    PlatformWalletStatus,
    Scope,
    ThesisStance,
    TradeLabel,
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
    #: Extras switched on for the instance by CabalSpy, e.g. ``["callouts"]``.
    features: list[str]


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
    #: Events about one of your platform users (white-label) also carry
    #: "external_id" (your own user id) and "csid_id".
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
    #: created | updated | deleted | wallets_removed | ignored | unknown_user | waiting_for_wallet
    result: str
    external_id: str
    csid_id: str
    wallets_added: list[WalletAdded]
    #: wallets_removed: the addresses removed, and {address, code} for each one kept
    wallets_removed: list[str]
    wallets_not_removed: list[dict[str, str]]
    #: ignored: why (wallet removals from auth providers are not applied)
    note: str
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


class _CompetitionKindFields(TypedDict, total=False):
    #: Trading competitions only.
    min_trades: int
    min_volume_usd: float
    #: Callout competitions only: callouts needed to be ranked, and the multiple that counts as a hit.
    min_callouts: int
    hit_x: float


class Competition(_CompetitionKindFields):
    """A competition as listed (GET /v1/competitions).

    Trading competitions carry ``min_trades`` and ``min_volume_usd``; callout
    competitions (``kind`` = callouts) ``min_callouts`` and ``hit_x``.
    """

    id: str
    name: str
    description: str | None
    kind: CompetitionKind
    #: "all" (every chain) only for callout competitions.
    chain: CompetitionChain
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


class CalloutBestCall(TypedDict):
    """A caller's best callout (highest peak multiple)."""

    id: str
    chain: Chain
    mint: str
    symbol: str | None
    peak_x: float | None


class CompetitionStanding(TypedDict, total=False):
    """One trader. Unranked traders (below the minimums) have ``rank`` None.

    Trading competitions carry the trading stats (pnl ... wallets); callout
    competitions the callout stats (callouts ... best_call).
    """

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
    # callout competitions
    callouts: int
    avg_peak_x: float | None
    median_peak_x: float | None
    best_peak_x: float | None
    sum_peak_x: float
    hits: int
    #: Percent (0-100) of the callouts that reached ``hit_x``.
    hit_rate: float
    best_call: CalloutBestCall | None


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


# ── callouts (an extra, switched on per instance on request) ─────────────────


class CalloutUser(TypedDict, total=False):
    """The caller. A user without a profile row only has ``csid_id``."""

    csid_id: str
    #: Your platform's user id (white-label), else None.
    external_id: str | None
    name: str | None
    username: str | None
    avatar_url: str | None
    kol: bool


class CalloutToken(TypedDict):
    name: str | None
    symbol: str | None
    logo: str | None


class CalloutPrice(TypedDict):
    price_usd: float | None
    market_cap_usd: float | None


class CalloutQuote(CalloutPrice):
    #: Multiple against the entry price (price / entry).
    x: float | None
    at: str | None


class CalloutTracking(TypedDict):
    active: bool
    phase: CalloutPhase
    next_check_at: str | None
    #: After the first day: since when the market cap is below $10k (tracking stops after
    #: 24 h in a row below it). None while at or above it, and once tracking stopped.
    below_10k_since: str | None
    #: Daily candle checks done after the first day.
    daily_checks: int
    stopped_at: str | None
    #: inactive (24 h below a $10k market cap) or no_price.
    stop_reason: str | None


class CalloutFirstDay(TypedDict):
    """The first 24 hours, scored on candles once they are over."""

    kind: CalloutFirstDayKind
    entry_price_usd: float | None
    #: candles only (None for kind = live).
    peak_x: float | None
    close_x: float | None
    minutes_to_peak: int | None
    #: e.g. STALE_ENTRY, NO_TRADES_AFTER, NO_TRADES_LAST_6H, EXTREME_MULTIPLE, CANDLES_UNAVAILABLE.
    flags: list[str]


class _CalloutOptional(TypedDict, total=False):
    #: Present once the first day is scored (``callout.scored``).
    first_day: CalloutFirstDay


class Callout(_CalloutOptional):
    """A callout: a user called a token; price and market cap are stamped and tracked."""

    id: str
    chain: Chain
    mint: str
    token: CalloutToken
    author: CalloutUser
    note: str | None
    called_at: str
    #: The end of the first day (called_at + 24 h).
    window_ends_at: str
    status: CalloutStatus
    #: Price and market cap at the call.
    at_call: CalloutPrice
    now: CalloutQuote
    peak: CalloutQuote
    #: The score: the peak multiple since the call.
    score_x: float | None
    #: Market data provider of the numbers.
    source: str | None
    tracking: CalloutTracking


class CalloutRemoved(TypedDict):
    id: str
    removed: bool


class CalloutSummary(TypedDict):
    """Peak multiples of a set of callouts."""

    callouts: int
    avg_peak_x: float | None
    median_peak_x: float | None
    best_peak_x: float | None
    sum_peak_x: float
    #: Callouts whose peak multiple reached ``hit_x``.
    hits: int
    #: Percent (0-100) of the callouts that reached ``hit_x``.
    hit_rate: float


class CalloutPeriodStats(CalloutSummary):
    """One period: the callouts made in the last 6h / 1d / 7d / 30d."""

    #: Average multiple right now.
    avg_now_x: float | None
    #: Callouts of the period that are still tracked.
    tracking: int


class CalloutStats(TypedDict):
    user: CalloutUser | None
    hit_x: float
    #: Keys 6h, 1d, 7d, 30d.
    periods: dict[str, CalloutPeriodStats]
    callouts_all_time: int


class CalloutLeaderboardEntry(CalloutSummary):
    rank: int
    csid_id: str
    author: CalloutUser | None
    best_call: CalloutBestCall


class CalloutLeaderboardResponse(TypedDict):
    period: Period
    chain: Chain | None
    sort: CalloutSort
    hit_x: float
    leaderboard: list[CalloutLeaderboardEntry]


class CalloutSettings(TypedDict):
    #: all, or kol_only (only users with the KOL badge).
    who: CalloutWho
    #: Only holders of the token may call it.
    require_holding: bool
    #: Minutes between two callouts of one user (0-10080).
    cooldown_minutes: int


class CalloutMilestone(Callout):
    """Stream event ``callout.milestone``: the callout plus the multiple reached."""

    milestone_x: float


class CalloutUpdate(TypedDict):
    """Stream event ``callout.update``: a new price of a tracked callout."""

    id: str
    chain: Chain
    mint: str
    price_usd: float
    market_cap_usd: float | None
    x: float | None
    peak_x: float


class CalloutRemovedEvent(TypedDict):
    """Stream event ``callout.removed``: the platform took a callout down."""

    id: str
    chain: Chain
    mint: str


class CalloutsStreamReady(TypedDict):
    events: list[str]
    chain: Chain | None
    mint: str | None


class CalloutWebhookData(TypedDict, total=False):
    """``data`` of the webhooks callout.created / .milestone / .scored / .final."""

    callout: Callout
    #: callout.milestone only.
    milestone_x: float


# ── copy trading ─────────────────────────────────────────────────────────────


class CopyTrader(TypedDict):
    """A copied trader as everyone may see them. A platform's own (managed) users have
    ``username`` and ``profile_url`` None."""

    csid_id: str
    username: str | None
    name: str | None
    image_url: str | None
    kol: bool
    profile_url: str | None


class CopySettings(TypedDict):
    """How one user copies one trader."""

    enabled: bool
    #: fixed_usd: every buy is ``amount_usd``; percent: ``percent`` % of the trader's buy.
    mode: CopyMode
    amount_usd: float
    #: Percent of the trader's buy in USD (mode percent), above 0 and at most 1000.
    percent: float
    #: Cap per copied buy in USD; None = no cap.
    max_usd: float | None
    #: buys, or both (sells are copied as a share of the copied position).
    sides: CopySides
    #: Price limit sent with every instruction (1-5000, default 300 = 3 %).
    slippage_bps: int
    updated_at: str | None


class CopyTradingSetting(TypedDict):
    """GET/POST /v1/copy-trading/settings: one trader in the user's Trade Feed and the copy settings."""

    trader: CopyTrader
    copy: CopySettings
    #: True while another platform copies this trader for this user (only that platform
    #: gets the instructions; switching it on here raises ``copy_managed_elsewhere``).
    managed_by_other_platform: bool


class CopyAction(TypedDict):
    """What to execute. Buys: ``amount_usd`` (and ``amount_native`` in ``currency``) with
    ``max_price_usd`` as the price limit. Sells: ``sell_percent`` of the copied position
    with ``min_price_usd`` as the price limit."""

    blockchain: Chain
    mint: str
    symbol: str | None
    name: str | None
    logo: str | None
    side: CopySide
    #: Buys only.
    amount_usd: float | None
    #: Buys only, when known: the same amount in the chain's native currency.
    amount_native: float | None
    currency: Currency | None
    #: Sells only: percent of the copied position to sell (100 = everything).
    sell_percent: float | None
    #: The trader's price.
    price_usd: float | None
    #: Buys: price_usd * (1 + slippage_bps / 10000).
    max_price_usd: float | None
    #: Sells: price_usd * (1 - slippage_bps / 10000).
    min_price_usd: float | None
    slippage_bps: int


class CopySourceTrade(TypedDict, total=False):
    """The trader's trade that was copied (as in the Trade Feed)."""

    blockchain: Chain
    mint: str
    symbol: str | None
    name: str | None
    logo: str | None
    side: CopySide
    #: new, add, partial, close or sell.
    label: str
    #: partial sells: percent of the position the trader sold.
    sold_percent: float | None
    amount_native: float
    currency: Currency | None
    amount_usd: float | None
    token_amount: float | None
    price_usd: float | None
    pnl_usd: float | None
    pnl_percent: float | None
    wallet: str
    wallet_url: str | None
    tx_signature: str
    tx_url: str | None


class CopyLinks(TypedDict, total=False):
    token: str | None
    terminal: str | None
    profile: str | None


class _CopyInstructionOptional(TypedDict, total=False):
    #: Webhook and stream only: your platform's user id (white-label), else None.
    external_id: str | None
    # REST only (the webhook and the stream send the new, pending instruction without them):
    #: As reported with the status.
    tx_signature: str | None
    executed_amount_usd: float | None
    note: str | None
    updated_at: str


class CopyInstruction(_CopyInstructionOptional):
    """A ready-to-execute copy instruction: execute ``action`` with the user's wallet, then
    report the result with ``report_copy_instruction``. CabalSpy ID never holds keys and
    never executes."""

    id: str
    type: Literal["copy_instruction"]
    #: pending, executed, failed, skipped; ``expired`` = still pending after ``expires_at``.
    status: CopyInstructionStatus
    created_at: str
    #: ``created_at`` + 120 seconds.
    expires_at: str
    #: The user to execute it for.
    csid_id: str
    trader: CopyTrader
    action: CopyAction
    source_trade: CopySourceTrade
    #: The copy settings when the instruction was made.
    settings: CopySettings
    links: CopyLinks


class CopyTradingStreamReady(TypedDict):
    events: list[str]


# ── trade feed ───────────────────────────────────────────────────────────────


class TradeFeedTrade(TypedDict):
    """A trade in the Trade Feed (``item["trade"]``)."""

    blockchain: Chain
    mint: str
    symbol: str | None
    name: str | None
    logo: str | None
    side: CopySide
    #: new, add, partial, close or sell.
    label: TradeLabel
    #: partial: the share of the position sold, 0-100; else None.
    sold_percent: float | None
    #: Trade size in the chain's native coin (``currency``).
    amount_native: float
    currency: Currency | None
    amount_usd: float | None
    token_amount: float | None
    price_usd: float | None
    #: Sells with a known entry: realized PnL of this sell against the average entry.
    pnl_usd: float | None
    pnl_percent: float | None
    wallet: str
    wallet_url: str | None
    tx_signature: str
    tx_url: str | None


class TradeFeedThesis(TypedDict):
    """A thesis in the Trade Feed (``item["thesis"]``)."""

    id: str
    blockchain: Chain
    mint: str
    symbol: str | None
    name: str | None
    logo: str | None
    stance: ThesisStance | None
    body: str
    likes: int
    replies: int
    url: str


class _TradeFeedItemOptional(TypedDict, total=False):
    #: GET /v1/trade-feed only: the item's position in the feed.
    cursor: str


class TradeFeedTradeItem(_TradeFeedItemOptional):
    """A trade item: the same ``id`` everywhere (feed, webhook, stream, notifications)."""

    id: str
    type: Literal["trade"]
    timestamp: str
    trader: CopyTrader
    trade: TradeFeedTrade
    #: token (the CabalSpy Terminal on Solana and BNB Chain, else the token's theses),
    #: terminal (None outside Solana and BNB Chain), profile.
    links: CopyLinks


class TradeFeedThesisItem(_TradeFeedItemOptional):
    """A thesis item; ``id`` is ``"h"`` followed by the thesis id."""

    id: str
    type: Literal["thesis"]
    timestamp: str
    trader: CopyTrader
    thesis: TradeFeedThesis
    links: CopyLinks


#: GET /v1/trade-feed: a trade or a thesis (check ``item["type"]``).
TradeFeedItem: TypeAlias = TradeFeedTradeItem | TradeFeedThesisItem


class TradeFeedMinNative(TypedDict):
    """Minimum trade size for alerts per native coin (0 = every trade)."""

    SOL: float
    BNB: float
    ETH: float


class TradeFeedSettings(TypedDict):
    """A user's alert settings for one trader, plus the copy settings."""

    notify_buys: bool
    notify_sells: bool
    notify_theses: bool
    min_native: TradeFeedMinNative
    #: No alerts for this trader.
    muted: bool
    #: How the user copies this trader (see copy trading).
    copy: CopySettings


class TradeFeedTrader(TypedDict):
    """GET /v1/trade-feed/traders: one trader in the user's Trade Feed."""

    trader: CopyTrader
    #: False while the trader keeps their trading private: they stay in the list, but
    #: nothing of them shows in the feed.
    trading_public: bool
    added_at: str
    #: In how many Trade Feeds the trader is.
    in_trade_feeds: int
    settings: TradeFeedSettings


class TradeFeedTraderResult(TypedDict):
    """POST /v1/trade-feed/traders (HTTP 201 when added, 200 when already there)."""

    in_trade_feed: Literal[True]
    #: True when the trader was added, False when they were already in the Trade Feed.
    created: bool
    trader: CopyTrader
    settings: TradeFeedSettings


class TradeFeedRemoveResult(TypedDict):
    """POST /v1/trade-feed/traders/delete."""

    in_trade_feed: Literal[False]
    #: False when the trader was not in the Trade Feed.
    removed: bool


class TradeFeedNotification(TypedDict):
    """GET /v1/trade-feed/notifications: an alert that passed the user's filters."""

    id: int
    #: trade_feed.trade or trade_feed.thesis.
    event: str
    #: A ready-made line in plain text.
    text: str | None
    created_at: str
    data: TradeFeedItem


class _TradeFeedRecipients(TypedDict):
    #: csid_ids of your users to tell (trader in their Trade Feed, filters passed).
    recipients: list[str]
    #: Your own user ids (external_id) of the recipients who are platform users.
    recipients_external: list[str]


class TradeFeedTradeEvent(TradeFeedTradeItem, _TradeFeedRecipients):
    """``data`` of the webhook and stream event ``trade_feed.trade``."""


class TradeFeedThesisEvent(TradeFeedThesisItem, _TradeFeedRecipients):
    """``data`` of the webhook and stream event ``trade_feed.thesis``."""


#: ``data`` of a Trade Feed webhook or stream event.
TradeFeedEvent: TypeAlias = TradeFeedTradeEvent | TradeFeedThesisEvent


class TradeFeedStreamReady(TypedDict):
    events: list[str]
