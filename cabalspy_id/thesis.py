"""``cabalspy_id.thesis`` — token theses: holders-only opinions on a token with
the author's real position, replies, reactions and moderation notifications.

- ``CabalSpyID`` / ``AsyncCabalSpyID``: Data API thesis methods (``list_theses``,
  ``post_thesis`` in a user's name, ...)
- ``ThesisClient`` / ``AsyncThesisClient``: public thesis API with a user's access token, ``live()``
- ``ThesesStream``: live theses for up to 200 tokens per connection (every plan)

    from cabalspy_id.thesis import CabalSpyID, ThesisClient

The same objects as ``cabalspy_id``.
"""

from typing import Any

import cabalspy_id as _root
from cabalspy_id import (
    CHAINS,
    DEFAULT_THESES_STREAM_URL,
    DEFAULT_THESIS_URL,
    DEFAULT_THESIS_WS_URL,
    MAX_THESES_STREAM_TOKENS,
    SDK_VERSION,
    THESIS_EMOJIS,
    THESIS_MAX_BODY,
    THESIS_REPORT_REASONS,
    THESIS_SCOPES,
    APIConnectionError,
    AsyncCabalSpyID,
    AsyncThesisClient,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    CabalSpyIDError,
    Chain,
    HeaderSource,
    InvalidResponseError,
    NotFoundError,
    Pagination,
    PermissionError,
    PlanUserLimitError,
    RateLimitError,
    ServerError,
    Thesis,
    ThesisAuthor,
    ThesisClient,
    ThesisEligibility,
    ThesisEmoji,
    ThesisLive,
    ThesisNotices,
    ThesisNotification,
    ThesisNotifications,
    ThesisPage,
    ThesisPnl,
    ThesisPosition,
    ThesisReactions,
    ThesisReactor,
    ThesisReportReason,
    ThesisScope,
    ThesisSort,
    ThesisStance,
    ThesisSummary,
    ThesisToken,
    TokenThesesPage,
    WebhookEvent,
    WebhookVerificationError,
    sign_webhook,
    verify_webhook,
)

__version__ = SDK_VERSION

__all__ = [
    "__version__",
    "SDK_VERSION",
    # clients
    "CabalSpyID",
    "AsyncCabalSpyID",
    "ThesisClient",
    "AsyncThesisClient",
    "ThesisLive",
    "ThesesStream",
    "TokenThesesPage",
    "ThesisPage",
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
    "WebhookVerificationError",
    # constants
    "CHAINS",
    "THESIS_EMOJIS",
    "THESIS_REPORT_REASONS",
    "THESIS_MAX_BODY",
    "THESIS_SCOPES",
    "THESIS_EVENTS",
    "THESES_STREAM_EVENTS",
    "MAX_THESES_STREAM_TOKENS",
    "DEFAULT_THESIS_URL",
    "DEFAULT_THESIS_WS_URL",
    "DEFAULT_THESES_STREAM_URL",
    "Chain",
    "ThesisScope",
    "ThesisStance",
    "ThesisSort",
    "ThesisEmoji",
    "ThesisReportReason",
    # types
    "Pagination",
    "WebhookEvent",
    "Thesis",
    "ThesisAuthor",
    "ThesisPnl",
    "ThesisPosition",
    "ThesisToken",
    "ThesisSummary",
    "ThesisEligibility",
    "ThesisNotification",
    "ThesisNotifications",
    "ThesisNotices",
    "ThesisReactor",
    "ThesisReactions",
]


def __getattr__(name: str) -> Any:
    # The streams need the optional websockets dependency: loaded lazily, like the root package.
    if name in ("ThesesStream", "THESES_STREAM_EVENTS", "THESIS_EVENTS"):
        return getattr(_root, name)
    raise AttributeError(f"module 'cabalspy_id.thesis' has no attribute {name!r}")
