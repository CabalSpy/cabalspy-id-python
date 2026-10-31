"""Exception hierarchy for the CabalSpy ID SDK.

Every failure raised by this library is a subclass of :class:`CabalSpyIDError`,
so callers can branch on the kind of failure instead of parsing message strings.
"""

from __future__ import annotations

from typing import Any


class RateLimit:
    """Rate limit state parsed from the X-RateLimit-* response headers."""

    __slots__ = ("limit", "remaining", "reset")

    def __init__(
        self,
        limit: int | None = None,
        remaining: int | None = None,
        reset: int | None = None,
    ) -> None:
        #: Requests per second allowed by the plan.
        self.limit = limit
        self.remaining = remaining
        #: Seconds until the current one-second window resets.
        self.reset = reset

    def __repr__(self) -> str:
        return f"RateLimit(limit={self.limit}, remaining={self.remaining}, reset={self.reset})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RateLimit) and (self.limit, self.remaining, self.reset) == (
            other.limit,
            other.remaining,
            other.reset,
        )


class CabalSpyIDError(Exception):
    """Base class for every error raised by this library."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "unknown_error",
        request_id: str | None = None,
        docs: str | None = None,
        parameter: str | None = None,
        allowed: list[Any] | None = None,
        rate_limit: RateLimit | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        #: Link to the error's documentation.
        self.docs = docs
        self.parameter = parameter
        self.allowed = allowed
        self.rate_limit = rate_limit or RateLimit()
        #: The parsed response body, when there was one.
        self.body = body

    def __str__(self) -> str:
        parts = [self.message]
        if self.code and self.code != "unknown_error":
            detail = f"(code={self.code}"
            if self.parameter:
                detail += f", parameter={self.parameter}"
            if self.request_id:
                detail += f", request_id={self.request_id}"
            parts.append(detail + ")")
        return " ".join(parts)


class BadRequestError(CabalSpyIDError):
    """400 — missing_parameter, invalid_parameter, instance_required; platform users:
    wallet_required, invalid_address, invalid_return_url, invalid_body.

    Also 422 — callouts: no_price (the token has no market price yet, so a callout
    could not be tracked). ``status`` keeps the real HTTP status.
    """


class AuthenticationError(CabalSpyIDError):
    """401 — missing_api_key; public thesis API: client_id_required, invalid_client."""


class PermissionError_(CabalSpyIDError):
    """403 — invalid_api_key, product_not_enabled, no_instance, scope_not_allowed;
    public thesis API: origin_not_allowed; platform users: claim_disabled.

    Callouts: feature_not_enabled (callouts, and callout competitions, are switched on
    per instance on request), invalid_account, kol_only, not_a_holder, posting_paused,
    consent_required, sandbox_user.
    """


class PlanUserLimitError(PermissionError_):
    """403 — plan_user_limit.

    The person signed in beyond the plan's user limit: the platform receives no
    data for them until it upgrades. Creating a platform user beyond the limit
    raises it too; ``body`` then carries ``user_limit`` (and ``users``, ``plan``
    on live instances).
    """

    limited = True


class NotFoundError(CabalSpyIDError):
    """404 — profile_not_found, wallet_not_found, instance_not_found; platform users:
    platform_user_not_found, verification_not_found, invalid_inbound_url;
    competitions: competition_not_found; callouts: callout_not_found."""


class ConflictError(CabalSpyIDError):
    """409 — the request conflicts with the current state.

    Platform users: account_claimed, last_wallet, too_many_wallets,
    wallet_already_verified, already_verified, kol_badge, x_required,
    kol_not_eligible, volume_check_unavailable. Competitions: competition_limit,
    competition_closed, competition_full, late_join_closed. Callouts: already_called
    (the user called this token less than 24 hours ago).
    """


class RateLimitError(CabalSpyIDError):
    """429 — rate_limit_exceeded; public thesis API: rate_limited (Retry-After 60);
    platform users: rate_limited (new users or inbound events per minute),
    too_many_open_verifications; callouts: callout_cooldown (the instance's cooldown
    between two callouts of a user; ``retry_after`` can be hours, so it is never
    retried automatically); streams: too_many_connections."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        #: Seconds until the next request is allowed, from Retry-After.
        self.retry_after = retry_after


class ServerError(CabalSpyIDError):
    """5xx — internal_error, service_unavailable."""


class APIConnectionError(CabalSpyIDError):
    """Network failure, timeout or aborted connection."""


class InvalidResponseError(CabalSpyIDError):
    """The response was not valid JSON, or did not have the expected envelope."""


class OAuthError(CabalSpyIDError):
    """An OAuth error from the login endpoints or the authorization redirect.

    ``code`` and ``error`` are the OAuth ``error`` (invalid_grant,
    invalid_client, access_denied, ...).
    """

    def __init__(self, error: str, description: str | None = None, **kwargs: Any) -> None:
        super().__init__(f"{error}: {description}" if description else error, code=error, **kwargs)
        self.error = error
        self.error_description = description


class TokenVerificationError(CabalSpyIDError):
    """An ID or access token failed verification (signature, iss, aud, exp, nonce ...)."""


class WebhookVerificationError(CabalSpyIDError):
    """A webhook failed signature or timestamp verification."""


class PlatformImportError(CabalSpyIDError):
    """A bulk import stopped before every user was sent.

    ``result`` holds the results of the users that were imported (same shape as
    the return value), ``remaining`` the users that were not; pass them to
    ``bulk_import_platform_users`` again to resume. The error that stopped the
    import is ``__cause__`` (its ``status`` and ``code`` are copied here).
    """

    def __init__(self, message: str, *, result: dict[str, Any], remaining: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.result = result
        self.remaining = remaining


def error_from_status(
    status: int,
    body: dict[str, Any] | None,
    rate_limit: RateLimit,
    retry_after: float | None,
    fallback: str,
) -> CabalSpyIDError:
    """Maps an HTTP status and Data API error body onto the right exception class."""
    b = body or {}
    kwargs: dict[str, Any] = {
        "status": status,
        "code": b.get("code") or f"http_{status}",
        "request_id": b.get("request_id"),
        "docs": b.get("docs"),
        "parameter": b.get("parameter"),
        "allowed": b.get("allowed"),
        "rate_limit": rate_limit,
        "body": body,
    }
    message = b.get("message") or fallback
    body_wait = b.get("retry_after")
    if retry_after is None and isinstance(body_wait, (int, float)) and not isinstance(body_wait, bool):
        retry_after = float(body_wait)

    if status in (400, 422):
        return BadRequestError(message, **kwargs)
    if status == 401:
        return AuthenticationError(message, **kwargs)
    if status == 403:
        if b.get("code") == "plan_user_limit":
            return PlanUserLimitError(message, **kwargs)
        return PermissionError_(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 409:
        return ConflictError(message, **kwargs)
    if status == 429:
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    if status >= 500:
        return ServerError(message, **kwargs)
    return CabalSpyIDError(message, **kwargs)


#: 429 codes that are not worth an automatic retry (the wait can be hours).
NOT_RETRYABLE_CODES = frozenset({"callout_cooldown"})


def is_retryable(exc: BaseException) -> bool:
    """True for failures where retrying with backoff is worthwhile."""
    if isinstance(exc, CabalSpyIDError) and exc.code in NOT_RETRYABLE_CODES:
        return False
    return isinstance(exc, (RateLimitError, ServerError, APIConnectionError))
