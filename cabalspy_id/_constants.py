"""Chains, periods and other fixed values of the CabalSpy ID Data API."""

from __future__ import annotations

from typing import Literal

SDK_VERSION = "0.6.0"
USER_AGENT = f"cabalspy-id-python/{SDK_VERSION}"

DEFAULT_BASE_URL = "https://api-id.cabalspy.xyz/v1"
DEFAULT_STREAM_URL = "wss://api-id.cabalspy.xyz/v1/stream"
DEFAULT_ISSUER = "https://id.cabalspy.xyz"

Chain = Literal["solana", "bnb", "base", "eth", "rh"]
Period = Literal["6h", "1d", "7d", "30d"]
LeaderboardSort = Literal["volume", "pnl", "pnl_usd", "win_rate", "trades"]
Currency = Literal["SOL", "BNB", "ETH"]
Scope = Literal["instance", "global"]
#: ``thesis``: post theses and replies, react and report in the user's name.
OidcScope = Literal["openid", "profile", "wallets", "onchain", "thesis", "offline_access"]
ThesisStance = Literal["bull", "bear"]
ThesisSort = Literal["new", "top"]
ThesisEmoji = Literal["like", "🔥", "🚀", "💎", "👀", "😂", "🤝", "💀", "🐂", "🐻"]
ThesisReportReason = Literal["spam", "scam", "abuse", "impersonation", "other"]
#: ``trades``: your users' trades. ``theses``: new theses, replies, reactions, removals.
StreamTopic = Literal["trades", "theses"]
ThesisScope = Literal["global", "instance"]

#: solana, bnb (BNB Chain), base, eth (Ethereum), rh (Robinhood Chain)
CHAINS: tuple[Chain, ...] = ("solana", "bnb", "base", "eth", "rh")
PERIODS: tuple[Period, ...] = ("6h", "1d", "7d", "30d")
LEADERBOARD_SORTS: tuple[LeaderboardSort, ...] = ("volume", "pnl", "pnl_usd", "win_rate", "trades")
SCOPES: tuple[Scope, ...] = ("instance", "global")

CURRENCY_BY_CHAIN: dict[Chain, Currency] = {
    "solana": "SOL",
    "bnb": "BNB",
    "base": "ETH",
    "eth": "ETH",
    "rh": "ETH",
}

#: Webhook events about platform users (white-label). ``data.sub`` is the user's csid_id.
PLATFORM_WEBHOOK_EVENTS: tuple[str, ...] = (
    "platform_user.created",
    "platform_user.claimed",
    "platform_user.x_connected",
    "wallet.added",
    "verification.expired",
)
#: Webhook events about trading competitions. Sent per instance, not per user.
COMPETITION_WEBHOOK_EVENTS: tuple[str, ...] = (
    "competition.started",
    "competition.updated",
    "competition.standings",
    "competition.ended",
)
#: Webhook event types.
WEBHOOK_EVENTS: tuple[str, ...] = (
    "wallet.verified",
    "wallet.removed",
    "profile.updated",
    "kol.granted",
    "consent.revoked",
    "thesis.created",
    "thesis.reply",
    "thesis.reaction",
    "webhook.test",
    *PLATFORM_WEBHOOK_EVENTS,
    *COMPETITION_WEBHOOK_EVENTS,
)

#: Reactions: "like" plus a fixed emoji set.
THESIS_EMOJIS: tuple[str, ...] = ("like", "🔥", "🚀", "💎", "👀", "😂", "🤝", "💀", "🐂", "🐻")
THESIS_REPORT_REASONS: tuple[str, ...] = ("spam", "scam", "abuse", "impersonation", "other")
#: Maximum thesis / reply length in characters.
THESIS_MAX_BODY = 1000
STREAM_TOPICS: tuple[str, ...] = ("trades", "theses")
#: global: theses written on every platform; instance: only on your instance.
THESIS_SCOPES: tuple[str, ...] = ("global", "instance")
#: Tokens per theses-stream connection.
MAX_THESES_STREAM_TOKENS = 200
DEFAULT_THESES_STREAM_URL = "wss://api-id.cabalspy.xyz/v1/theses/stream"
DEFAULT_THESIS_URL = "https://id.cabalspy.xyz/thesis/v1"
DEFAULT_THESIS_WS_URL = "wss://id.cabalspy.xyz/thesis/v1/ws"
#: Header that carries the instance's public client_id on every public thesis API call.
CLIENT_ID_HEADER = "X-CSID-Client-Id"

# ── white-label: platform users ──────────────────────────────────────────────

#: Users per POST /v1/platform-users/import call.
PLATFORM_IMPORT_MAX = 1000
#: Wallets per user in one create / import item / wallets-add call.
PLATFORM_MAX_WALLETS_PER_REQUEST = 10
#: The server rejects request bodies above 1 MB; bulk imports stay below this.
MAX_REQUEST_BODY_BYTES = 1_000_000
#: all: imported (unverified) wallets count; verified_only: only payment-verified ones.
WalletTrust = Literal["all", "verified_only"]
WALLET_TRUST: tuple[WalletTrust, ...] = ("all", "verified_only")
#: csid: part of the CabalSpy ID network (default); platform: only your platform sees its users.
DataScope = Literal["csid", "platform"]
DATA_SCOPES: tuple[DataScope, ...] = ("csid", "platform")
#: ``trust`` filter of the platform leaderboard: it can only narrow the instance setting.
LeaderboardTrust = Literal["all", "verified"]
#: Trust status of a platform user's wallet.
PlatformWalletStatus = Literal["verified", "active", "needs_verification", "verified_elsewhere", "pending"]
PlatformImportStatus = Literal["created", "updated", "unchanged", "rejected"]
VerificationStatus = Literal["pending", "verified", "cancelled", "expired"]
#: Payload formats the inbound URL understands.
INBOUND_FORMATS: tuple[str, ...] = ("csid", "privy", "dynamic", "generic")

# ── trading competitions ─────────────────────────────────────────────────────

CompetitionMetric = Literal["pnl_usd", "pnl", "volume_usd", "volume", "trades", "win_rate"]
COMPETITION_METRICS: tuple[CompetitionMetric, ...] = ("pnl_usd", "pnl", "volume_usd", "volume", "trades", "win_rate")
#: waiting: the start time passed, but fewer than min_participants joined.
CompetitionStatus = Literal["scheduled", "waiting", "running", "ended", "cancelled"]
COMPETITION_STATUSES: tuple[CompetitionStatus, ...] = ("scheduled", "waiting", "running", "ended", "cancelled")
#: opt_in: users join through the API; all_users: every platform user of the instance takes part.
CompetitionEnrollment = Literal["opt_in", "all_users"]
COMPETITION_ENROLLMENTS: tuple[CompetitionEnrollment, ...] = ("opt_in", "all_users")
#: Scheduled + running competitions at a time per developer account.
MAX_OPEN_COMPETITIONS = 5
