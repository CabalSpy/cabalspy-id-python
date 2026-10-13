"""CabalSpy ID — the verified social layer for crypto trading.

Login with CabalSpy ID (OpenID Connect), the Data API for verified wallets, KOL
badges and trading stats, the live trade stream and webhook verification.

    from cabalspy_id import CabalSpyID, CabalSpyIDAuth, verify_webhook

    auth = CabalSpyIDAuth(client_id="csid_...", client_secret="csid_sk_...",
                          redirect_uri="https://your.app/callback")
    csid = CabalSpyID()                     # reads CABALSPY_ID_API_KEY / CABALSPY_API_KEY
    profile = csid.profile(csid_id=claims["sub"])

Docs: https://docs.cabalspy.xyz/cabalspy-id
"""

from ._client import AsyncCabalSpyID, CabalSpyID, Envelope
from ._constants import (
    CHAINS,
    CURRENCY_BY_CHAIN,
    DEFAULT_BASE_URL,
    DEFAULT_ISSUER,
    DEFAULT_STREAM_URL,
    LEADERBOARD_SORTS,
    PERIODS,
    SCOPES,
    SDK_VERSION,
    WEBHOOK_EVENTS,
    Chain,
    Currency,
    LeaderboardSort,
    OidcScope,
    Period,
    Scope,
)
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    CabalSpyIDError,
    InvalidResponseError,
    NotFoundError,
    OAuthError,
    PlanUserLimitError,
    RateLimit,
    RateLimitError,
    ServerError,
    TokenVerificationError,
    WebhookVerificationError,
)
from ._errors import PermissionError_ as PermissionError
from ._oidc import (
    AsyncCabalSpyIDAuth,
    AuthorizationRequest,
    CabalSpyIDAuth,
    LoginResult,
    PkcePair,
    generate_pkce,
    is_limited,
)
from ._types import (
    ActiveHoldings,
    ActiveTokens,
    CabalSpyIDClaims,
    DiscoveryDocument,
    HealthResponse,
    HistoryResponse,
    HistoryToken,
    HistoryTrade,
    HoldingsResponse,
    HoldingToken,
    LeaderboardEntry,
    LeaderboardResponse,
    LifetimeStats,
    MeResponse,
    Pagination,
    PeriodStats,
    PnlCalendarDay,
    PnlCalendarMonth,
    PnlCalendarResponse,
    PnlChartPoint,
    Profile,
    ResponseMeta,
    TokenOverview,
    TokenResponse,
    TrackerResponse,
    TrackerTrade,
    Trade,
    TradeOwner,
    TraderProfile,
    VerifiedWallet,
    WalletClaim,
    WalletLookupResponse,
    WebhookEvent,
    WinRateBuckets,
    WinRateDistribution,
    XProfileClaim,
)
from ._webhooks import HeaderSource, sign_webhook, verify_webhook

__version__ = SDK_VERSION


def __getattr__(name: str) -> object:
    # The stream needs the optional websockets dependency; import it lazily.
    if name in ("CabalSpyIDStream", "STREAM_EVENTS"):
        from . import _stream

        return getattr(_stream, name)
    raise AttributeError(f"module 'cabalspy_id' has no attribute {name!r}")


__all__ = [
    "__version__",
    # clients
    "CabalSpyID",
    "AsyncCabalSpyID",
    "CabalSpyIDStream",
    "Envelope",
    "CabalSpyIDAuth",
    "AsyncCabalSpyIDAuth",
    "AuthorizationRequest",
    "LoginResult",
    "PkcePair",
    "generate_pkce",
    "is_limited",
    "verify_webhook",
    "sign_webhook",
    "HeaderSource",
    # errors
    "CabalSpyIDError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionError",
    "PlanUserLimitError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "APIConnectionError",
    "InvalidResponseError",
    "OAuthError",
    "TokenVerificationError",
    "WebhookVerificationError",
    "RateLimit",
    # constants
    "SDK_VERSION",
    "CHAINS",
    "PERIODS",
    "LEADERBOARD_SORTS",
    "SCOPES",
    "CURRENCY_BY_CHAIN",
    "WEBHOOK_EVENTS",
    "STREAM_EVENTS",
    "DEFAULT_BASE_URL",
    "DEFAULT_STREAM_URL",
    "DEFAULT_ISSUER",
    "Chain",
    "Period",
    "LeaderboardSort",
    "Currency",
    "Scope",
    "OidcScope",
    # response types
    "ResponseMeta",
    "Pagination",
    "HealthResponse",
    "MeResponse",
    "Profile",
    "VerifiedWallet",
    "WalletLookupResponse",
    "TraderProfile",
    "PeriodStats",
    "WinRateBuckets",
    "WinRateDistribution",
    "ActiveTokens",
    "HistoryToken",
    "PnlChartPoint",
    "TrackerTrade",
    "TrackerResponse",
    "LifetimeStats",
    "TokenOverview",
    "HistoryTrade",
    "HistoryResponse",
    "HoldingToken",
    "ActiveHoldings",
    "HoldingsResponse",
    "PnlCalendarDay",
    "PnlCalendarMonth",
    "PnlCalendarResponse",
    "LeaderboardEntry",
    "LeaderboardResponse",
    "Trade",
    "TradeOwner",
    "CabalSpyIDClaims",
    "XProfileClaim",
    "WalletClaim",
    "TokenResponse",
    "DiscoveryDocument",
    "WebhookEvent",
]
