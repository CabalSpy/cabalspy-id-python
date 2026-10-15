"""``cabalspy_id.trade_feed`` — Trade Feed: your users add CabalSpy ID traders
(public trading, verified wallets) to their Trade Feed and you tell them about
every trade and thesis of those traders.

- ``CabalSpyID`` / ``AsyncCabalSpyID``: Data API Trade Feed methods in a user's
  name (scope ``trade_feed``): ``trade_feed``, ``trade_feed_traders``,
  ``add_to_trade_feed``, ``remove_from_trade_feed``, ``trade_feed_notifications``
  (+ ``iter_...``)
- ``TradeFeedStream``: live ``trade_feed.trade`` / ``trade_feed.thesis`` events with ``recipients``
- ``is_trade_feed_event`` and friends: type guards for the ``trade_feed.*`` webhooks

    from cabalspy_id.trade_feed import CabalSpyID, verify_webhook, is_trade_feed_trade_event

The same objects as ``cabalspy_id``.
"""

from typing import Any

import cabalspy_id as _root
from cabalspy_id import (
    CHAINS,
    CURRENCY_BY_CHAIN,
    DEFAULT_TRADE_FEED_STREAM_URL,
    SDK_VERSION,
    TRADE_FEED_EVENTS,
    TRADE_FEED_FILTERS,
    TRADE_FEED_MAX_TRADERS,
    APIConnectionError,
    AsyncCabalSpyID,
    AuthenticationError,
    BadRequestError,
    CabalSpyID,
    CabalSpyIDError,
    Chain,
    Currency,
    Envelope,
    HandleKind,
    HeaderSource,
    InvalidResponseError,
    NotFoundError,
    Pagination,
    PermissionError,
    PlanUserLimitError,
    RateLimitError,
    ServerError,
    TradeFeedAddResult,
    TradeFeedEntry,
    TradeFeedEvent,
    TradeFeedEventData,
    TradeFeedEventType,
    TradeFeedFilter,
    TradeFeedItem,
    TradeFeedLabel,
    TradeFeedLinks,
    TradeFeedMinNative,
    TradeFeedNotification,
    TradeFeedRemoveResult,
    TradeFeedSettings,
    TradeFeedThesis,
    TradeFeedThesisData,
    TradeFeedThesisEvent,
    TradeFeedThesisItem,
    TradeFeedTrade,
    TradeFeedTradeData,
    TradeFeedTradeEvent,
    TradeFeedTradeItem,
    TradeFeedTrader,
    WebhookEvent,
    WebhookVerificationError,
    handle_kind,
    has_x,
    is_trade_feed_event,
    is_trade_feed_thesis_event,
    is_trade_feed_trade_event,
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
    "TradeFeedStream",
    "Envelope",
    "verify_webhook",
    "sign_webhook",
    "is_trade_feed_event",
    "is_trade_feed_trade_event",
    "is_trade_feed_thesis_event",
    "HeaderSource",
    "has_x",
    "handle_kind",
    "HandleKind",
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
    "CURRENCY_BY_CHAIN",
    "TRADE_FEED_EVENTS",
    "TRADE_FEED_FILTERS",
    "TRADE_FEED_MAX_TRADERS",
    "TRADE_FEED_STREAM_EVENTS",
    "DEFAULT_TRADE_FEED_STREAM_URL",
    "Chain",
    "Currency",
    "TradeFeedFilter",
    "TradeFeedLabel",
    "TradeFeedEventType",
    # types
    "Pagination",
    "WebhookEvent",
    "TradeFeedTrader",
    "TradeFeedTrade",
    "TradeFeedThesis",
    "TradeFeedLinks",
    "TradeFeedTradeItem",
    "TradeFeedThesisItem",
    "TradeFeedItem",
    "TradeFeedMinNative",
    "TradeFeedSettings",
    "TradeFeedEntry",
    "TradeFeedAddResult",
    "TradeFeedRemoveResult",
    "TradeFeedNotification",
    "TradeFeedTradeData",
    "TradeFeedThesisData",
    "TradeFeedEventData",
    "TradeFeedTradeEvent",
    "TradeFeedThesisEvent",
    "TradeFeedEvent",
]


def __getattr__(name: str) -> Any:
    # The stream needs the optional websockets dependency: loaded lazily, like the root package.
    if name in ("TradeFeedStream", "TRADE_FEED_STREAM_EVENTS"):
        return getattr(_root, name)
    raise AttributeError(f"module 'cabalspy_id.trade_feed' has no attribute {name!r}")
