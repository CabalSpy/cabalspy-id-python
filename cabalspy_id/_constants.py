"""Chains, periods and other fixed values of the CabalSpy ID Data API."""

from __future__ import annotations

from typing import Literal

SDK_VERSION = "0.1.0"
USER_AGENT = f"cabalspy-id-python/{SDK_VERSION}"

DEFAULT_BASE_URL = "https://api-id.cabalspy.xyz/v1"
DEFAULT_STREAM_URL = "wss://api-id.cabalspy.xyz/v1/stream"
DEFAULT_ISSUER = "https://id.cabalspy.xyz"

Chain = Literal["solana", "bnb", "base", "eth", "rh"]
Period = Literal["6h", "1d", "7d", "30d"]
LeaderboardSort = Literal["volume", "pnl", "pnl_usd", "win_rate", "trades"]
Currency = Literal["SOL", "BNB", "ETH"]
Scope = Literal["instance", "global"]
OidcScope = Literal["openid", "profile", "wallets", "onchain", "offline_access"]

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
    "webhook.test",
)
