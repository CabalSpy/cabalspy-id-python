"""Chains, periods and other fixed values of the CabalSpy ID Data API."""

from __future__ import annotations

from typing import Literal

SDK_VERSION = "0.3.0"
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

#: Webhook event types.
WEBHOOK_EVENTS: tuple[str, ...] = (
    "wallet.verified",
    "wallet.removed",
    "profile.updated",
    "kol.granted",
    "consent.revoked",
    "thesis.created",
    "webhook.test",
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
