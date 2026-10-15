# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.5.1] - 2026-10-15

### Changed

- People can sign in with X, Telegram or Google. Types match accounts without X: `x` is
  `None` in userinfo claims and Data API profiles, `twitter` is `None` in profiles, trading
  profile blocks and leaderboards, `telegram` is documented (`https://t.me/<name>` or `""`),
  handles may be `tg.<name>` or `id.<hex>`.

### Added

- `has_x()` and `handle_kind()` helpers and a README section "Users without X".

## [0.5.0] - 2026-10-14

### Added

- Modules `cabalspy_id.api` (Data API, trade stream, login, webhooks) and `cabalspy_id.thesis`
  (thesis methods, `ThesisClient`, `ThesesStream`), exposing the same objects as `cabalspy_id`.
- Packages table (socialfi-api, socialfi-thesis, socialfi-widget) in the README.

## [0.4.1] - 2026-10-14

### Changed

- Package description, keywords, classifiers and README: CabalSpy ID as a SocialFi API & SDK. No code changes.

## [0.4.0] - 2026-10-14

### Added

- `Thesis["reacted_by"]` (who reacted recently) and `Thesis["latest_replies"]` (reply preview).
- Moderation notifications: Data API `thesis_notifications(csid_id)` and
  `appeal_thesis_decision(csid_id, notification_id, message)`; public `ThesisClient.notifications()`,
  `mark_notifications_read()` and `appeal(notification_id, message)`. `TypedDict`s
  `ThesisNotification`, `ThesisNotifications`, `ThesisNotices`; `me()` returns `notices`.
- Webhook types `thesis.reply` (`data["reply"]`) and `thesis.reaction`
  (`thesis_id`, `chain`, `mint`, `emoji`, `on`, `reactions`).
- Error code `reporting_paused` (403, `PermissionError`) documented.

## [0.3.0] - 2026-10-13

### Added

- `scope` (`global` | `instance`) on `list_theses`, `iter_theses`, `thesis_summary` and
  `latest_theses`.
- `ThesesStream` (`client.theses_stream()`, async) for `wss://api-id.cabalspy.xyz/v1/theses/stream`
  (every plan): `subscribe` / `unsubscribe` up to 200 tokens, `subscribe_all` / `unsubscribe_all`,
  subscriptions restored after reconnects, heartbeat watchdog, handlers and async iteration.
- `ThesisClient` / `AsyncThesisClient`: `scope` and `client_id` (reads, `live()`, post attribution).

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

[0.5.1]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CabalSpy/cabalspy-id-python/releases/tag/v0.1.0
