# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-13

### Added

- Token theses in the Data API (sync and async): `list_theses` / `iter_theses`, `thesis_summary`,
  `thesis`, `thesis_replies` / `iter_thesis_replies`, `latest_theses`, `user_theses`,
  `thesis_eligibility`, and writes in a user's name: `post_thesis`, `reply_to_thesis`,
  `react_to_thesis`, `report_thesis`, `delete_thesis`. `TypedDict`s `Thesis`, `ThesisPosition`,
  `ThesisSummary`, `ThesisEligibility`, `ThesisReactions`.
- `post_raw`. Writes are only retried after the API's own rate limit (`rate_limit_exceeded`),
  never after a server or network error.
- Stream: `events=["trades", "theses"]` and `mint=`; events `thesis`, `thesis.reply`,
  `thesis.reaction`, `thesis.removed`; `stream.theses()` iterator.
- `ThesisClient` / `AsyncThesisClient` for the public thesis API
  (`https://id.cabalspy.xyz/thesis/v1`) with a user's access token, and `ThesisLive` (`.live()`)
  for the public per-token websocket.
- Webhook type `thesis.created`, OAuth scope `thesis`.

## [0.1.0] - 2026-10-13

First release.

### Added

- `CabalSpyID` and `AsyncCabalSpyID` Data API clients for `https://api-id.cabalspy.xyz/v1`:
  `health`, `me`, `users`, `profile`, `wallet_lookup`, `tracker`, `history`, `holdings`,
  `pnl_calendar`, `leaderboard`, `latest_transactions`, with `instance` support, retries with
  backoff, rate limit info, `get_raw` / `pages` and iterators (`iter_users`, `iter_history`,
  `iter_leaderboard`).
- `CabalSpyIDStream` (async, `[stream]` extra) for the live trade stream (`/v1/stream`):
  auto-reconnect, heartbeat watchdog, fatal configuration errors, async iteration.
- `CabalSpyIDAuth` and `AsyncCabalSpyIDAuth` OpenID Connect helpers: discovery,
  `create_authorization_url` (PKCE S256, state, nonce), `handle_callback`, `exchange_code`,
  `refresh`, `revoke`, `userinfo`, `verify_id_token` and `verify_access_token` (ES256 via JWKS,
  PyJWT), `is_limited`, `generate_pkce`.
- `verify_webhook` / `sign_webhook` for Standard Webhooks signatures.
- `TypedDict` response types and `py.typed`.
- Exceptions: `BadRequestError`, `AuthenticationError`, `PermissionError`, `PlanUserLimitError`,
  `NotFoundError`, `RateLimitError`, `ServerError`, `APIConnectionError`,
  `InvalidResponseError`, `OAuthError`, `TokenVerificationError`, `WebhookVerificationError`.

[0.2.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CabalSpy/cabalspy-id-python/releases/tag/v0.1.0
